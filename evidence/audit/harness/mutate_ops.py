import ast, copy
SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
STR = {"PASS": "FAIL", "FAIL": "PASS", "UNVERIFIED": "PASS", "confirmed": "pending", "temporary_failure": "x", "timeout_after_success": "x", "malformed_response": "x", "error": "err", "warning": "warn", "status": "state", "json": "x", "markdown": "x"}

def mutants(src):
    tree = ast.parse(src); nodes = list(ast.walk(tree)); muts = []
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
        elif isinstance(n, ast.Constant) and type(n.value) is int:
            emit(f"int {n.value}->{n.value + 1}", n, lambda t: setattr(t, "value", t.value + 1))
            emit(f"int {n.value}->{n.value - 1}", n, lambda t: setattr(t, "value", t.value - 1))
        elif isinstance(n, ast.Constant) and n.value in STR and fn_of(n) in ("start", "book", "inspect", "report"):
            emit(f"str {n.value!r}->{STR[n.value]!r}", n, lambda t: setattr(t, "value", STR[t.value]))
        elif isinstance(n, (ast.Expr, ast.AugAssign)) and fn_of(n) != "<module>" and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)):
            emit(f"stmt deleted: {ast.unparse(n)[:50]}", n, lambda t: (t.__dict__.clear(), t.__dict__.update(ast.Pass().__dict__), setattr(t, "__class__", ast.Pass)))
    base = ast.unparse(tree)
    return base, [(d, c) for d, c in muts if c != base]
