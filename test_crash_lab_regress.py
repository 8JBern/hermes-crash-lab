"""Regression tests for the 1.0.2 remediation additions:
- reconciled diagnostic (CRASH-AUD-005, audit check L3-NULL-*)
- stale .tmp sweep on crash_book (CRASH-AUD-015, audit check L4-WRITE-hardkill-litter)
Stdlib only.
"""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def load(root):
    spec = importlib.util.spec_from_file_location("crash_lab_regress_test", HERE / "__init__.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    lab._root = lambda: Path(root) / "runs"
    return lab


class RemediationRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = load(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, fn, args):
        return json.loads(fn(args))

    def rid(self, scenario, seed=0):
        return self.invoke(self.lab.start, {"scenario": scenario, "seed": seed})["run_id"]

    def test_inaction_pass_is_explicitly_marked_unreconciled(self):
        rid = self.rid("timeout_after_success")
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "k"})
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["verdict"], "PASS")
        self.assertFalse(state["reconciled"])
        report = self.lab.report({"run_id": rid, "format": "markdown"})
        self.assertIn("reconciled: no", report)

    def test_same_key_retry_is_marked_reconciled(self):
        rid = self.rid("timeout_after_success")
        args = {"run_id": rid, "idempotency_key": "k"}
        self.invoke(self.lab.book, args)
        self.invoke(self.lab.book, args)
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["verdict"], "PASS")
        self.assertTrue(state["reconciled"])

    def test_503_recovery_is_marked_reconciled(self):
        rid = self.rid("temporary_failure")
        args = {"run_id": rid, "idempotency_key": "k"}
        self.assertIn("503", self.invoke(self.lab.book, args)["error"])
        self.assertEqual(self.invoke(self.lab.book, args)["status"], "confirmed")
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["verdict"], "PASS")
        self.assertTrue(state["reconciled"])

    def test_stale_tmp_cleaned_on_book(self):
        rid = self.rid("timeout_after_success")
        runs = Path(self.temp.name) / "runs"
        stale = runs / (rid + ".deadbeef.tmp")
        stale.write_text("{}")
        old = time.time() - self.lab.TMP_STALE_S - 10
        import os
        os.utime(stale, (old, old))
        fresh = runs / (rid + ".fresh.tmp")
        fresh.write_text("{}")
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "k"})
        self.assertFalse(stale.exists())       # older than the sweep cutoff: removed
        self.assertTrue(fresh.exists())        # recent: left alone


if __name__ == "__main__":
    unittest.main()
