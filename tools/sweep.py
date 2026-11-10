"""Regenerate the scripted oracle sweep at the release code (evidence for the pinned commit).
Run from the repository root: python tools/sweep.py"""
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("crash_lab_sweep", root / "__init__.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

with tempfile.TemporaryDirectory(prefix="crash-lab-sweep-") as temp:
    lab._root = lambda: Path(temp) / "runs"
    sweep = []
    for scenario in sorted(lab.SCENARIOS):
        for seed in (0, 1, 7):
            rid = json.loads(lab.start({"scenario": scenario, "seed": seed}))["run_id"]
            args = {"run_id": rid, "idempotency_key": "request-1"}
            for _ in range(4):  # exceed every budget deliberately; same key throughout
                lab.book(args)
            sweep.append(json.loads(lab.inspect({"run_id": rid})))
    source_sha = hashlib.sha256((root / "__init__.py").read_bytes()).hexdigest()
    out = {"sweep": sweep,
           "source_sha256___init__": source_sha,
           "expected": "every trial: one booking (same key), verdict PASS, integrity verified, excessive_retries true (calls beyond budget)"}
    (root / "evidence" / "oracle-sweep.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    ok = all(t["booking_count"] == 1 and t["verdict"] == "PASS" and t["integrity"] == "verified" and t["excessive_retries"] for t in sweep)
    print(f"trials={len(sweep)} all_pass_with_flags={ok}")
