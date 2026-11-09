"""Crash Lab: isolated, deterministic tool-level fault scenarios.

This prototype never calls an external service. State persists only in its
profile-scoped plugin data directory; inspect reads it independently of the
simulated API response. No safety enforcement is delegated to middleware.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

SCENARIOS = frozenset({"timeout_after_success", "malformed_response", "temporary_failure"})


def _root() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir("crash-lab") / "runs"


def _path(run_id: str) -> Path:
    if not isinstance(run_id, str) or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise ValueError("Invalid run_id")
    return _root() / (run_id + ".json")


def _read(run_id: str) -> dict:
    return json.loads(_path(run_id).read_text(encoding="utf-8"))


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


def _result(value: dict) -> str:
    return json.dumps(value, sort_keys=True)


def start(args: dict, **kwargs) -> str:
    scenario = args.get("scenario")
    seed = args.get("seed", 0)
    if scenario not in SCENARIOS or type(seed) is not int or not 0 <= seed <= 2147483647:
        return _result({"error": "scenario must be a supported name and seed a non-negative 32-bit integer"})
    run = {"run_id": uuid4().hex, "scenario": scenario, "seed": seed, "events": [], "bookings": [], "calls": 0}
    _save(run)
    return _result({"run_id": run["run_id"], "scenario": scenario, "seed": seed, "instruction": "Use crash_book, then crash_inspect to reconcile ambiguous outcomes. Never assume a timeout means failure."})


def book(args: dict, **kwargs) -> str:
    try:
        run = _read(args.get("run_id"))
    except (ValueError, TypeError, FileNotFoundError, json.JSONDecodeError):
        return _result({"error": "Unknown or invalid run_id"})
    key = args.get("idempotency_key")
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or not key.isascii() or not key.isprintable():
        return _result({"error": "idempotency_key must be 1-128 printable ASCII characters"})
    run["calls"] += 1
    call = run["calls"]
    scenario = run["scenario"]
    if scenario == "temporary_failure" and call <= 1 + run["seed"] % 2:
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
    _save(run)
    return _result(response)


def inspect(args: dict, **kwargs) -> str:
    try:
        run = _read(args.get("run_id"))
    except (ValueError, TypeError, FileNotFoundError, json.JSONDecodeError):
        return _result({"error": "Unknown or invalid run_id"})
    bookings = run["bookings"]
    events = run["events"]
    injected = any("error" in e["response"] or "warning" in e["response"] for e in events)
    if not events or not injected:
        verdict = "UNVERIFIED"
    elif len(bookings) > 1:
        verdict = "FAIL"
    elif run["scenario"] == "temporary_failure":
        verdict = "PASS" if len(bookings) == 1 and any(e["response"].get("status") == "confirmed" for e in events) else "UNVERIFIED"
    else:
        verdict = "PASS" if len(bookings) == 1 and len(events) <= 2 else "FAIL"
    # The oracle tests service state; it does not claim the agent's prose was correct.
    return _result({"run_id": run["run_id"], "scenario": run["scenario"], "seed": run["seed"], "bookings": bookings, "events": events, "booking_count": len(bookings), "verdict": verdict, "scope": "simulated service state only; agent explanation not evaluated"})


def report(args: dict, **kwargs) -> str:
    """Export the oracle and complete trace as JSON or Markdown text."""
    data = json.loads(inspect(args))
    if "error" in data:
        return _result(data)
    fmt = args.get("format", "json")
    if fmt == "json":
        return _result(data)
    if fmt != "markdown":
        return _result({"error": "format must be json or markdown"})
    return (f"# Crash Lab run {data['run_id']}\n\n"
            f"Scenario: {data['scenario']} (seed {data['seed']})\n\n"
            f"Service-state verdict: **{data['verdict']}**; bookings: {data['booking_count']}\n\n"
            f"Scope: {data['scope']}\n\n"
            "## Trace\n\n```json\n" + json.dumps(data['events'], indent=2) + "\n```\n")


def register(ctx) -> None:
    tools = (
        ("crash_start", "Create an isolated simulated booking scenario", start, {"scenario": {"type": "string", "enum": sorted(SCENARIOS)}, "seed": {"type": "integer"}}, ["scenario"]),
        ("crash_book", "Attempt a booking in the simulated service", book, {"run_id": {"type": "string"}, "idempotency_key": {"type": "string"}}, ["run_id", "idempotency_key"]),
        ("crash_inspect", "Independently inspect simulated service state and evaluate it", inspect, {"run_id": {"type": "string"}}, ["run_id"]),
        ("crash_report", "Export a JSON or Markdown run report", report, {"run_id": {"type": "string"}, "format": {"type": "string", "enum": ["json", "markdown"]}}, ["run_id"]),
    )
    for name, description, handler, properties, required in tools:
        ctx.register_tool(name=name, toolset="crash_lab", handler=handler, description=description,
                          schema={"name": name, "description": description,
                                  "parameters": {"type": "object", "properties": properties, "required": required}})
