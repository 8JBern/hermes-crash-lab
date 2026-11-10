"""Shared harness for the independent Crash Lab audit. Stdlib only.
Loads a pinned revision of the plugin from a disposable git worktree, redirects its storage
root to a throwaway directory, and records every test outcome to evidence/results_<level>.jsonl."""
import hashlib, importlib.util, json, os, sys, tempfile, uuid
from pathlib import Path
sys.dont_write_bytecode = True
AUDIT = Path(os.environ.get("CRASH_AUDIT_ROOT", "/home/claude/audit"))
REVS = {"1.0.0": AUDIT / "work/rev-1.0.0", "1.0.1": AUDIT / "work/rev-1.0.1"}
SHAS = {"1.0.0": "44c8071aa68a626e0d89d4afe697e3b7b864695e", "1.0.1": "9a712f9714ff5687425f0ffc9ac7eb6f9eb441cb"}
SCRATCH = AUDIT / "scratch"
SCEN = ("timeout_after_success", "malformed_response", "temporary_failure")

def load_module(rev="1.0.1", src=None):
    src = Path(src) if src else REVS[rev] / "__init__.py"
    spec = importlib.util.spec_from_file_location("cl_" + uuid.uuid4().hex, src)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

class Lab:
    def __init__(self, rev="1.0.1", root=None, src=None):
        self.rev = rev
        self.root = Path(root) if root else Path(tempfile.mkdtemp(prefix="cl_", dir=SCRATCH))
        self.m = load_module(rev, src)
        self.m._root = lambda: self.root / "runs"
    def _call(self, fn, args, raw=False):
        try:
            out = fn(args)
        except BaseException as e:  # an exception escaping a tool handler is itself a finding
            return {"__exception__": f"{type(e).__name__}: {e}"}
        if raw: return out
        try: return json.loads(out)
        except Exception: return {"__nonjson__": out}
    def start(self, scenario, seed=0, **kw):
        a = {"scenario": scenario, "seed": seed}; a.update(kw); return self._call(self.m.start, a)
    def start_raw(self, args): return self._call(self.m.start, args)
    def book(self, rid, key): return self._call(self.m.book, {"run_id": rid, "idempotency_key": key})
    def book_raw(self, args): return self._call(self.m.book, args)
    def inspect(self, rid): return self._call(self.m.inspect, {"run_id": rid})
    def inspect_raw(self, args): return self._call(self.m.inspect, args)
    def report(self, rid, fmt=None):
        a = {"run_id": rid};
        if fmt is not None: a["format"] = fmt
        return self._call(self.m.report, a, raw=True)
    def path(self, rid): return self.root / "runs" / (rid + ".json")
    def state(self, rid): return json.loads(self.path(rid).read_text(encoding="utf-8"))   # independent read
    def write_state(self, rid, obj): self.path(rid).write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    def files(self): return sorted(p.name for p in (self.root / "runs").glob("*")) if (self.root / "runs").exists() else []
    def run(self, scenario, seed, keys):
        rid = self.start(scenario, seed)["run_id"]; resp = [self.book(rid, k) for k in keys]; return rid, resp

def ref_oracle(scenario, seed, keys):
    """Independent reference oracle. Derived from the README's published service semantics, NOT from
    the plugin code: timeout/malformed commit the booking on every call (idempotent per key);
    temporary_failure rejects the first 1 (even seed) or 2 (odd seed) calls without committing.
    Safety invariant: one booking intended -> >1 committed distinct keys is FAIL; exactly 1 is PASS;
    0 (or no attempt) is UNVERIFIED."""
    committed = []
    fails = 0 if scenario != "temporary_failure" else (2 if seed % 2 else 1)
    for i, k in enumerate(keys, 1):
        if i <= fails: continue
        if k not in committed: committed.append(k)
    if not keys: return "UNVERIFIED", 0
    if len(committed) > 1: return "FAIL", len(committed)
    if len(committed) == 1: return "PASS", 1
    return "UNVERIFIED", 0

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class Rec:
    def __init__(self, name):
        self.name = name; self.rows = []; self.log = open(AUDIT / "evidence" / f"{name}.log", "w")
    def note(self, *a):
        s = " ".join(str(x) for x in a); print(s); self.log.write(s + "\n")
    def add(self, tid, level, cat, objective, expected, actual, result, defect="", rev="1.0.1", mode="direct"):
        assert result in ("PASS", "FAIL", "INCONCLUSIVE", "NOT TESTED")
        row = dict(test_id=tid, level=level, category=cat, objective=objective, revision=rev, mode=mode,
                   expected=str(expected), actual=str(actual)[:600], result=result,
                   evidence=f"evidence/{self.name}.log", defect=defect)
        self.rows.append(row); self.note(f"[{result}] {tid} | exp: {expected} | act: {str(actual)[:400]}" + (f" | {defect}" if defect else ""))
    def check(self, tid, level, cat, objective, expected, actual, ok, defect="", **kw):
        self.add(tid, level, cat, objective, expected, actual, "PASS" if ok else "FAIL", defect if not ok else "", **kw)
    def close(self):
        with open(AUDIT / "evidence" / f"results_{self.name}.jsonl", "w") as f:
            for r in self.rows: f.write(json.dumps(r) + "\n")
        from collections import Counter
        self.note("SUMMARY", self.name, dict(Counter(r["result"] for r in self.rows))); self.log.close()
