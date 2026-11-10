import csv, json, glob, collections, sys
from audit_lib import AUDIT
order = ["L0_REL_baseline_release", "L1_functional", "L2_L3_fault_oracle", "L4_persistence", "L4_concurrency_security", "L4_hermes_integration", "L5_adversarial_property_mutation", "L5_mutation", "L5_suite_assessment", "FIX_proposed_verification", "FIX_mutation"]
rows = []
for n in order:
    p = AUDIT / "evidence" / f"results_{n}.jsonl"
    if p.exists(): rows += [json.loads(l) for l in open(p)]
ids = [r["test_id"] for r in rows]; assert len(ids) == len(set(ids)), [i for i, c in collections.Counter(ids).items() if c > 1]
lvl = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "REL": 6, "FIX": 7}
rows.sort(key=lambda r: lvl[r["level"]])
out = sys.argv[1]
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["Test ID", "Level", "Category", "Objective", "Revision", "Mode", "Expected", "Actual", "Result", "Evidence", "Defect ID"])
    for r in rows: w.writerow([r["test_id"], r["level"], r["category"], r["objective"], r["revision"], r["mode"], r["expected"], r["actual"], r["result"], r["evidence"], r["defect"]])
tot = collections.Counter(r["result"] for r in rows); print("TOTAL", len(rows), dict(tot))
audit = [r for r in rows if r["level"] != "FIX"]; print("AUDIT (excl. FIX)", len(audit), dict(collections.Counter(r["result"] for r in audit)))
by = collections.defaultdict(collections.Counter)
for r in rows: by[r["level"]][r["result"]] += 1
for k in sorted(by, key=lvl.get): print(k, sum(by[k].values()), dict(by[k]))
d = collections.defaultdict(list)
for r in rows:
    if r["defect"] and r["result"] in ("FAIL", "INCONCLUSIVE", "NOT TESTED"): d[r["defect"].split(" ")[0]].append(r["test_id"])
for k in sorted(d): print(k, len(d[k]), d[k][:60])
json.dump({"total": len(rows), "by_result": tot, "by_level": {k: dict(v) for k, v in by.items()}, "defect_tests": d}, open(AUDIT / "evidence/summary.json", "w"), indent=1)
