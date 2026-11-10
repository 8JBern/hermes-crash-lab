import json, sys
from audit_lib import *
R = Rec("L1_functional")
L = "L1"
lab = Lab()
# --- normal execution of each scenario (expected from README semantics) ---
for sc in SCEN:
    s = lab.start(sc, 0)
    ok = isinstance(s.get("run_id"), str) and len(s["run_id"]) == 32 and s["scenario"] == sc and s["seed"] == 0
    R.check(f"L1-START-{sc}", L, "normal", f"crash_start {sc} seed 0 returns a run", "run_id (32 hex), scenario and seed echoed", s, ok)
    st = lab.state(s["run_id"])
    R.check(f"L1-STATE0-{sc}", L, "normal", "fresh run persists empty state", "0 bookings, 0 events on disk", {k: st[k] for k in ("bookings", "events", "calls")}, st["bookings"] == [] and st["events"] == [] and st["calls"] == 0)
# --- invalid scenario names ---
bad = ["real_service", "", "TIMEOUT_AFTER_SUCCESS", "timeout_after_success ", " timeout_after_success", None, 0, ["timeout_after_success"], {"a": 1}, "timeout_after_success\n", "../x"]
before = lab.files(); outs = []
for b in bad:
    o = lab.start_raw({"scenario": b}); outs.append((repr(b), o))
ok = all("error" in o and "__exception__" not in o for _, o in outs) and lab.files() == before
R.check("L1-BADSCEN", L, "validation", f"{len(bad)} invalid scenario names rejected without side effects", "structured error for each; no run file created", [t for t in outs if "error" not in t[1] or "__exception__" in t[1]] or "all rejected, no files created", ok, defect="CRASH-AUD-014")
o = lab.start_raw({}); R.check("L1-NOSCEN", L, "validation", "crash_start with no arguments", "structured error", o, "error" in o and "__exception__" not in o)
# --- seeds ---
for seed, accept in [(0, True), (1, True), (2147483647, True), (-1, False), (2147483648, False), (1.0, False), ("1", False), (True, False), (False, False), (None, False), ([1], False), (10**30, False)]:
    o = lab.start_raw({"scenario": "temporary_failure", "seed": seed})
    got = "run_id" in o
    R.check(f"L1-SEED-{seed!r}", L, "boundary", f"seed={seed!r}", "accepted" if accept else "rejected with structured error", o if not got else "accepted", got == accept and "__exception__" not in o)
o = lab.start_raw({"scenario": "temporary_failure"}); R.check("L1-SEED-default", L, "boundary", "seed omitted", "defaults to 0", o.get("seed"), o.get("seed") == 0)
# --- missing / wrong-typed args on book / inspect / report ---
rid = lab.start("timeout_after_success")["run_id"]
cases = {"book-no-args": (lab.book_raw, {}), "book-no-key": (lab.book_raw, {"run_id": rid}), "book-no-run": (lab.book_raw, {"idempotency_key": "k"}),
         "book-key-int": (lab.book_raw, {"run_id": rid, "idempotency_key": 5}), "book-key-none": (lab.book_raw, {"run_id": rid, "idempotency_key": None}),
         "book-key-list": (lab.book_raw, {"run_id": rid, "idempotency_key": ["k"]}), "book-run-int": (lab.book_raw, {"run_id": 5, "idempotency_key": "k"}),
         "book-run-list": (lab.book_raw, {"run_id": [rid], "idempotency_key": "k"}), "book-run-dict": (lab.book_raw, {"run_id": {"a": 1}, "idempotency_key": "k"}),
         "inspect-no-args": (lab.inspect_raw, {}), "inspect-run-none": (lab.inspect_raw, {"run_id": None}), "inspect-run-bytes": (lab.inspect_raw, {"run_id": b"0" * 32}),
         }
for name, (fn, a) in cases.items():
    o = fn(a); R.check(f"L1-ARGS-{name}", L, "validation", name, "structured error, no exception", o, "error" in o and "__exception__" not in o)
st = lab.state(rid); R.check("L1-ARGS-noeffect", L, "validation", "rejected calls leave state untouched", "calls=0, no events", st["calls"], st["calls"] == 0 and not st["events"])
for name, a in {"args-None": None, "args-list": [], "args-str": "x"}.items():
    o = lab.book_raw(a); R.check(f"L1-ARGS-{name}", L, "validation", f"handler called with non-dict args ({name}); not reachable through Hermes, which coerces args to a dict", "structured error, no exception", o, "error" in o and "__exception__" not in o, defect="CRASH-AUD-014")
for fmtname, fmt, want in [("omitted", None, "json"), ("json", "json", "json"), ("markdown", "markdown", "md"), ("MARKDOWN", "MARKDOWN", "err"), ("html", "html", "err"), ("int", 5, "err"), ("list", ["json"], "err"), ("empty", "", "err")]:
    o = lab.report(rid, fmt)
    if isinstance(o, dict): kind = "exc"
    elif o.startswith("# Crash Lab run"): kind = "md"
    else:
        j = json.loads(o); kind = "err" if "error" in j else "json"
    R.check(f"L1-REPORT-fmt-{fmtname}", L, "report", f"crash_report format={fmt!r}", want, kind, kind == want)
o = lab._call(lab.m.report, {"run_id": "0" * 32, "format": "markdown"}); R.check("L1-REPORT-unknown-run", L, "report", "report for unknown run", "structured error", o, isinstance(o, dict) and "error" in o)
o = json.loads(lab._call(lab.m.report, {"run_id": "0" * 32, "format": "bogus"}, raw=True)); R.check("L1-REPORT-err-precedence", L, "report", "unknown run + bad format", "an error", o, "error" in o)
# --- repeated inspection is read-only and stable ---
rid, _ = lab.run("timeout_after_success", 0, ["k1"]); h0 = sha(lab.path(rid)); outs = {json.dumps(lab.inspect(rid), sort_keys=True) for _ in range(50)}
R.check("L1-INSPECT-idempotent", L, "inspect", "50 repeated inspections", "identical output, state file byte-identical", f"{len(outs)} distinct outputs; file unchanged={sha(lab.path(rid)) == h0}", len(outs) == 1 and sha(lab.path(rid)) == h0)
# --- report consistency with service state (independent file read) ---
for sc, seed, keys in [("timeout_after_success", 0, ["a"]), ("timeout_after_success", 0, ["a", "b"]), ("malformed_response", 3, ["a", "a"]), ("temporary_failure", 1, ["a", "a", "a"]), ("temporary_failure", 0, ["a"])]:
    rid, _ = lab.run(sc, seed, keys); st = lab.state(rid); ins = lab.inspect(rid); js = json.loads(lab.report(rid, "json")); md = lab.report(rid, "markdown")
    ok = ins == js and ins["booking_count"] == len(st["bookings"]) and ins["bookings"] == st["bookings"] and ins["events"] == st["events"] and f"bookings: {len(st['bookings'])}" in md and f"**{ins['verdict']}**" in md and rid in md and sc in md
    R.check(f"L1-REPORT-consistency-{sc}-{seed}-{len(keys)}", L, "report", "JSON report == inspect == state file; Markdown carries same verdict and count", "all consistent", f"verdict={ins['verdict']} count={ins['booking_count']} consistent={ok}", ok)
# --- reproducibility across isolated runs ---
def norm(lab, sc, seed, keys):
    rid, resp = lab.run(sc, seed, keys); ins = lab.inspect(rid); ins.pop("run_id"); return json.dumps([resp, ins], sort_keys=True)
ok = True
for sc in SCEN:
    for seed in (0, 1, 7, 2147483647):
        a = norm(Lab(), sc, seed, ["a", "a", "b"]); b = norm(Lab(), sc, seed, ["a", "a", "b"]); ok &= a == b
R.check("L1-REPRO", L, "determinism", "same scenario/seed/call sequence in two isolated stores (12 combinations)", "identical responses and inspect output apart from run_id", ok, ok)
# seed influence (README: seed controls 503 count by parity only)
sig = {}
for sc in SCEN:
    sig[sc] = len({norm(Lab(), sc, seed, ["a", "a", "a", "a"]).replace(f'"seed": {seed}', '"seed": S') for seed in range(0, 40)})
R.check("L1-SEED-effect", L, "determinism", "number of distinct behaviours across seeds 0..39", "README: parity only -> 2 for temporary_failure; other scenarios unspecified", sig, sig["temporary_failure"] == 2)
R.add("L1-SEED-effect-obs", L, "determinism", "seed has any effect on timeout/malformed scenarios", "a 'seed' parameter on a 'deterministic seeded' tool varies behaviour", f"timeout={sig['timeout_after_success']} malformed={sig['malformed_response']} distinct behaviours over 40 seeds", "FAIL" if sig["timeout_after_success"] == 1 else "PASS", defect="CRASH-AUD-012")
# naming: retry_count
rid, _ = lab.run("timeout_after_success", 0, ["a"]); ins = lab.inspect(rid)
R.check("L1-RETRYCOUNT-semantics", L, "report", "one booking call, zero retries", "retry_count == 0 (a retry is a repeat of an earlier attempt)", f"retry_count={ins['retry_count']}; markdown says '{lab.report(rid, 'markdown').split('; ')[2].splitlines()[0]}'", ins["retry_count"] == 0, defect="CRASH-AUD-008")
# excessive budget for temporary_failure seed 0: 1 failure -> 2 calls needed; 3rd call is an unnecessary repeat
rid, _ = lab.run("temporary_failure", 0, ["a", "a", "a"]); ins = lab.inspect(rid)
R.check("L1-BUDGET-503-even", L, "report", "temporary_failure seed 0: success on call 2, then one needless extra call", "excessive_retries == true (one call beyond what the scenario required)", f"retry_count={ins['retry_count']} excessive_retries={ins['excessive_retries']}", ins["excessive_retries"] is True, defect="CRASH-AUD-008")
R.close()
