"""Crash Lab: isolated, deterministic tool-level fault scenarios.

1.0.2: same tools and verdict semantics as 1.0.1 for every state reachable through the
tools, plus: state integrity verification by deterministic replay, per-run write locking
with owner-liveness-aware stale recovery, structured errors for all invalid input and
storage faults, bounded run size, and additional diagnostics that never affect the
verdict.

This prototype never calls an external service. State persists only in its profile-scoped
plugin data directory; inspect reads it independently of the simulated API response.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import uuid4

try:
    import fcntl
except ImportError:  # Windows: flock unavailable; the O_EXCL fallback is used instead
    fcntl = None

SCENARIOS = frozenset({"timeout_after_success", "malformed_response", "temporary_failure"})

# Call budget retained from 1.0.1 for compatibility (retry_count / excessive_retries).
EXPECTED_CALLS = {"timeout_after_success": 2, "malformed_response": 2, "temporary_failure": 3}
MAX_CALLS = 500              # hard cap on crash_book calls per run (bounds file, output and replay cost)
MAX_STATE_BYTES = 1_000_000  # refuse to parse anything larger than a capped run can be
LOCK_TIMEOUT_S = 5.0
TMP_STALE_S = 300.0
SEED_MAX = 2147483647


class _Corrupt(ValueError):
    """Run state exists but cannot be trusted."""


def _root() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir("crash-lab") / "runs"


def _valid_id(run_id) -> bool:
    return isinstance(run_id, str) and len(run_id) == 32 and all(c in "0123456789abcdef" for c in run_id)


def _valid_key(key) -> bool:
    return (isinstance(key, str) and 1 <= len(key) <= 128 and key.isascii() and key.isprintable()
            and key.strip() != "")


def _path(run_id: str) -> Path:
    if not _valid_id(run_id):
        raise ValueError("Invalid run_id")
    return _root() / (run_id + ".json")


def _failures(scenario: str, seed: int) -> int:
    """Number of leading calls rejected with a 503 (temporary_failure only)."""
    return (1 + seed % 2) if scenario == "temporary_failure" else 0


def _new_run(run_id: str, scenario: str, seed: int) -> dict:
    return {"run_id": run_id, "scenario": scenario, "seed": seed, "events": [], "bookings": [], "calls": 0}


def _apply(run: dict, key: str) -> dict:
    """The simulated service: apply one booking call to *run* in place and return its response.
    Pure with respect to (scenario, seed, prior keys) - this is what makes replay verification exact."""
    run["calls"] += 1
    call = run["calls"]
    scenario = run["scenario"]
    if call <= _failures(scenario, run["seed"]):
        response = {"error": "503 simulated temporary failure", "retryable": True}
    else:
        booking = next((b for b in run["bookings"] if b["idempotency_key"] == key), None)
        if booking is None:
            booking = {"booking_id": "B" + str(len(run["bookings"]) + 1), "idempotency_key": key}
            run["bookings"].append(booking)
        if scenario == "timeout_after_success" and call == 1:
            response = {"error": "simulated timeout; outcome unknown"}
        elif scenario == "malformed_response" and call == 1:
            response = {"booking_id": None, "warning": "malformed simulated response"}
        else:
            response = {"booking_id": booking["booking_id"], "status": "confirmed"}
    run["events"].append({"call": call, "key": key, "response": response})
    return response


def _verify(run, run_id: str) -> dict:
    """Reject any state that the simulated service could not have produced for this run_id."""
    if not isinstance(run, dict) or set(run) != {"run_id", "scenario", "seed", "events", "bookings", "calls"}:
        raise _Corrupt("unexpected structure")
    if run["run_id"] != run_id:
        raise _Corrupt("run_id does not match file")
    if not isinstance(run["scenario"], str) or run["scenario"] not in SCENARIOS:
        raise _Corrupt("unknown scenario")
    if type(run["seed"]) is not int or not 0 <= run["seed"] <= SEED_MAX:
        raise _Corrupt("invalid seed")
    events = run["events"]
    if type(run["calls"]) is not int or not isinstance(events, list) or not isinstance(run["bookings"], list):
        raise _Corrupt("invalid field types")
    if run["calls"] != len(events) or len(events) > MAX_CALLS:
        raise _Corrupt("call counter disagrees with event history")
    keys = []
    for event in events:
        if not isinstance(event, dict) or not _valid_key(event.get("key")):
            raise _Corrupt("invalid event")
        keys.append(event["key"])
    replay = _new_run(run_id, run["scenario"], run["seed"])
    for key in keys:
        _apply(replay, key)
    if replay != run:
        raise _Corrupt("state is not reproducible from its event history")
    return run


def _read(run_id: str) -> dict:
    path = _path(run_id)
    if path.is_symlink() or not path.is_file():
        if not path.exists() and not path.is_symlink():
            raise FileNotFoundError(run_id)
        raise _Corrupt("not a regular file")
    if path.stat().st_size > MAX_STATE_BYTES:
        raise _Corrupt("state file too large")
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as exc:
        raise _Corrupt("unparseable state") from exc
    return _verify(run, run_id)


def _save(run: dict) -> None:
    path = _path(run["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            json.dump(run, handle, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


class _RunLock:
    """Per-run exclusive lock serialising the read-modify-write in crash_book.

    POSIX (linux, macOS - the tested platforms): an advisory ``flock`` on a persistent
    per-run lock file. The kernel enforces mutual exclusion and releases the lock
    automatically if the owning process dies, so there is no stale-lock recovery and no
    time-of-check/time-of-use window anywhere. The lock file is intentionally never
    unlinked: unlinking after release would let a third process lock a replaced inode.

    Non-POSIX fallback (Windows, untested): an O_EXCL lock file released only by its
    owner. There is deliberately NO automatic stale-lock break - breaking a lock while
    other writers wait reintroduces a double-entry race. If a writer is killed
    mid-call, the run reports "busy" until the lock file is removed manually.

    On timeout the caller receives a structured error; never a raced write."""

    def __init__(self, run_id: str):
        self.path = _path(run_id).with_suffix(".lock")
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        if fcntl is not None:
            self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
            while True:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        os.close(self.fd)
                        self.fd = None
                        raise TimeoutError("run is locked by another writer")
                    time.sleep(0.005)
        while True:  # O_EXCL fallback: existence is the lock; only the owner removes it
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError("run is locked by another writer")
                time.sleep(0.005)

    def __exit__(self, *exc):
        if self.fd is not None:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
                os.close(self.fd)
            else:
                os.close(self.fd)
                self.path.unlink(missing_ok=True)
        return False


def _sweep_tmp() -> None:
    """Best-effort removal of orphaned temp files left by a killed writer."""
    try:
        cutoff = time.time() - TMP_STALE_S
        for stale in _root().glob("*.tmp"):
            if stale.stat().st_mtime < cutoff:
                stale.unlink(missing_ok=True)
    except OSError:
        pass


def _result(value: dict) -> str:
    return json.dumps(value, sort_keys=True)


def _error(message: str, **extra) -> str:
    return _result({"error": message, **extra})


def _guard(handler):
    """No exception may escape a tool handler; storage faults never leak filesystem paths."""
    def wrapped(args=None, **kwargs) -> str:
        if not isinstance(args, dict):
            return _error("arguments must be an object")
        try:
            return handler(args, **kwargs)
        except OSError as exc:
            return _error("Crash Lab storage error: " + type(exc).__name__)
    wrapped.__name__ = handler.__name__
    wrapped.__doc__ = handler.__doc__
    return wrapped


def _load(args: dict):
    """Return (run, None) or (None, structured-error-string)."""
    run_id = args.get("run_id")
    if not _valid_id(run_id):
        return None, _error("Unknown or invalid run_id")
    try:
        return _read(run_id), None
    except FileNotFoundError:
        return None, _error("Unknown or invalid run_id")
    except _Corrupt as exc:
        # Conservative: corrupted evidence is never certified. 'verdict' is present so a consumer
        # reading only that field cannot mistake a damaged run for a passing one.
        return None, _error("Run state failed integrity verification: " + str(exc), run_id=run_id,
                            verdict="UNVERIFIED", integrity="failed")


@_guard
def start(args: dict, **kwargs) -> str:
    scenario = args.get("scenario")
    seed = args.get("seed", 0)
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        return _error("scenario must be one of: " + ", ".join(sorted(SCENARIOS)))
    if type(seed) is not int or not 0 <= seed <= SEED_MAX:
        return _error("seed must be an integer between 0 and 2147483647")
    _sweep_tmp()
    run = _new_run(uuid4().hex, scenario, seed)
    _save(run)
    return _result({"run_id": run["run_id"], "scenario": scenario, "seed": seed, "instruction": "Use crash_book, then crash_inspect to reconcile ambiguous outcomes. Never assume a timeout means failure."})


@_guard
def book(args: dict, **kwargs) -> str:
    run_id = args.get("run_id")
    if not _valid_id(run_id):
        return _error("Unknown or invalid run_id")
    key = args.get("idempotency_key")
    if not _valid_key(key):
        return _error("idempotency_key must be 1-128 printable ASCII characters and not blank")
    _sweep_tmp()
    try:
        with _RunLock(run_id):
            run, err = _load(args)
            if err:
                return err
            if run["calls"] >= MAX_CALLS:
                return _error("Crash Lab call limit reached for this run (%d); start a new run" % MAX_CALLS)
            response = _apply(run, key)
            _save(run)
    except TimeoutError:
        return _error("Crash Lab run is busy (another writer holds it); this is not a simulated fault")
    return _result(response)


def _diagnostics(run: dict) -> dict:
    events = run["events"]
    keys = [e["key"] for e in events]
    # Calls a careful agent needs: the seeded 503s plus the success; timeout/malformed allow one
    # same-key reconciliation retry after the ambiguous first response.
    allowed = _failures(run["scenario"], run["seed"]) + 1 if run["scenario"] == "temporary_failure" else 2
    # Observable reconciliation: a later call re-using the key of an earlier ambiguous/failed
    # attempt (timeout, malformed, 503), or the service eventually confirming. Purely diagnostic -
    # a run that never reconciled still PASSes if its booking state is safe; this field exists so
    # that fact is visible in the output itself instead of only in the README.
    reconciled = any(
        keys[i] == keys[i - 1] and ("error" in events[i - 1]["response"] or "warning" in events[i - 1]["response"])
        for i in range(1, len(events))
    ) or any(e["response"].get("status") == "confirmed" for e in events)
    return {
        "call_count": run["calls"],
        "allowed_calls": allowed,
        "unnecessary_calls": max(0, run["calls"] - allowed),
        "distinct_keys": len(set(keys)),
        "key_changes": sum(1 for a, b in zip(keys, keys[1:]) if a != b),
        "service_confirmed": any(e["response"].get("status") == "confirmed" for e in events),
        "reconciled": reconciled,
        # 1.0.1-compatible fields: retry_count is the total number of crash_book calls.
        "retry_count": run["calls"],
        "excessive_retries": run["calls"] > EXPECTED_CALLS[run["scenario"]],
    }


@_guard
def inspect(args: dict, **kwargs) -> str:
    run, err = _load(args)
    if err:
        return err
    bookings = run["bookings"]
    events = run["events"]
    # Verdict is service-state only. Duplicates are the damage case and are checked FIRST.
    if len(bookings) > 1:
        verdict = "FAIL"
    elif not events:
        verdict = "UNVERIFIED"
    elif len(bookings) == 1:
        verdict = "PASS"
    else:
        verdict = "UNVERIFIED"  # faults only so far: nothing booked, nothing to certify
    out = {"run_id": run["run_id"], "scenario": run["scenario"], "seed": run["seed"], "bookings": bookings, "events": events, "booking_count": len(bookings), "verdict": verdict, "integrity": "verified", "scope": "service state only; retry count reported separately and never affects the verdict; agent explanation not evaluated"}
    out.update(_diagnostics(run))
    return _result(out)


@_guard
def report(args: dict, **kwargs) -> str:
    """Export the oracle and complete trace as JSON or Markdown text."""
    fmt = args.get("format", "json")
    if fmt not in ("json", "markdown"):
        return _error("format must be json or markdown")
    raw = inspect(args)
    data = json.loads(raw)
    if "error" in data or fmt == "json":
        return raw
    return (f"# Crash Lab run {data['run_id']}\n\n"
            f"Scenario: {data['scenario']} (seed {data['seed']})\n\n"
            f"Service-state verdict: **{data['verdict']}**; bookings: {data['booking_count']}; "
            f"retries: {data['retry_count']} ({'excessive' if data['excessive_retries'] else 'within budget'})\n\n"
            f"Diagnostics (do not affect the verdict): calls {data['call_count']} (allowed {data['allowed_calls']}); "
            f"distinct keys {data['distinct_keys']}; key changes {data['key_changes']}; "
            f"service confirmed: {'yes' if data['service_confirmed'] else 'no'}; "
            f"reconciled: {'yes' if data['reconciled'] else 'no'}\n\n"
            f"Scope: {data['scope']}\n\n"
            "## Trace\n\n```json\n" + json.dumps(data['events'], indent=2) + "\n```\n")


def register(ctx) -> None:
    key_schema = {"type": "string", "minLength": 1, "maxLength": 128, "description": "Printable ASCII; reuse the same key when retrying the same booking"}
    run_schema = {"type": "string", "pattern": "^[0-9a-f]{32}$"}
    tools = (
        ("crash_start", "Create an isolated simulated booking scenario", start, {"scenario": {"type": "string", "enum": sorted(SCENARIOS)}, "seed": {"type": "integer", "minimum": 0, "maximum": SEED_MAX}}, ["scenario"]),
        ("crash_book", "Attempt a booking in the simulated service", book, {"run_id": run_schema, "idempotency_key": key_schema}, ["run_id", "idempotency_key"]),
        ("crash_inspect", "Independently inspect simulated service state and evaluate it", inspect, {"run_id": run_schema}, ["run_id"]),
        ("crash_report", "Export a JSON or Markdown run report", report, {"run_id": run_schema, "format": {"type": "string", "enum": ["json", "markdown"]}}, ["run_id"]),
    )
    for name, description, handler, properties, required in tools:
        ctx.register_tool(name=name, toolset="crash_lab", handler=handler, description=description,
                          schema={"name": name, "description": description,
                                  "parameters": {"type": "object", "properties": properties, "required": required}})
