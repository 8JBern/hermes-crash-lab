"""Lock-regression tests added during 1.0.2 remediation.

The audit's stale-lock-break design (and a PID-liveness adaptation of it) was found to
contain a time-of-check/time-of-use double-entry window: a waiter that decided the lock
had vanished could unlink a *new* owner's lock file and acquire alongside it, losing
booked events (reproduced 3/20 runs: 30 successful responses, 23-29 events persisted).
1.0.2 therefore uses flock on POSIX (kernel mutex, no stale handling) and an
owner-release-only O_EXCL lock file elsewhere. These tests pin that behaviour.
Stdlib only; no assertions read plugin state through the plugin's own inspect().
"""
import importlib.util
import json
import multiprocessing
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def load(root):
    spec = importlib.util.spec_from_file_location("crash_lab_lock_test", HERE / "__init__.py")
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    lab._root = lambda: Path(root) / "runs"
    return lab


def _worker(root, rid, key, go_at, n, q):
    lab = load(root)
    while time.time() < go_at:
        pass
    q.put([json.loads(lab.book({"run_id": rid, "idempotency_key": key})) for _ in range(n)])


class LockRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.lab = load(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _race(self, keys, per_worker):
        rid = json.loads(self.lab.start({"scenario": "timeout_after_success", "seed": 0}))["run_id"]
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        go = time.time() + 1.0
        procs = [ctx.Process(target=_worker, args=(self.temp.name, rid, k, go, per_worker, q)) for k in keys]
        for p in procs:
            p.start()
        outs = [q.get(timeout=60) for _ in procs]
        for p in procs:
            p.join()
        return rid, [r for o in outs for r in o]

    def _disk_state(self, rid):
        return json.loads((Path(self.temp.name) / "runs" / (rid + ".json")).read_text())

    def test_same_key_six_writers_no_event_loss_repeated(self):
        """The exact case the double-entry bug ate events from: repeated to catch flakes."""
        for trial in range(5):
            rid, responses = self._race(["same"] * 6, per_worker=5)
            state = self._disk_state(rid)
            self.assertEqual(len(state["events"]), 30, f"trial {trial}: events lost")
            self.assertEqual(len(state["bookings"]), 1, f"trial {trial}: booking count wrong")
            self.assertEqual(len(responses), 30)
            busy = [r for r in responses if "busy" in r.get("error", "")]
            self.assertEqual(busy, [], f"trial {trial}: unexpected lock-contention refusals")

    def test_distinct_keys_six_writers_all_persisted(self):
        rid, responses = self._race([f"key-{i}" for i in range(6)], per_worker=5)
        state = self._disk_state(rid)
        self.assertEqual(len(state["events"]), 30)
        self.assertEqual(len(state["bookings"]), 6)
        self.assertEqual(sorted(b["idempotency_key"] for b in state["bookings"]),
                         [f"key-{i}" for i in range(6)])


if __name__ == "__main__":
    unittest.main()
