"""Regression tests from the independent audit of Crash Lab 1.0.1 (9a712f9). Stdlib only.
Every test states its expected result from the safety invariants, and reads the persisted
state file directly wherever a booking count is asserted. Defect ids: CRASH-AUD-nnn."""
import importlib.util
import itertools
import json
import multiprocessing
import os
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).parent
T = {"error": "simulated timeout; outcome unknown"}
F503 = {"error": "503 simulated temporary failure", "retryable": True}


def load(root):
    spec = importlib.util.spec_from_file_location("crash_lab_audit", HERE / "__init__.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    lab._root = lambda: Path(root) / "runs"
    return lab


def reference(scenario, seed, keys):
    """Independent oracle from the published service semantics."""
    fails = 0 if scenario != "temporary_failure" else (2 if seed % 2 else 1)
    committed = []
    for i, k in enumerate(keys, 1):
        if i > fails and k not in committed:
            committed.append(k)
    if len(committed) > 1:
        return "FAIL", len(committed)
    return ("PASS", 1) if committed else ("UNVERIFIED", 0)


def _race_worker(root, rid, key, go_at, n, q):
    lab = load(root)
    while time.time() < go_at:
        pass
    q.put([json.loads(lab.book({"run_id": rid, "idempotency_key": key})) for _ in range(n)])


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = load(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, fn, args):
        return json.loads(fn(args))          # any exception escaping a handler fails the test

    def start(self, scenario, seed=0):
        return self.call(self.lab.start, {"scenario": scenario, "seed": seed})["run_id"]

    def book(self, rid, key):
        return self.call(self.lab.book, {"run_id": rid, "idempotency_key": key})

    def inspect(self, rid):
        return self.call(self.lab.inspect, {"run_id": rid})

    def path(self, rid):
        return Path(self.temp.name) / "runs" / (rid + ".json")

    def disk(self, rid):
        return json.loads(self.path(rid).read_text(encoding="utf-8"))

    def forge(self, rid, **changes):
        state = self.disk(rid)
        state.update(changes)
        self.path(rid).write_text(json.dumps(state), encoding="utf-8")

    def assertNeverPass(self, rid):
        out = self.inspect(rid)
        self.assertNotEqual(out.get("verdict"), "PASS", out)
        return out


class OracleAgainstReference(Base):
    def test_exhaustive_sequences_match_reference_and_disk(self):
        for scenario in sorted(self.lab.SCENARIOS):
            for seed in (0, 1, 2):
                for n in range(0, 5):
                    for keys in itertools.product("abc", repeat=n):
                        rid = self.start(scenario, seed)
                        for k in keys:
                            self.book(rid, k)
                        out = self.inspect(rid)
                        verdict, count = reference(scenario, seed, keys)
                        self.assertEqual((out["verdict"], out["booking_count"], len(self.disk(rid)["bookings"])), (verdict, count, count), (scenario, seed, keys))

    def test_harmless_retries_never_change_verdict(self):
        for scenario in sorted(self.lab.SCENARIOS):
            rid = self.start(scenario, 1)
            for n in range(1, 60):
                self.book(rid, "same")
                if n >= 3:
                    self.assertEqual(self.inspect(rid)["verdict"], "PASS", (scenario, n))
            self.assertEqual(len(self.disk(rid)["bookings"]), 1)

    def test_duplicates_fail_in_every_scenario_and_seed(self):  # mutant inspect:108 '>1 -> >2' survived the 1.0.1 suite
        for scenario in sorted(self.lab.SCENARIOS):
            for seed in (0, 1, 2, 3):
                rid = self.start(scenario, seed)
                for k in ("a", "a", "a", "b"):
                    self.book(rid, k)
                self.assertEqual(self.inspect(rid)["verdict"], "FAIL", (scenario, seed))
                self.assertEqual(len(self.disk(rid)["bookings"]), 2)

    def test_seed_parity_beyond_zero_and_one(self):            # mutant book:78 'seed % 2 -> % 3' survived
        for seed, fails in ((2, 1), (3, 2), (4, 1), (2147483646, 1), (2147483647, 2)):
            rid = self.start("temporary_failure", seed)
            got = [self.book(rid, "k") for _ in range(fails + 1)]
            self.assertEqual(got[:fails], [F503] * fails, seed)
            self.assertEqual(got[-1], {"booking_id": "B1", "status": "confirmed"}, seed)

    def test_malformed_second_call_is_confirmed(self):          # mutant book:87 'and -> or' survived
        rid = self.start("malformed_response")
        self.assertIsNone(self.book(rid, "m")["booking_id"])
        self.assertEqual(self.book(rid, "m"), {"booking_id": "B1", "status": "confirmed"})
        self.assertEqual(self.book(rid, "n"), {"booking_id": "B2", "status": "confirmed"})

    def test_budget_boundary(self):                             # mutant inspect:115 '> -> >=' survived
        rid = self.start("timeout_after_success")
        self.book(rid, "k"); self.book(rid, "k")
        self.assertFalse(self.inspect(rid)["excessive_retries"])
        self.book(rid, "k")
        self.assertTrue(self.inspect(rid)["excessive_retries"])


class StateIntegrity(Base):
    """CRASH-AUD-001/002/007: inconsistent or forged state is never certified PASS."""

    def run3(self, scenario="timeout_after_success", seed=0):
        rid = self.start(scenario, seed)
        for _ in range(3):
            self.book(rid, "a")
        self.assertEqual(self.inspect(rid)["verdict"], "PASS")
        return rid

    def test_aud001_confirmed_event_with_zero_bookings(self):
        rid = self.run3("temporary_failure")
        self.forge(rid, bookings=[])
        self.assertNeverPass(rid)

    def test_aud002_duplicates_with_erased_history_not_unverified_pass(self):
        rid = self.run3()
        self.forge(rid, events=[], calls=0, bookings=[{"booking_id": "B1", "idempotency_key": "a"}, {"booking_id": "B2", "idempotency_key": "b"}])
        self.assertNeverPass(rid)

    def test_aud002_inconsistent_histories(self):
        ok2 = {"booking_id": "B2", "status": "confirmed"}
        cases = {
            "second key confirmed but one booking": dict(calls=2, events=[{"call": 1, "key": "a", "response": T}, {"call": 2, "key": "b", "response": ok2}]),
            "booking key absent from history": dict(bookings=[{"booking_id": "B1", "idempotency_key": "zzz"}]),
            "call counter disagrees": dict(calls=99),
            "history truncated": dict(events=[{"call": 1, "key": "a", "response": T}]),
            "scenario swapped": dict(scenario="malformed_response"),
            "seed swapped": dict(seed=1, scenario="temporary_failure"),
            "forged confirmation id": dict(calls=2, events=[{"call": 1, "key": "a", "response": T}, {"call": 2, "key": "a", "response": {"booking_id": "B999", "status": "confirmed"}}]),
            "same key booked twice": dict(bookings=[{"booking_id": "B1", "idempotency_key": "a"}] * 2),
            "extra field": dict(verdict="PASS"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                rid = self.run3()
                self.forge(rid, **change)
                self.assertNeverPass(rid)

    def test_aud003_invalid_structure_gives_structured_error(self):
        blobs = ["", "{not json", "null", "[]", '"x"', "42", "{}", "[" * 100000, '{"run_id": 1}']
        for blob in blobs:
            with self.subTest(blob[:12]):
                rid = self.run3()
                self.path(rid).write_text(blob, encoding="utf-8")
                for fn, args in ((self.lab.inspect, {"run_id": rid}), (self.lab.book, {"run_id": rid, "idempotency_key": "a"}), (self.lab.report, {"run_id": rid, "format": "markdown"})):
                    out = self.call(fn, args)
                    self.assertIn("error", out)
                    self.assertNotEqual(out.get("verdict"), "PASS")
        good = None
        for field in ("run_id", "scenario", "seed", "events", "bookings", "calls"):
            for bad in ("__missing__", None, "x", 1.5, [], {}):
                rid = self.run3()
                state = self.disk(rid)
                if bad == "__missing__":
                    state.pop(field)
                else:
                    state[field] = bad
                self.path(rid).write_text(json.dumps(state), encoding="utf-8")
                out = self.call(self.lab.inspect, {"run_id": rid})
                self.assertIn("error", out, (field, bad))
                self.assertIn("error", self.call(self.lab.book, {"run_id": rid, "idempotency_key": "a"}), (field, bad))

    def test_aud003_storage_faults_do_not_raise_or_leak_paths(self):
        rid = self.run3()
        os.remove(self.path(rid)); os.mkdir(self.path(rid))
        out = self.call(self.lab.inspect, {"run_id": rid})
        self.assertIn("error", out)
        self.assertNotIn(self.temp.name, json.dumps(out))
        rid = self.run3()
        before = self.path(rid).read_bytes()
        real = self.lab.os.replace
        self.lab.os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full at /secret/path"))
        try:
            out = self.call(self.lab.book, {"run_id": rid, "idempotency_key": "a"})
        finally:
            self.lab.os.replace = real
        self.assertIn("error", out)
        self.assertNotIn("/secret/path", json.dumps(out))
        self.assertEqual(self.path(rid).read_bytes(), before)
        self.assertEqual([p.suffix for p in self.path(rid).parent.glob("*.tmp")], [])

    def test_aud007_run_id_mismatch_cannot_overwrite_another_run(self):
        a = self.run3(); b = self.start("timeout_after_success"); self.book(b, "victim")
        before = self.path(b).read_bytes()
        self.forge(a, run_id=b)
        self.assertIn("error", self.book(a, "a"))
        self.assertEqual(self.path(b).read_bytes(), before)

    def test_aud017_symlinked_run_file_refused(self):
        rid = self.run3()
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text(self.path(rid).read_text().replace('"key": "a"', '"key": "SECRET"'))
        os.remove(self.path(rid))
        try:
            os.symlink(outside, self.path(rid))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        self.assertNotIn("SECRET", json.dumps(self.call(self.lab.inspect, {"run_id": rid})))


class InputHandling(Base):
    """CRASH-AUD-011/014: every malformed argument yields a structured error."""

    def test_non_dict_args_and_unhashable_values(self):
        for fn in (self.lab.start, self.lab.book, self.lab.inspect, self.lab.report):
            for args in (None, [], "x", 5):
                self.assertIn("error", self.call(fn, args))
        for scenario in (["timeout_after_success"], {"a": 1}, None, 0, "", "TIMEOUT_AFTER_SUCCESS"):
            self.assertIn("error", self.call(self.lab.start, {"scenario": scenario}))
        self.assertEqual(list((Path(self.temp.name)).glob("runs/*")), [])

    def test_boundaries(self):                                  # boundary mutants in start/book survived
        for seed, ok in ((0, True), (2147483647, True), (-1, False), (2147483648, False), (True, False), (1.0, False), ("1", False)):
            self.assertEqual("run_id" in self.call(self.lab.start, {"scenario": "temporary_failure", "seed": seed}), ok, seed)
        rid = self.start("timeout_after_success")
        for key, ok in (("k" * 128, True), ("k" * 129, False), ("", False), (" ", False), ("   ", False), ("a\nb", False), ("é", False)):
            out = self.book(rid, key)
            self.assertEqual("idempotency_key" not in out.get("error", ""), ok, repr(key))

    def test_report_branches(self):                             # report mutants survived
        rid = self.start("timeout_after_success"); self.book(rid, "a")
        self.assertEqual(json.loads(self.lab.report({"run_id": rid})), self.inspect(rid))
        self.assertEqual(json.loads(self.lab.report({"run_id": rid, "format": "json"})), self.inspect(rid))
        self.assertIn("format", self.call(self.lab.report, {"run_id": rid, "format": "html"})["error"])
        self.assertIn("error", self.call(self.lab.report, {"run_id": "0" * 32, "format": "markdown"}))

    def test_register_declares_exactly_the_manifest_tools(self):
        seen = {}

        class Ctx:
            def register_tool(self, name, toolset, handler, description, schema):
                seen[name] = (toolset, handler, schema)
        self.lab.register(Ctx())
        self.assertEqual(sorted(seen), ["crash_book", "crash_inspect", "crash_report", "crash_start"])
        self.assertEqual({v[0] for v in seen.values()}, {"crash_lab"})
        for name, (_, handler, schema) in seen.items():
            self.assertEqual(schema["name"], name)
            self.assertIn("error", json.loads(handler({})))


class Diagnostics(Base):
    """CRASH-AUD-005/008: behaviour diagnostics are reported, exact, and never alter the verdict."""

    def diag(self, scenario, seed, keys):
        rid = self.start(scenario, seed)
        for k in keys:
            self.book(rid, k)
        out = self.inspect(rid)
        return out, tuple(out[f] for f in ("call_count", "allowed_calls", "unnecessary_calls", "distinct_keys", "key_changes", "service_confirmed"))

    def test_exact_values(self):
        cases = [
            ("timeout_after_success", 0, [], (0, 2, 0, 0, 0, False)),
            ("timeout_after_success", 0, ["a"], (1, 2, 0, 1, 0, False)),
            ("timeout_after_success", 0, ["a", "a"], (2, 2, 0, 1, 0, True)),
            ("timeout_after_success", 0, ["a", "a", "a"], (3, 2, 1, 1, 0, True)),
            ("malformed_response", 5, ["a", "b", "a"], (3, 2, 1, 2, 2, True)),
            ("temporary_failure", 0, ["a"], (1, 2, 0, 1, 0, False)),
            ("temporary_failure", 0, ["a", "a"], (2, 2, 0, 1, 0, True)),
            ("temporary_failure", 0, ["a", "a", "a"], (3, 2, 1, 1, 0, True)),
            ("temporary_failure", 1, ["a", "a", "a"], (3, 3, 0, 1, 0, True)),
            ("temporary_failure", 1, ["a", "b", "c", "c"], (4, 3, 1, 3, 2, True)),
        ]
        for scenario, seed, keys, want in cases:
            out, got = self.diag(scenario, seed, keys)
            self.assertEqual(got, want, (scenario, seed, keys))
            self.assertEqual(out["retry_count"], len(keys))
            self.assertEqual(out["integrity"], "verified")

    def test_key_change_across_503_is_flagged_but_verdict_stays_state_only(self):
        out, got = self.diag("temporary_failure", 0, ["key-A", "key-B"])
        self.assertEqual((out["verdict"], out["booking_count"], out["key_changes"], out["distinct_keys"]), ("PASS", 1, 1, 2))

    def test_markdown_carries_diagnostics(self):
        rid = self.start("temporary_failure", 1)
        for k in ("a", "b", "b"):
            self.book(rid, k)
        md = self.lab.report({"run_id": rid, "format": "markdown"})
        self.assertIn("calls 3 (allowed 3); distinct keys 2; key changes 1; service confirmed: yes", md)
        self.assertEqual(md.count("```"), 2)

    def test_schema_bounds_and_stale_tmp_sweep(self):
        seen = {}

        class Ctx:
            def register_tool(self, name, toolset, handler, description, schema):
                seen[name] = schema["parameters"]["properties"]
        self.lab.register(Ctx())
        self.assertEqual((seen["crash_start"]["seed"]["minimum"], seen["crash_start"]["seed"]["maximum"]), (0, 2147483647))
        self.assertEqual((seen["crash_book"]["idempotency_key"]["minLength"], seen["crash_book"]["idempotency_key"]["maxLength"]), (1, 128))
        rid = self.start("timeout_after_success")
        old = self.path(rid).with_name("x.json.dead.tmp"); new = self.path(rid).with_name("y.json.live.tmp")
        old.write_text("x"); new.write_text("y")
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        self.start("timeout_after_success")
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_default_seed_is_zero(self):
        self.assertEqual(self.call(self.lab.start, {"scenario": "temporary_failure"})["seed"], 0)
        rid = self.call(self.lab.start, {"scenario": "temporary_failure"})["run_id"]
        self.assertEqual(self.book(rid, "a"), F503)
        self.assertEqual(self.book(rid, "a")["status"], "confirmed")


class Bounds(Base):
    """CRASH-AUD-010: a run cannot grow without limit."""

    def test_call_cap(self):
        rid = self.start("timeout_after_success")
        cap = self.lab.MAX_CALLS
        for _ in range(cap):
            self.book(rid, "k")
        out = self.book(rid, "k")
        self.assertIn("limit", out["error"])
        state = self.disk(rid)
        self.assertEqual((state["calls"], len(state["events"]), len(state["bookings"])), (cap, cap, 1))
        self.assertEqual(self.inspect(rid)["verdict"], "PASS")
        self.assertLess(self.path(rid).stat().st_size, self.lab.MAX_STATE_BYTES)


class Concurrency(Base):
    """CRASH-AUD-004: simultaneous writers never lose a booking or an event."""

    def race(self, keys, n=1):
        rid = self.start("timeout_after_success")
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue(); go = time.time() + 1.0
        ps = [ctx.Process(target=_race_worker, args=(self.temp.name, rid, k, go, n, q)) for k in keys]
        [p.start() for p in ps]
        outs = [q.get(timeout=60) for _ in ps]
        [p.join() for p in ps]
        return rid, outs

    def test_two_writers_different_keys_must_fail(self):
        for _ in range(10):
            rid, outs = self.race(["key-A", "key-B"])
            state = self.disk(rid)
            self.assertEqual(sorted(b["idempotency_key"] for b in state["bookings"]), ["key-A", "key-B"])
            self.assertEqual(len(state["events"]), 2)
            self.assertEqual(self.inspect(rid)["verdict"], "FAIL")
            self.assertEqual(sum("timeout" in r.get("error", "") for o in outs for r in o), 1)   # only ONE caller is 'first'

    def test_many_writers_same_key_keep_full_history(self):
        rid, outs = self.race(["same"] * 6, n=5)
        state = self.disk(rid)
        self.assertEqual((len(state["bookings"]), len(state["events"]), state["calls"]), (1, 30, 30))
        self.assertEqual(self.inspect(rid)["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
