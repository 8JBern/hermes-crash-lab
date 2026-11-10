"""Mutation testing of the repo's own suite (test_crash_lab.py @9a712f9) against AST mutants of __init__.py @9a712f9."""
import ast, copy, json, shutil, subprocess, sys, tempfile
from pathlib import Path
from audit_lib import *
R = Rec("L5_mutation"); L = "L5"
SRC = REVS["1.0.1"] / "__init__.py"; TEST = REVS["1.0.1"] / "test_crash_lab.py"
src = SRC.read_text(); tree = ast.parse(src)
SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
STR = {"PASS": "FAIL", "FAIL": "PASS", "UNVERIFIED": "PASS", "confirmed": "pending", "temporary_failure": "x", "timeout_after_success": "x", "malformed_response": "x", "error": "err", "warning": "warn", "status": "state", "json": "x", "markdown": "x"}
nodes = list(ast.walk(tree)); muts = []
def fn_of(node):
    for f in ast.walk(tree):
        if isinstance(f, ast.FunctionDef) and f.lineno <= getattr(node, "lineno", 0) <= f.end_lineno: return f.name
    return "<module>"
def emit(desc, node, apply):
    t = copy.deepcopy(tree); target = [n for n in ast.walk(t)][nodes.index(node)]; apply(target)
    try: code = ast.unparse(ast.fix_missing_locations(t))
    except Exception: return
    muts.append((f"{fn_of(node)}:{node.lineno} {desc}", code))
for n in nodes:
    if isinstance(n, ast.Compare):
        for i, op in enumerate(n.ops):
            if type(op) in SWAP: emit(f"cmp {type(op).__name__}->{SWAP[type(op)].__name__}", n, lambda t, i=i, op=op: t.ops.__setitem__(i, SWAP[type(op)]()))
    elif isinstance(n, ast.BoolOp):
        emit(f"bool {type(n.op).__name__} flipped", n, lambda t: setattr(t, "op", ast.Or() if isinstance(t.op, ast.And) else ast.And()))
    elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        emit("not removed", n, lambda t: setattr(t, "op", ast.UAdd()) if False else t.__dict__.update(copy.deepcopy(ast.Call(func=ast.Name("bool", ast.Load()), args=[t.operand], keywords=[]).__dict__)) or setattr(t, "__class__", ast.Call))
    elif isinstance(n, ast.Constant) and type(n.value) is int and fn_of(n) != "<module>" or (isinstance(n, ast.Constant) and type(n.value) is int and n.lineno == 20):
        emit(f"int {n.value}->{n.value + 1}", n, lambda t: setattr(t, "value", t.value + 1))
        emit(f"int {n.value}->{n.value - 1}", n, lambda t: setattr(t, "value", t.value - 1))
    elif isinstance(n, ast.Constant) and n.value in STR and fn_of(n) in ("start", "book", "inspect", "report"):
        emit(f"str {n.value!r}->{STR[n.value]!r}", n, lambda t: setattr(t, "value", STR[t.value]))
    elif isinstance(n, (ast.Expr, ast.AugAssign)) and fn_of(n) != "<module>" and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)):
        emit(f"stmt deleted: {ast.unparse(n)[:50]}", n, lambda t: (t.__dict__.clear(), t.__dict__.update(ast.Pass().__dict__), setattr(t, "__class__", ast.Pass)))
work = Path(tempfile.mkdtemp(prefix="mut_", dir=SCRATCH)); shutil.copy(TEST, work / "test_crash_lab.py")
def run_suite(code):
    (work / "__init__.py").write_text(code)
    p = subprocess.run([sys.executable, "-B", "-m", "unittest", "test_crash_lab", "-q"], cwd=work, capture_output=True, text=True, timeout=60)
    return p.returncode
assert run_suite(ast.unparse(tree)) == 0, "baseline (unparsed original) must pass"
killed = []; survived = []
for desc, code in muts:
    if code == ast.unparse(tree): continue
    try: rc = run_suite(code)
    except subprocess.TimeoutExpired: rc = 99
    (killed if rc else survived).append(desc)
R.note(f"mutants: {len(killed) + len(survived)} killed: {len(killed)} survived: {len(survived)}")
for s in survived: R.note("  SURVIVED", s)
json.dump({"killed": killed, "survived": survived}, open(AUDIT / "evidence/mutation_results.json", "w"), indent=1)
by_fn = {}
for d in killed + survived:
    f = d.split(":")[0]; by_fn.setdefault(f, [0, 0]); by_fn[f][0 if d in killed else 1] += 1
R.note("by function [killed, survived]:", by_fn)
score = len(killed) / (len(killed) + len(survived))
R.check("L5-MUT-score", L, "mutation", f"repo unit suite (9 tests) vs {len(killed) + len(survived)} AST mutants of __init__.py @9a712f9", "mutation score >= 90% for a tool whose product is a verdict; every verdict-logic mutant killed", f"score {score:.0%} ({len(killed)} killed, {len(survived)} survived); by function [killed, survived]: {by_fn}", score >= 0.9, defect="CRASH-AUD-009")
insp = [s for s in survived if s.startswith("inspect:")]
R.check("L5-MUT-oracle", L, "mutation", "surviving mutants inside inspect() (the oracle)", "0", f"{len(insp)}: {insp}", not insp, defect="CRASH-AUD-009")
R.close()
