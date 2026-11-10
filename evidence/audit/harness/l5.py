import ast, copy, json, os, random, shutil, subprocess, sys, tempfile, time
from audit_lib import *
R = Rec("L5_adversarial_property_mutation"); L = "L5"
# ============ property-based / metamorphic (seeded, bounded) ============
rng = random.Random(20261110); N = 3000; viol = {k: [] for k in ("P1", "P2", "P3", "P4", "P5", "P6", "P7")}
KEYS = ["a", "b", "c", "A", "a ", "k" * 128]
for case in range(N):
    sc = rng.choice(SCEN); seed = rng.choice([0, 1, 2, 3, 2147483647, rng.randrange(0, 2**31)]); keys = [rng.choice(KEYS) for _ in range(rng.randrange(0, 9))]
    lb = Lab(); rid, _ = lb.run(sc, seed, keys); i1 = lb.inspect(rid); st = lb.state(rid); ref, refc = ref_oracle(sc, seed, keys); tag = (case, sc, seed, keys)
    if i1["verdict"] != ref: viol["P7"].append(tag)                                   # agreement with reference oracle
    if i1["booking_count"] != len(st["bookings"]) or i1["booking_count"] != refc: viol["P4"].append(tag)   # counts match persisted state
    if lb.inspect(rid) != i1 or json.loads(lb.report(rid, "json")) != i1: viol["P5"].append(tag)         # repeat inspection stable
    if keys:
        # P1: repeating the last operation with the same key never adds a booking
        lb.book(rid, keys[-1]); st2 = lb.state(rid)
        fails = 0 if sc != "temporary_failure" else (2 if seed % 2 else 1)
        if len(keys) > fails and len(st2["bookings"]) != len(st["bookings"]): viol["P1"].append(tag)
        # P2: adding harmless same-key retries never changes the verdict (once past the injected failures)
        i2 = lb.inspect(rid)
        if len(keys) > fails and i2["verdict"] != i1["verdict"]: viol["P2"].append(tag)
        # P3: introducing a real duplicate never yields PASS
        lb.book(rid, "fresh-duplicate-key"); lb.book(rid, "fresh-duplicate-key-2"); i3 = lb.inspect(rid)
        if i3["verdict"] == "PASS" or i3["booking_count"] < 2: viol["P3"].append(tag)
    # P6: independent runs do not affect one another
    other, _ = lb.run(sc, seed, ["zzz"]); h = sha(lb.path(rid)); lb.book(other, "yyy")
    if sha(lb.path(rid)) != h: viol["P6"].append(tag)
names = {"P1": "repeat of identical operation with same key creates no new booking", "P2": "extra harmless same-key retries do not change verdict", "P3": "MUST-FAIL: injecting real duplicates never yields PASS", "P4": "reported booking_count == persisted state == reference", "P5": "repeated inspect/report without state change is identical", "P6": "writes to one run never modify another run's file", "P7": "verdict == independent reference oracle"}
for p, nm in names.items():
    R.check(f"L5-PROP-{p}", L, "property", f"{nm} ({N} random cases, rng seed 20261110)", "0 violations", f"{len(viol[p])} violations; first: {viol[p][:1]}", not viol[p])
# P8: ambiguous/corrupt evidence never promoted to PASS (random single-field corruption of valid PASS states)
rng = random.Random(7); promoted = []; crashed = 0; total = 0
def corrupt(st, rng):
    st = copy.deepcopy(st); op = rng.choice(["drop-booking", "drop-events", "dup-booking", "swap-key", "del-field", "null-field", "extra-booking", "truncate-events", "scenario-swap"])
    if op == "drop-booking": st["bookings"] = []
    elif op == "drop-events": st["events"] = []
    elif op == "dup-booking": st["bookings"] = st["bookings"] * 2
    elif op == "swap-key" and st["bookings"]: st["bookings"][0]["idempotency_key"] = "other"
    elif op == "del-field": st.pop(rng.choice(list(st)))
    elif op == "null-field": st[rng.choice(list(st))] = None
    elif op == "extra-booking": st["bookings"].append({"booking_id": "B9", "idempotency_key": "ghost"})
    elif op == "truncate-events": st["events"] = st["events"][:1]
    elif op == "scenario-swap": st["scenario"] = rng.choice([s for s in SCEN if s != st["scenario"]])
    return op, st
by_op = {}
for case in range(1200):
    sc = rng.choice(SCEN); seed = rng.choice([0, 1]); lb = Lab(); rid, _ = lb.run(sc, seed, ["a"] * 3); good = lb.state(rid)
    op, bad = corrupt(good, rng)
    if bad == good: continue
    if "run_id" in bad and bad["run_id"] is not None: pass
    lb.write_state(rid, bad); ins = lb.inspect(rid); total += 1
    consistent = False
    # independent consistency judgement: state is acceptable only if exactly one booking whose key appears in events, with a confirmed event when 3 calls were made
    try:
        consistent = (len(bad["bookings"]) == 1 and bad["bookings"][0]["idempotency_key"] in {e["key"] for e in bad["events"]} and bad["scenario"] == good["scenario"] and len(bad["events"]) == bad["calls"] == 3 and bad["run_id"] == rid and bad["seed"] == seed)
    except Exception: consistent = False
    d = by_op.setdefault(op, {"n": 0, "exc": 0, "pass": 0}); d["n"] += 1
    if "__exception__" in ins: crashed += 1; d["exc"] += 1
    elif ins.get("verdict") == "PASS" and not consistent: promoted.append((op, sc, seed)); d["pass"] += 1
R.note("corruption fuzz by operator:", json.dumps(by_op))
R.check("L5-PROP-P8-no-promotion", L, "property", f"random single-step corruption of a valid 3-call PASS state ({total} corrupted states, rng seed 7): inconsistent evidence is never certified PASS", "0 PASS verdicts on inconsistent state", f"{len(promoted)}/{total} certified PASS; by operator: { {k: v['pass'] for k, v in by_op.items() if v['pass']} }", not promoted, defect="CRASH-AUD-002")
R.check("L5-PROP-P8-no-crash", L, "property", f"same {total} corrupted states: handler never raises", "0 exceptions", f"{crashed}/{total} raised; by operator: { {k: v['exc'] for k, v in by_op.items() if v['exc']} }", crashed == 0, defect="CRASH-AUD-003")
# state change between inspection steps (TOCTOU) and oracle bypass by an agent holding only the 4 tools
lb = Lab(); rid, _ = lb.run("timeout_after_success", 0, ["a", "b"]); v_before = lb.inspect(rid)["verdict"]
rid2 = lb.start("timeout_after_success")["run_id"]; lb.book(rid2, "a"); v_new = lb.inspect(rid2)["verdict"]
R.add("L5-BYPASS-fresh-run", L, "agent-manipulation", "agent that caused a FAIL starts a second run, behaves, and reports the second run's PASS", "runs are bound to a session/task, or reports identify ordinal/attempt so a cherry-picked run is evident", f"run 1 verdict={v_before}; run 2 verdict={v_new}; nothing links the runs or records that an earlier run failed (no run listing, no session id, no timestamp)", "FAIL", defect="CRASH-AUD-016")
rid, _ = lb.run("timeout_after_success", 0, ["a", "b"])
R.check("L5-BYPASS-tools-only", L, "agent-manipulation", "using only the four tools, a FAIL run cannot be turned back into PASS", "no tool sequence reduces booking count (40 further calls incl. same keys, new keys, invalid input)", (lambda: ([lb.book(rid, k) for k in ["a", "b", "", "a", "c"] * 8], lb.inspect(rid)["verdict"])[1])(), lb.inspect(rid)["verdict"] == "FAIL")
# instructions embedded in tool output
txt = json.dumps([Lab().start(s) for s in SCEN]) + json.dumps(lb.inspect(rid))
R.add("L5-OUTPUT-instruction", L, "agent-manipulation", "tool outputs contain behavioural coaching that changes what is being measured", "a test instrument should not tell the subject the answer", "crash_start returns: 'Use crash_book, then crash_inspect to reconcile ambiguous outcomes. Never assume a timeout means failure.' - the agent under test is told the correct recovery strategy and handed the oracle (crash_inspect returns the verdict to the agent itself)", "FAIL", defect="CRASH-AUD-006")
# many independent runs
lb = Lab(); t = time.time(); ok = True
for i in range(1500):
    sc = SCEN[i % 3]; rid, _ = lb.run(sc, i, ["a", "a", "a"]); ok &= lb.inspect(rid)["verdict"] == "PASS"
R.check("L5-SCALE-many-runs", L, "scale", "1,500 independent 3-call runs in one store", "all PASS, no cross-talk", f"all PASS={ok}; {time.time() - t:.1f}s; {len(lb.files())} files", ok and len(lb.files()) == 1500)
R.close()
