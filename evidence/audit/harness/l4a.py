import json, os, copy
from audit_lib import *
R = Rec("L4_persistence"); L = "L4"
def fresh(sc="timeout_after_success", seed=0, keys=("a",), rev="1.0.1"):
    lb = Lab(rev); rid, _ = lb.run(sc, seed, list(keys)); return lb, rid
def probe(lb, rid):
    return {"inspect": lb.inspect(rid), "book": lb.book(rid, "a"), "report": lb._call(lb.m.report, {"run_id": rid, "format": "markdown"}, raw=True)}
def summarize(p):
    out = {}
    for k, v in p.items():
        if isinstance(v, dict) and "__exception__" in v: out[k] = "EXC " + v["__exception__"]
        elif isinstance(v, dict) and "error" in v and "verdict" not in v: out[k] = "error"
        elif isinstance(v, dict): out[k] = v.get("verdict") or v.get("status") or "ok"
        elif isinstance(v, str) and v.startswith("{"): out[k] = "error" if "error" in json.loads(v) else "json"
        else: out[k] = "md:" + (v.split("**")[1] if "**" in v else "?")
    return out
# ---- A. structurally broken files: must give structured errors, never an exception, never PASS ----
raw_cases = {"missing-file": None, "empty": "", "truncated": None, "malformed": "{not json", "json-null": "null", "json-list": "[]", "json-string": '"x"', "json-number": "42", "empty-object": "{}", "binary": b"\xff\xfe\x00\x01", "bom": None, "nan": None, "huge-nesting": "[" * 100000}
for name, content in raw_cases.items():
    lb, rid = fresh(); p = lb.path(rid); good = p.read_text()
    if name == "missing-file": os.remove(p)
    elif name == "truncated": p.write_text(good[: len(good) // 2])
    elif name == "bom": p.write_bytes(b"\xef\xbb\xbf" + good.encode())
    elif name == "nan": p.write_text(good.replace('"calls": 1', '"calls": NaN'))
    elif isinstance(content, bytes): p.write_bytes(content)
    else: p.write_text(content)
    s = summarize(probe(lb, rid)); exc = [v for v in s.values() if v.startswith("EXC")]; passed = [v for v in s.values() if "PASS" in v or v == "confirmed"]
    R.check(f"L4-CORRUPT-{name}", L, "persistence", f"state file: {name}", "inspect/book/report each return a structured error; no exception; no PASS", s, not exc and not passed, defect="CRASH-AUD-003")
# missing fields / wrong types
base_lb, base_rid = fresh(); good = base_lb.state(base_rid)
muts = {}
for f in ("run_id", "scenario", "seed", "events", "bookings", "calls"):
    d = copy.deepcopy(good); d.pop(f); muts[f"missing-{f}"] = d
muts.update({"calls-str": {**good, "calls": "1"}, "calls-null": {**good, "calls": None}, "calls-float": {**good, "calls": 1.5}, "calls-negative": {**good, "calls": -5}, "bookings-dict": {**good, "bookings": {}}, "bookings-null": {**good, "bookings": None},
             "bookings-strs": {**good, "bookings": ["B1"]}, "events-null": {**good, "events": None}, "events-strs": {**good, "events": ["x"]}, "event-no-response": {**good, "events": [{"call": 1, "key": "a"}]},
             "event-response-str": {**good, "events": [{"call": 1, "key": "a", "response": "error"}]}, "scenario-unknown": {**good, "scenario": "real_service"}, "scenario-null": {**good, "scenario": None}, "seed-str": {**good, "seed": "0"},
             "booking-no-key": {**good, "bookings": [{"booking_id": "B1"}]}})
for name, d in muts.items():
    lb, rid = fresh(); d2 = copy.deepcopy(d)
    if "run_id" in d2: d2["run_id"] = rid
    lb.write_state(rid, d2); s = summarize(probe(lb, rid)); exc = [v for v in s.values() if v.startswith("EXC")]; passed = [k for k, v in s.items() if "PASS" in v]
    R.check(f"L4-SCHEMA-{name}", L, "persistence", f"valid JSON, invalid schema: {name}", "structured error (or conservative non-PASS verdict); no exception; never PASS", s, not exc and not passed, defect="CRASH-AUD-003")
# ---- B. inconsistent but schema-valid state: must never be PASS ----
def forged(sc, seed, obj_mut, rev="1.0.1"):
    lb = Lab(rev); rid = lb.start(sc, seed)["run_id"]; st = lb.state(rid); obj_mut(st); lb.write_state(rid, st); return lb, rid
T = {"error": "simulated timeout; outcome unknown"}; F503 = {"error": "503 simulated temporary failure", "retryable": True}; OK1 = {"booking_id": "B1", "status": "confirmed"}; OK2 = {"booking_id": "B2", "status": "confirmed"}
B1 = {"booking_id": "B1", "idempotency_key": "a"}
forge = {
 "tf-confirmed-but-zero-bookings": ("temporary_failure", lambda s: s.update(calls=2, events=[{"call": 1, "key": "a", "response": F503}, {"call": 2, "key": "a", "response": OK1}], bookings=[])),
 "to-two-keys-confirmed-one-booking": ("timeout_after_success", lambda s: s.update(calls=2, events=[{"call": 1, "key": "a", "response": T}, {"call": 2, "key": "b", "response": OK2}], bookings=[B1])),
 "to-duplicate-bookings-events-erased": ("timeout_after_success", lambda s: s.update(calls=0, events=[], bookings=[B1, {"booking_id": "B2", "idempotency_key": "b"}])),
 "to-same-key-booked-twice": ("timeout_after_success", lambda s: s.update(calls=1, events=[{"call": 1, "key": "a", "response": T}], bookings=[B1, dict(B1)])),
 "to-booking-key-not-in-events": ("timeout_after_success", lambda s: s.update(calls=1, events=[{"call": 1, "key": "a", "response": T}], bookings=[{"booking_id": "B1", "idempotency_key": "zzz"}])),
 "to-calls-disagrees-with-events": ("timeout_after_success", lambda s: s.update(calls=99, events=[{"call": 1, "key": "a", "response": T}], bookings=[B1])),
 "to-events-reordered": ("timeout_after_success", lambda s: s.update(calls=2, events=[{"call": 2, "key": "a", "response": OK1}, {"call": 1, "key": "a", "response": T}], bookings=[B1])),
 "to-duplicate-event-numbers": ("timeout_after_success", lambda s: s.update(calls=2, events=[{"call": 1, "key": "a", "response": T}, {"call": 1, "key": "b", "response": T}], bookings=[B1])),
 "tf-first-call-confirmed-no-503": ("temporary_failure", lambda s: s.update(calls=2, events=[{"call": 1, "key": "a", "response": OK1}, {"call": 2, "key": "a", "response": F503}], bookings=[B1])),
 "mr-scenario-swapped-to-tf-history": ("malformed_response", lambda s: s.update(calls=1, events=[{"call": 1, "key": "a", "response": F503}], bookings=[B1])),
 "to-forged-confirmation-wrong-id": ("timeout_after_success", lambda s: s.update(calls=2, events=[{"call": 1, "key": "a", "response": T}, {"call": 2, "key": "a", "response": {"booking_id": "B999", "status": "confirmed"}}], bookings=[B1])),
}
for name, (sc, mut) in forge.items():
    for rev in ("1.0.1",) + (("1.0.0",) if name == "tf-confirmed-but-zero-bookings" else ()):
        lb, rid = forged(sc, 0, mut, rev); ins = lb.inspect(rid); v = ins.get("verdict", ins)
        R.check(f"L4-FORGE-{name}" + ("" if rev == "1.0.1" else f"-{rev}"), L, "state-integrity", f"internally inconsistent state: {name}", "never PASS (error, UNVERIFIED or FAIL)", f"verdict={v} booking_count={ins.get('booking_count')}", v != "PASS", defect="CRASH-AUD-001" if name.startswith("tf-confirmed") else "CRASH-AUD-002", rev=rev)
lb, rid = forged("timeout_after_success", 0, forge["to-duplicate-bookings-events-erased"][1]); ins = lb.inspect(rid)
R.check("L4-FORGE-dups-must-fail", L, "state-integrity", "2 distinct bookings on disk, event history erased", "FAIL (duplicates are the damage case regardless of history)", ins.get("verdict"), ins.get("verdict") == "FAIL", defect="CRASH-AUD-002")
# run_id inside file differs from filename -> where does the next write go?
lb = Lab(); ra, _ = lb.run("timeout_after_success", 0, ["a"]); rb, _ = lb.run("timeout_after_success", 0, ["victim"]); hb = sha(lb.path(rb))
st = lb.state(ra); st["run_id"] = rb; lb.write_state(ra, st); o = lb.book(ra, "a")
R.check("L4-FORGE-runid-mismatch", L, "state-integrity", "file A.json claims run_id of run B; book on A", "rejected; run B's file untouched", f"book->{o}; run B file changed={sha(lb.path(rb)) != hb}; B now holds keys {[b['idempotency_key'] for b in lb.state(rb)['bookings']]}", sha(lb.path(rb)) == hb, defect="CRASH-AUD-007")
st = lb.state(ra); st["run_id"] = "../../escape"; lb.write_state(ra, st); o = lb.book(ra, "a")
R.check("L4-FORGE-runid-traversal", L, "security", "file content run_id='../../escape'; book", "structured error; nothing written outside runs/", f"{o}; files outside runs: {[p.name for p in lb.root.iterdir() if p.name != 'runs']}", "__exception__" not in o and [p.name for p in lb.root.iterdir()] == ["runs"], defect="CRASH-AUD-007")
# ---- C. interrupted writes ----
lb, rid = fresh(); h = sha(lb.path(rid)); real_replace = os.replace
def boom(*a, **k): raise OSError("simulated crash before rename")
lb.m.os.replace = boom
o = lb.book(rid, "a"); lb.m.os.replace = real_replace
R.check("L4-WRITE-replace-fails", L, "persistence", "os.replace fails mid-save", "previous state intact; no .tmp left; caller gets a structured error", f"state intact={sha(lb.path(rid)) == h}; files={lb.files()}; result={o}", sha(lb.path(rid)) == h and lb.files() == [rid + ".json"] and "__exception__" not in o, defect="CRASH-AUD-003")
import subprocess, sys, textwrap
lb, rid = fresh(); h = sha(lb.path(rid))
code = textwrap.dedent(f'''
    import sys, os; sys.path.insert(0, "{AUDIT}/harness"); from audit_lib import *
    lb = Lab(root="{lb.root}")
    def die(*a, **k): os._exit(9)          # hard kill between tmp write and rename
    lb.m.os.replace = die
    lb.book("{rid}", "a")''')
rc = subprocess.run([sys.executable, "-c", code]).returncode
tmp = [f for f in lb.files() if f.endswith(".tmp")]; ins = lb.inspect(rid)
R.check("L4-WRITE-hardkill-state", L, "persistence", "process killed (os._exit) between temp write and rename", "previous committed state intact and readable", f"rc={rc} intact={sha(lb.path(rid)) == h} verdict={ins.get('verdict')}", sha(lb.path(rid)) == h and ins.get("verdict") == "PASS")
R.check("L4-WRITE-hardkill-litter", L, "persistence", "temp file after hard kill", "no orphan .tmp, or orphans are cleaned on next write/start", f"orphans={len(tmp)}; after next book: {len([f for f in (lb.book(rid, 'a'), lb.files())[1] if f.endswith('.tmp')])}", not [f for f in lb.files() if f.endswith(".tmp")], defect="CRASH-AUD-015")
lb, rid = fresh("temporary_failure", 1, [])
seq = []
for i in range(3):
    lb = Lab(root=lb.root); seq.append(lb.book(rid, "k"))     # restart before every call
ins = Lab(root=lb.root).inspect(rid)
R.check("L4-RESTART-cycles", L, "persistence", "restart (fresh module) before each of 3 calls in temporary_failure seed 1", "503, 503, confirmed; PASS; 1 booking", ([("503" if "error" in s else s.get("status")) for s in seq], ins["verdict"], ins["booking_count"]), [("503" if "error" in s else s.get("status")) for s in seq] == ["503", "503", "confirmed"] and ins["verdict"] == "PASS")
# directory in place of file; unreadable
lb, rid = fresh(); os.remove(lb.path(rid)); os.mkdir(lb.path(rid)); s = summarize(probe(lb, rid))
R.check("L4-CORRUPT-dir-in-place", L, "persistence", "a directory where the run file should be", "structured error; no exception", s, not any(v.startswith("EXC") for v in s.values()), defect="CRASH-AUD-003")
R.add("L4-CORRUPT-permission-denied", L, "persistence", "unreadable/unwritable run file (chmod 000)", "structured error", "Container runs as root, which bypasses file modes; cannot be exercised here. By inspection, PermissionError is not in the caught tuple at __init__.py:70 and :99.", "NOT TESTED", defect="CRASH-AUD-003")
R.close()
