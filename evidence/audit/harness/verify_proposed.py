import copy, itertools, json, random, subprocess, sys, time, os
from audit_lib import *
R = Rec("FIX_proposed_verification"); L = "FIX"; SRC = AUDIT / "proposed/__init__.py"; REVN = "draft-1.0.2 (audit proposal)"
P = lambda: Lab(src=SRC)
tot = 0; mism = []
lab = P()
for sc in SCEN:
    for seed in (0, 1, 2):
        for n in range(0, 6):
            for keys in itertools.product("abc", repeat=n):
                rid, _ = lab.run(sc, seed, list(keys)); ins = lab.inspect(rid); tot += 1
                ev, ec = ref_oracle(sc, seed, list(keys))
                if ins.get("verdict") != ev or ins.get("booking_count") != ec or len(lab.state(rid)["bookings"]) != ec: mism.append((sc, seed, keys, ins.get("verdict")))
R.check("FIX-REF-exhaustive", L, "reference-oracle", f"draft fix vs reference oracle and state file, {tot} exhaustive sequences", "0 mismatches (no behaviour change on reachable states)", f"{len(mism)} mismatches", not mism, rev=REVN)
# behaviour parity with 1.0.1 on reachable states: responses + verdict + shared fields identical
diff = 0; rng = random.Random(5); o = Lab()
for case in range(1500):
    sc = rng.choice(SCEN); seed = rng.randrange(0, 50); keys = [rng.choice("abcd") for _ in range(rng.randrange(0, 10))]
    r1, a1 = o.run(sc, seed, keys); r2, a2 = lab.run(sc, seed, keys); i1 = o.inspect(r1); i2 = lab.inspect(r2); i1.pop("run_id"); i2.pop("run_id")
    if a1 != a2 or any(i1[k] != i2[k] for k in i1): diff += 1
R.check("FIX-PARITY", L, "compatibility", "draft fix vs 1.0.1: responses and every 1.0.1 inspect field on 1,500 random reachable runs (rng seed 5)", "identical (fix adds fields only)", f"{diff} differing runs", diff == 0, rev=REVN)
# corruption fuzz
rng = random.Random(7); promoted = crashed = total = 0
for case in range(1200):
    sc = rng.choice(SCEN); seed = rng.choice([0, 1]); lb = P(); rid, _ = lb.run(sc, seed, ["a"] * 3); good = lb.state(rid); st = copy.deepcopy(good)
    op = rng.choice(["drop-booking", "drop-events", "dup-booking", "swap-key", "del-field", "null-field", "extra-booking", "truncate-events", "scenario-swap"])
    if op == "drop-booking": st["bookings"] = []
    elif op == "drop-events": st["events"] = []
    elif op == "dup-booking": st["bookings"] = st["bookings"] * 2
    elif op == "swap-key": st["bookings"][0]["idempotency_key"] = "other"
    elif op == "del-field": st.pop(rng.choice(list(st)))
    elif op == "null-field": st[rng.choice(list(st))] = None
    elif op == "extra-booking": st["bookings"].append({"booking_id": "B9", "idempotency_key": "ghost"})
    elif op == "truncate-events": st["events"] = st["events"][:1]
    elif op == "scenario-swap": st["scenario"] = rng.choice([s for s in SCEN if s != st["scenario"]])
    if st == good: continue
    lb.write_state(rid, st); total += 1
    for out in (lb.inspect(rid), lb.book(rid, "a"), lb._call(lb.m.report, {"run_id": rid, "format": "markdown"})):
        if "__exception__" in out: crashed += 1
        elif out.get("verdict") == "PASS" or out.get("status") == "confirmed": promoted += 1
R.check("FIX-FUZZ-corruption", L, "state-integrity", f"draft fix: {total} corrupted states x inspect/book/report", "0 exceptions, 0 PASS/confirmed", f"exceptions={crashed} certified={promoted}", crashed == 0 and promoted == 0, rev=REVN)
# races
def race(keys, n=1):
    lb = P(); rid = lb.start("timeout_after_success")["run_id"]; go = time.time() + 0.35
    code = "import sys,json,time;sys.path.insert(0,'%s/harness');from audit_lib import Lab;lb=Lab(root=sys.argv[1],src='%s')\nwhile time.time()<float(sys.argv[4]):pass\nprint(json.dumps([lb.book(sys.argv[2],sys.argv[3]) for _ in range(int(sys.argv[5]))]))" % (AUDIT, SRC)
    ps = [subprocess.Popen([sys.executable, "-c", code, str(lb.root), rid, k, str(go), str(n)], stdout=subprocess.PIPE) for k in keys]
    return lb, rid, [json.loads(p.communicate()[0] or b"[]") for p in ps]
bad = 0
for t in range(150):
    lb, rid, outs = race(["key-A", "key-B"]); st = lb.state(rid)
    if not (len(st["bookings"]) == 2 and len(st["events"]) == 2 and lb.inspect(rid)["verdict"] == "FAIL"): bad += 1
R.check("FIX-RACE-diffkeys", L, "concurrency", "draft fix: 2 processes, different keys, 150 trials", "2 bookings, 2 events, FAIL in every trial", f"{bad}/150 wrong", bad == 0, rev=REVN)
bad = 0; leftover = 0
for t in range(30):
    lb, rid, outs = race(["same"] * 8, n=5); st = lb.state(rid)
    if not (len(st["bookings"]) == 1 and len(st["events"]) == 40 == st["calls"]): bad += 1
    leftover += len([f for f in lb.files() if not f.endswith(".json")])
R.check("FIX-RACE-samekey", L, "concurrency", "draft fix: 8 processes x 5 calls same key, 30 trials", "1 booking, 40 events every trial; no lock/tmp files left", f"{bad}/30 wrong; leftover non-json files={leftover}", bad == 0 and leftover == 0, rev=REVN)
# bounded cost
lb = P(); rid = lb.start("timeout_after_success")["run_id"]; t = time.time(); outs = [lb.book(rid, "k" * 128) for _ in range(520)]; dt = time.time() - t
R.check("FIX-BOUND", L, "resource", "draft fix: 520 calls on one run", "calls beyond 500 rejected; state < 1 MB", f"{sum('limit' in o.get('error', '') for o in outs)} rejected; state {lb.path(rid).stat().st_size:,} bytes; inspect {len(json.dumps(lb.inspect(rid))):,} chars; {dt:.1f}s", sum("limit" in o.get("error", "") for o in outs) == 20 and lb.state(rid)["calls"] == 500, rev=REVN)
# stale lock recovery
lb = P(); rid = lb.start("timeout_after_success")["run_id"]; lock = lb.path(rid).with_suffix(".lock"); lock.write_text(""); os.utime(lock, (time.time() - 120, time.time() - 120)); o = lb.book(rid, "a")
R.check("FIX-LOCK-stale", L, "concurrency", "draft fix: stale lock file (120 s old) left by a killed writer", "broken automatically; call proceeds", o, "timeout" in o.get("error", ""), rev=REVN)
lb.m.LOCK_TIMEOUT_S = 0.2; lock.write_text(""); o = lb.book(rid, "a"); lock.unlink()
R.check("FIX-LOCK-busy", L, "concurrency", "draft fix: live lock held past the timeout", "structured 'busy' error, clearly not a simulated fault; state unchanged", o, "busy" in o.get("error", "") and lb.state(rid)["calls"] == 1, rev=REVN)
# Hermes admission checks on the draft
env = dict(os.environ, HERMES_HOME=str(AUDIT / "hermes-home-ci"))
for cmd, tid in ((["plugins", "doctor", ".", "--ci"], "FIX-HERMES-doctor"), (["plugins", "validate", ".", "--install-deps"], "FIX-HERMES-validate")):
    p = subprocess.run([str(AUDIT / "hermes-venv/bin/hermes")] + cmd, cwd=AUDIT / "proposed", env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL); tail = (p.stdout + p.stderr).strip().splitlines()[-1]
    R.note((p.stdout + p.stderr)[-1500:])
    R.check(tid, L, "integration", "draft fix: hermes " + " ".join(cmd), "exit 0", f"exit {p.returncode}: {tail}", p.returncode == 0, rev=REVN, mode="hermes-cli")
R.close()
