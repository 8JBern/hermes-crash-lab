"""Mutation score of (existing 9 tests + audit regression tests, Concurrency class excluded for time) vs the draft fix."""
import ast, copy, json, shutil, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from audit_lib import *
import mutate_ops
R = Rec("FIX_mutation"); P = AUDIT / "proposed"
src = (P / "__init__.py").read_text(); base, muts = mutate_ops.mutants(src)
def run(code):
    w = Path(tempfile.mkdtemp(prefix="mutf_", dir=SCRATCH)); shutil.copy(P / "test_crash_lab.py", w); shutil.copy(P / "test_crash_lab_audit.py", w); (w / "__init__.py").write_text(code)
    try: rc = subprocess.run([sys.executable, "-B", "-m", "unittest", "-f", "-q", "test_crash_lab", "test_crash_lab_audit.OracleAgainstReference", "test_crash_lab_audit.StateIntegrity", "test_crash_lab_audit.InputHandling", "test_crash_lab_audit.Bounds", "test_crash_lab_audit.Diagnostics"], cwd=w, capture_output=True, timeout=120).returncode
    except subprocess.TimeoutExpired: rc = 99
    shutil.rmtree(w, ignore_errors=True); return rc
assert run(base) == 0
with ThreadPoolExecutor(4) as ex: rcs = list(ex.map(lambda m: run(m[1]), muts))
killed = [d for (d, _), rc in zip(muts, rcs) if rc]; survived = [d for (d, _), rc in zip(muts, rcs) if not rc]
for s in survived: R.note("  SURVIVED", s)
score = len(killed) / len(muts)
R.check("FIX-MUT-score", "FIX", "mutation", f"existing + audit regression tests (concurrency class excluded for run time) vs {len(muts)} AST mutants of the draft fix", "materially higher than the 71% of the 1.0.1 suite", f"score {score:.0%} ({len(killed)} killed, {len(survived)} survived)", score > 0.71, rev="draft-1.0.2 (audit proposal)")
R.close()
