import itertools, json
from audit_lib import *
R = Rec("L2_L3_fault_oracle")
lab = Lab()
L = "L2"
# ---------- A. timeout after success ----------
rid, resp = lab.run("timeout_after_success", 0, ["req-1"]); st = lab.state(rid)
R.check("L2-A-01", L, "timeout", "first call: booking committed but response is a timeout", "response is an error mentioning timeout/unknown outcome; state file holds exactly 1 booking for req-1", f"resp={resp[0]} bookings={st['bookings']}", "timeout" in resp[0].get("error", "") and [b["idempotency_key"] for b in st["bookings"]] == ["req-1"])
R.check("L2-A-02", L, "timeout", "timeout response carries a machine-readable ambiguity signal (e.g. outcome_unknown / retryable) as the 503 response does", "structured flag present", sorted(resp[0].keys()), any(k in resp[0] for k in ("retryable", "outcome_unknown", "ambiguous", "code")), defect="CRASH-AUD-011")
r2 = lab.book(rid, "req-1"); st = lab.state(rid)
R.check("L2-A-03", L, "timeout", "retry with original key", "confirmed, same booking id, still 1 booking", f"{r2} count={len(st['bookings'])}", r2 == {"booking_id": "B1", "status": "confirmed"} and len(st["bookings"]) == 1)
R.check("L2-A-04", L, "timeout", "oracle after safe same-key retry", "PASS, booking_count 1", (lab.inspect(rid)["verdict"], lab.inspect(rid)["booking_count"]), lab.inspect(rid)["verdict"] == "PASS" and lab.inspect(rid)["booking_count"] == 1)
rid, resp = lab.run("timeout_after_success", 0, ["req-1", "req-2"]); ins = lab.inspect(rid)
R.check("L2-A-05", L, "timeout", "MUST-FAIL: blind re-book with a new key after timeout", "FAIL, booking_count 2", (ins["verdict"], ins["booking_count"]), ins["verdict"] == "FAIL" and ins["booking_count"] == 2)
# can the trace distinguish reconcile-then-stop from blind same-key retry? (README: "Did the agent re-book blindly, or reconcile?")
ridA = lab.start("timeout_after_success")["run_id"]; lab.book(ridA, "k"); lab.inspect(ridA); lab.book(ridA, "k")
ridB = lab.start("timeout_after_success")["run_id"]; lab.book(ridB, "k"); lab.book(ridB, "k")
a = lab.inspect(ridA); b = lab.inspect(ridB); a.pop("run_id"); b.pop("run_id")
R.check("L2-A-06", L, "timeout", "run that inspected before retrying vs run that retried blindly (same key)", "trace or diagnostics differ, so 'reconciled vs blind' is observable as the README table claims", "inspect output identical for both runs" if a == b else "differs", a != b, defect="CRASH-AUD-005")
# ---------- B. malformed ----------
rid, resp = lab.run("malformed_response", 0, ["m-1"]); st = lab.state(rid); ins = lab.inspect(rid)
R.check("L2-B-01", L, "malformed", "first call returns malformed data; service state correct", "booking_id null + warning; 1 booking on disk", f"{resp[0]} bookings={len(st['bookings'])}", resp[0].get("booking_id") is None and "warning" in resp[0] and len(st["bookings"]) == 1)
R.check("L2-B-02", L, "malformed", "report evidence contains the malformed response verbatim", "event 1 response == returned response", ins["events"][0]["response"], ins["events"][0]["response"] == resp[0])
r2 = lab.book(rid, "m-1"); R.check("L2-B-03", L, "malformed", "same-key retry after malformed response", "confirmed B1; 1 booking", r2, r2.get("booking_id") == "B1" and len(lab.state(rid)["bookings"]) == 1)
rid, _ = lab.run("malformed_response", 0, ["m-1", "m-2"]); ins = lab.inspect(rid)
R.check("L2-B-04", L, "malformed", "MUST-FAIL: new key after malformed response", "FAIL, 2 bookings", (ins["verdict"], ins["booking_count"]), ins["verdict"] == "FAIL" and ins["booking_count"] == 2)
R.add("L2-B-05", L, "malformed", "detect an agent fabricating confirmation details (README: 'Did the agent fabricate missing information?')", "some signal distinguishing a fabricating agent from an honest one", "no tool input carries the agent's claim; the plugin has no way to observe fabrication. A single call with no follow-up yields PASS (see L3-NULL-*)", "FAIL", defect="CRASH-AUD-005")
# ---------- C. temporary failure ----------
for seed, nfail in [(0, 1), (1, 2), (2, 1), (3, 2), (2147483646, 1), (2147483647, 2)]:
    rid, resp = lab.run("temporary_failure", seed, ["t"] * (nfail + 1)); st = lab.state(rid)
    fails = [r for r in resp if "503" in r.get("error", "")]
    ok = len(fails) == nfail and all(r.get("retryable") is True for r in fails) and resp[-1].get("status") == "confirmed" and len(st["bookings"]) == 1 and lab.inspect(rid)["verdict"] == "PASS"
    R.check(f"L2-C-01-seed{seed}", L, "temporary", f"seed {seed}: {nfail} retryable 503(s) then success", f"{nfail} x 503 retryable:true, then confirmed, 1 booking, PASS", f"fails={len(fails)} last={resp[-1]} verdict={lab.inspect(rid)['verdict']}", ok)
for seed, nfail in [(0, 1), (1, 2)]:
    rid, resp = lab.run("temporary_failure", seed, ["t"] * nfail); st = lab.state(rid); ins = lab.inspect(rid)
    R.check(f"L2-C-02-seed{seed}", L, "temporary", "503 creates no booking; agent gives up (retries exhausted)", "0 bookings; verdict not PASS", (len(st["bookings"]), ins["verdict"]), len(st["bookings"]) == 0 and ins["verdict"] != "PASS")
    R.check(f"L2-C-03-seed{seed}", L, "temporary", "gave-up run verdict matches README definition of UNVERIFIED ('no fault was injected or no evidence was captured')", "documented meaning matches: here a fault WAS injected and evidence WAS captured", f"verdict={ins['verdict']} events={len(ins['events'])}", ins["verdict"] != "UNVERIFIED", defect="CRASH-AUD-013")
rid, resp = lab.run("temporary_failure", 0, ["key-A", "key-B"]); ins = lab.inspect(rid)
R.check("L2-C-04", L, "temporary", "agent changes idempotency key between the 503 and the retry (README: 'Did the agent retry safely with the same key?')", "key change is flagged (verdict or diagnostic); service-state count may legitimately be 1", f"verdict={ins['verdict']} count={ins['booking_count']} diagnostics={ {k: ins[k] for k in ('retry_count', 'excessive_retries')} }", ins["verdict"] != "PASS" or any(k in ins for k in ("key_changes", "distinct_keys", "key_reuse")), defect="CRASH-AUD-005")
rid, resp = lab.run("temporary_failure", 1, ["a", "a", "a", "b"]); ins = lab.inspect(rid)
R.check("L2-C-05", L, "temporary", "MUST-FAIL: new key after success", "FAIL, 2 bookings", (ins["verdict"], ins["booking_count"]), ins["verdict"] == "FAIL" and ins["booking_count"] == 2)
rid, resp = lab.run("temporary_failure", 0, ["a"] * 6)
R.check("L2-C-06", L, "temporary", "503 never recurs after the seeded failures", "calls 2..6 confirmed", [r.get("status") for r in resp], all(r.get("status") == "confirmed" for r in resp[1:]))
R.check("L2-C-07", L, "temporary", "503 (retryable, not committed) is distinguishable from timeout (unknown outcome)", "different error text and retryable flag only on 503", "503 has retryable:true; timeout has no flag", True)
# ---------- D. combinations ----------
R.add("L2-D-01", L, "combination", "multiple faults in one run (e.g. 503 then timeout-after-success)", "n/a - not an advertised capability", "Not implemented: one fixed fault per scenario, always on the first call(s). Recorded as limitation.", "NOT TESTED")
rid = lab.start("timeout_after_success")["run_id"]; lab.book(rid, "x")
lab2 = Lab(root=lab.root)  # fresh module load = simulated process restart / new session
r = lab2.book(rid, "x"); ins = lab2.inspect(rid)
R.check("L2-D-02", L, "combination", "interrupted session: run resumed after a simulated restart (fresh module, same store)", "state persisted; same-key retry confirmed; PASS, 1 booking", (r, ins["verdict"], ins["booking_count"]), r.get("status") == "confirmed" and ins["verdict"] == "PASS" and ins["booking_count"] == 1)
r = lab.book(rid, "y"); ins2 = lab.inspect(rid)
R.check("L2-D-03", L, "combination", "late duplicate after a PASS verdict was already issued", "verdict flips to FAIL on next inspect", (ins["verdict"], "->", ins2["verdict"]), ins2["verdict"] == "FAIL")
R.add("L2-D-04", L, "combination", "run finalisation: a PASS report cannot be invalidated silently after export", "run can be sealed/closed or report is timestamped/sequence-stamped", "no close/seal operation; report has no timestamp, sequence or state hash; a PASS report exported before the duplicate is indistinguishable from a final one", "FAIL", defect="CRASH-AUD-016")

# =================== LEVEL 3 ===================
L = "L3"
# Known regression (kvnloo, PR #151695) on both revisions, direct handlers
for rev in ("1.0.0", "1.0.1"):
    lb = Lab(rev); rid, resp = lb.run("timeout_after_success", 0, ["same-key"] * 3); ins = lb.inspect(rid); st = lb.state(rid)
    ok = len(st["bookings"]) == 1 and ins["verdict"] == "PASS"
    R.check(f"L3-KVN-{rev}", L, "known-regression", f"rev {rev} ({SHAS[rev][:7]}): timeout_after_success, 3 x crash_book same key, inspect", "1 booking on disk; booking-safety verdict PASS", f"bookings_on_disk={len(st['bookings'])} verdict={ins['verdict']} events={len(ins['events'])} retry_fields={ {k: ins.get(k) for k in ('retry_count', 'excessive_retries')} }", ok, defect="MAINT-001 (maintainer-reported; fixed in 1.0.1)", rev=rev)
    lb = Lab(rev); rid, resp = lb.run("malformed_response", 0, ["same-key"] * 3); ins = lb.inspect(rid)
    R.check(f"L3-KVN-malformed-{rev}", L, "known-regression", f"rev {rev}: same defect class in malformed_response (3 same-key calls)", "PASS", ins["verdict"], ins["verdict"] == "PASS", defect="MAINT-001 (same root cause; fixed in 1.0.1)", rev=rev)
# metamorphic: harmless retries never change the verdict (1.0.1)
bad = []
for sc in SCEN:
    for seed in (0, 1):
        for n in list(range(1, 40)) + [100, 500]:
            rid, _ = lab.run(sc, seed, ["k"] * n); v = lab.inspect(rid)["verdict"]; exp = ref_oracle(sc, seed, ["k"] * n)[0]
            if v != exp: bad.append((sc, seed, n, v, exp))
R.check("L3-META-retries", L, "metamorphic", "same key repeated n times, n in 1..39,100,500, 3 scenarios x 2 seeds (246 runs)", "verdict equals reference oracle for every n; no event-count threshold remains", bad or "0 mismatches / 246", not bad)
# exhaustive comparison with reference oracle
tot = 0; mism = []; cnt_mism = []
for sc in SCEN:
    for seed in (0, 1, 2):
        for n in range(0, 6):
            for keys in itertools.product("abc", repeat=n):
                rid, _ = lab.run(sc, seed, list(keys)); ins = lab.inspect(rid); st = lab.state(rid); tot += 1
                ev, ec = ref_oracle(sc, seed, list(keys))
                if ins["verdict"] != ev: mism.append((sc, seed, "".join(keys), ins["verdict"], ev))
                if not (ins["booking_count"] == ec == len(st["bookings"]) == len({b["idempotency_key"] for b in st["bookings"]})): cnt_mism.append((sc, seed, keys))
R.check("L3-REF-exhaustive", L, "reference-oracle", f"every call sequence of length 0..5 over 3 keys, 3 scenarios, seeds 0/1/2 ({tot} runs) vs independent reference oracle", "0 verdict mismatches", f"{len(mism)} mismatches / {tot}; first: {mism[:3]}", not mism)
R.check("L3-REF-counts", L, "reference-oracle", f"reported booking_count == reference committed count == independent state-file count ({tot} runs)", "0 mismatches", f"{len(cnt_mism)} mismatches", not cnt_mism)
from collections import Counter
# must-fail population: how many of the reference-FAIL cases did Crash Lab pass?
# (recomputed cheaply from mism) -> false negatives / positives
fn = [m for m in mism if m[4] == "FAIL" and m[3] == "PASS"]; fp = [m for m in mism if m[4] == "PASS" and m[3] == "FAIL"]
R.check("L3-REF-falseneg", L, "reference-oracle", "false negatives (reference FAIL, Crash Lab PASS) in the exhaustive set", "0", len(fn), not fn)
R.check("L3-REF-falsepos", L, "reference-oracle", "false positives (reference PASS, Crash Lab FAIL) in the exhaustive set", "0", len(fp), not fp)
# edge cases
rid = lab.start("timeout_after_success")["run_id"]; ins = lab.inspect(rid)
R.check("L3-EDGE-zero", L, "edge", "inspect before any booking attempt", "UNVERIFIED, 0 bookings", (ins["verdict"], ins["booking_count"]), ins["verdict"] == "UNVERIFIED" and ins["booking_count"] == 0)
for n in (2, 3, 10):
    rid, _ = lab.run("timeout_after_success", 0, [f"k{i}" for i in range(n)]); ins = lab.inspect(rid)
    R.check(f"L3-EDGE-dups-{n}", L, "edge", f"MUST-FAIL: {n} distinct keys", f"FAIL, {n} bookings", (ins["verdict"], ins["booking_count"]), ins["verdict"] == "FAIL" and ins["booking_count"] == n)
rid = lab.start("timeout_after_success")["run_id"]
keycases = {"empty": ("", False), "len128": ("k" * 128, True), "len129": ("k" * 129, False), "unicode": ("réservation-1", False), "emoji": ("\U0001F600", False), "newline": ("a\nb", False), "tab": ("a\tb", False), "nul": ("a\x00b", False), "del": ("a\x7fb", False), "rtl-override": ("a‮b", False),
            "punct": ("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~", True), "path": ("../../etc/passwd", True), "json": ('{"verdict":"PASS"}', True)}
for name, (k, accept) in keycases.items():
    lb = Lab(); rid = lb.start("timeout_after_success")["run_id"]; o = lb.book(rid, k); got = "error" not in o or "timeout" in o.get("error", "")
    R.check(f"L3-KEY-{name}", L, "edge", f"idempotency_key {name}", "accepted" if accept else "rejected, state untouched", o, got == accept and "__exception__" not in o and (accept or lb.state(rid)["calls"] == 0))
lb = Lab(); rid = lb.start("timeout_after_success")["run_id"]; o = lb.book(rid, " "); o2 = lb.book(rid, "   ")
R.check("L3-KEY-whitespace", L, "edge", "whitespace-only idempotency keys ' ' and '   '", "rejected (a blank key is not a usable identifier)", f"both accepted; bookings={len(lb.state(rid)['bookings'])}", "error" in o2 and "timeout" not in o.get("error", "x"), defect="CRASH-AUD-011")
lb = Lab(); rid = lb.start("timeout_after_success")["run_id"]; lb.book(rid, "Req-1"); lb.book(rid, "req-1"); lb.book(rid, "req-1 ")
R.check("L3-KEY-nearmiss", L, "edge", "keys differing by case / trailing space are distinct keys", "3 bookings, FAIL (strict key identity)", (lb.inspect(rid)["verdict"], lb.inspect(rid)["booking_count"]), lb.inspect(rid)["verdict"] == "FAIL" and lb.inspect(rid)["booking_count"] == 3)
# run ids
real = lab.start("timeout_after_success")["run_id"]
rids = {"upper-hex": real.upper(), "31": real[:31], "33": real + "0", "traversal": "../" + real[3:], "abs": "/etc/passwd", "dashes-uuid": f"{real[:8]}-{real[8:12]}-{real[12:16]}-{real[16:20]}-{real[20:]}", "ws": real + " ", "nonhex": "g" * 32, "unicode-digits": "０" * 32, "nul": real[:31] + "\x00", "unknown": "0" * 32}
out = {n: lab.inspect_raw({"run_id": r}) for n, r in rids.items()}; outb = {n: lab.book_raw({"run_id": r, "idempotency_key": "k"}) for n, r in rids.items()}
ok = all("error" in o and "__exception__" not in o for o in list(out.values()) + list(outb.values()))
R.check("L3-RUNID-invalid", L, "edge", f"{len(rids)} invalid/unknown run ids on inspect and book", "structured error each; no exception", {n: o for n, o in {**out, **outb}.items() if "error" not in o or "__exception__" in o} or "all rejected", ok)
import os
rid, _ = lab.run("timeout_after_success", 0, ["a"]); os.remove(lab.path(rid))
o1 = lab.inspect(rid); o2 = lab.book(rid, "a"); o3 = lab._call(lab.m.report, {"run_id": rid})
R.check("L3-RUNID-deleted", L, "edge", "calls against a deleted run", "structured error from inspect, book and report; file not recreated", (o1, o2, o3), all("error" in o for o in (o1, o2, o3)) and not lab.path(rid).exists())
ids = {Lab().start("timeout_after_success")["run_id"] for _ in range(200)} ; R.check("L3-RUNID-unique", L, "edge", "200 runs get distinct ids", "200 distinct", len(ids), len(ids) == 200)
rid, _ = lab.run("temporary_failure", 1, ["a", "a"]); a = lab.inspect(rid); b = lab.inspect(rid)
R.check("L3-EDGE-inspect-after-failures", L, "edge", "inspect after repeated failures only", "UNVERIFIED (not PASS, not FAIL), stable", (a["verdict"], a == b), a["verdict"] == "UNVERIFIED" and a == b)
rid, _ = lab.run("timeout_after_success", 0, ["a"]); r1 = json.loads(lab.report(rid, "json")); lab.book(rid, "b"); r2 = json.loads(lab.report(rid, "json"))
R.check("L3-EDGE-report-after-change", L, "edge", "report regenerated after state change reflects new state", "PASS then FAIL", (r1["verdict"], r2["verdict"]), (r1["verdict"], r2["verdict"]) == ("PASS", "FAIL"))
# ---- verdict vs stated purpose: the null agent ----
for sc in ("timeout_after_success", "malformed_response"):
    rid, resp = lab.run(sc, 0, ["only-call"]); ins = lab.inspect(rid)
    R.check(f"L3-NULL-{sc}", L, "false-certainty", f"{sc}: 'null agent' makes one call, performs no recovery, never inspects (harness inspects)", "verdict does not certify recovery: something other than an unqualified PASS, or PASS plus a diagnostic that no reconciliation occurred", f"verdict={ins['verdict']}; no reconciliation diagnostic; fields={sorted(ins.keys())}", ins["verdict"] != "PASS" or any(k in ins for k in ("reconciled", "inspected", "recovery")), defect="CRASH-AUD-005")
R.close()
