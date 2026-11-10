"""Stdlib acceptance tests; plugin doctor/validate separately check registration."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class CrashLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        spec = importlib.util.spec_from_file_location("crash_lab_test", Path(__file__).parent / "__init__.py")
        self.lab = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.lab)
        self.lab._root = lambda: Path(self.temp.name) / "runs"

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def invoke(fn, args):
        return json.loads(fn(args))

    def run_case(self, scenario, seed=0):
        return self.invoke(self.lab.start, {"scenario": scenario, "seed": seed})["run_id"]

    def test_timeout_reconciled_without_retry(self):
        rid = self.run_case("timeout_after_success")
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "UNVERIFIED")
        self.assertIn("timeout", self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "request-1"})["error"])
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(state["booking_count"], 1)
        self.assertTrue(state["events"][0]["response"]["error"].startswith("simulated timeout"))

    def test_unsafe_retry_fails_and_same_key_deduplicates(self):
        rid = self.run_case("timeout_after_success")
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "first"})
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "second"})
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "FAIL")
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["booking_count"], 2)
        rid2 = self.run_case("timeout_after_success")
        self.invoke(self.lab.book, {"run_id": rid2, "idempotency_key": "first"})
        self.invoke(self.lab.book, {"run_id": rid2, "idempotency_key": "first"})
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid2})["booking_count"], 1)

    def test_malformed_and_503(self):
        rid = self.run_case("malformed_response")
        self.assertIsNone(self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "m"})["booking_id"])
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "PASS")
        rid = self.run_case("temporary_failure")
        self.assertIn("503", self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "f"})["error"])
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "UNVERIFIED")
        self.assertEqual(self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "f"})["status"], "confirmed")
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "PASS")

    def test_invalid_input_and_unknown_run(self):
        self.assertIn("error", self.invoke(self.lab.start, {"scenario": "real_service"}))
        self.assertIn("error", self.invoke(self.lab.book, {"run_id": "../oops", "idempotency_key": "ok"}))
        self.assertIn("error", self.invoke(self.lab.inspect, {"run_id": "0" * 32}))
        rid = self.run_case("timeout_after_success")
        self.assertIn("error", self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": ""}))
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "UNVERIFIED")

    def test_corrupt_state_file_recovers_cleanly(self):
        rid = self.run_case("timeout_after_success")
        self.lab._path(rid).write_text("{not json", encoding="utf-8")
        self.assertIn("error", self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "x"}))
        self.assertIn("error", self.invoke(self.lab.inspect, {"run_id": rid}))

    def test_same_key_repeated_retries_stay_pass(self):
        """Kevin's case (PR #151695): 3 same-key retries, 1 booking — must be PASS."""
        rid = self.run_case("timeout_after_success")
        args = {"run_id": rid, "idempotency_key": "request-1"}
        self.assertIn("timeout", self.invoke(self.lab.book, args)["error"])
        for _ in range(2):  # same-key retries reconcile to the same booking
            self.assertEqual(self.invoke(self.lab.book, args)["status"], "confirmed")
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["booking_count"], 1)
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(state["retry_count"], 3)
        self.assertTrue(state["excessive_retries"])
        report = self.lab.report({"run_id": rid, "format": "markdown"})
        self.assertIn("**PASS**", report)
        self.assertIn("retries: 3 (excessive)", report)

    def test_restrained_retry_budget_not_flagged(self):
        rid = self.run_case("timeout_after_success")
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "request-1"})
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["verdict"], "PASS")
        self.assertFalse(state["excessive_retries"])

    def test_distinct_keys_still_fail_on_duplicates(self):
        rid = self.run_case("timeout_after_success")
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "first"})
        self.invoke(self.lab.book, {"run_id": rid, "idempotency_key": "second"})
        state = self.invoke(self.lab.inspect, {"run_id": rid})
        self.assertEqual(state["booking_count"], 2)
        self.assertEqual(state["verdict"], "FAIL")

    def test_seeded_503_and_markdown_export(self):
        rid = self.run_case("temporary_failure", seed=1)
        args = {"run_id": rid, "idempotency_key": "seeded"}
        self.assertIn("503", self.invoke(self.lab.book, args)["error"])
        self.assertIn("503", self.invoke(self.lab.book, args)["error"])
        self.assertEqual(self.invoke(self.lab.book, args)["status"], "confirmed")
        self.assertEqual(self.invoke(self.lab.inspect, {"run_id": rid})["verdict"], "PASS")
        self.assertIn("Service-state verdict: **PASS**", self.lab.report({"run_id": rid, "format": "markdown"}))


if __name__ == "__main__":
    unittest.main()
