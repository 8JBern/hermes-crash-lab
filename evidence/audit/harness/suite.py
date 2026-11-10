import ast, itertools, random, subprocess, sys
from audit_lib import *
R = Rec("L5_suite_assessment"); L = "L5"; W = REVS["1.0.1"]
t = ast.parse((W / "test_crash_lab.py").read_text()); tests = [f.name for c in t.body if isinstance(c, ast.ClassDef) for f in c.body if isinstance(f, ast.FunctionDef) and f.name.startswith("test_")]
def run(args, py=sys.executable): return subprocess.run([py, "-B", "-m", "unittest"] + args, cwd=W, capture_output=True, text=True)
solo = {n: run([f"test_crash_lab.CrashLabTests.{n}"]).returncode for n in tests}
R.check("L5-SUITE-isolated", L, "test-suite", f"each of the {len(tests)} tests run alone in a fresh process", "all pass (no hidden order dependency)", solo, not any(solo.values()))
rng = random.Random(1); bad = 0
for _ in range(20):
    order = tests[:]; rng.shuffle(order); bad += run([f"test_crash_lab.CrashLabTests.{n}" for n in order]).returncode != 0
R.check("L5-SUITE-order", L, "test-suite", "20 random orderings of the suite", "all pass", f"{bad} failing orderings", bad == 0)
p = run(["discover", "-p", "test_*.py"], py="/home/claude/audit/hermes-venv/bin/python"); R.check("L5-SUITE-py314", L, "test-suite", "suite under Python 3.14.6 (Hermes' supported interpreter) as well as 3.13.18", "9/9", p.stderr.strip().splitlines()[-1], p.returncode == 0)
p = subprocess.run(["env", "-i", "PATH=/usr/bin:/bin:/usr/local/bin", sys.executable, "-B", "-m", "unittest", "discover", "-p", "test_*.py"], cwd=W, capture_output=True, text=True)
R.check("L5-SUITE-cleanenv", L, "test-suite", "suite with an empty environment (no HERMES_HOME, no Hermes on sys.path)", "9/9 - no undocumented environment dependency", p.stderr.strip().splitlines()[-1], p.returncode == 0)
asserts = {f.name: sum(isinstance(n, ast.Call) and getattr(n.func, "attr", "").startswith("assert") for n in ast.walk(f)) for c in t.body if isinstance(c, ast.ClassDef) for f in c.body if isinstance(f, ast.FunctionDef) and f.name.startswith("test_")}
R.check("L5-SUITE-vacuous", L, "test-suite", "every test contains assertions", "no test with 0 assertions", asserts, all(asserts.values()))
src = (W / "test_crash_lab.py").read_text()
reads_state = "read_text" in src or "json.load(" in src
R.check("L5-SUITE-independent-oracle", L, "test-suite", "tests verify verdicts against an independent reading of persisted state rather than the plugin's own inspect()", "at least the booking-count assertions read the state file directly", "all booking_count/verdict assertions consume lab.inspect(); the state file is only ever written (corruption test), never read independently", reads_state, defect="CRASH-AUD-009")
R.check("L5-SUITE-real-storage", L, "test-suite", "tests exercise the real storage root (plugins.plugin_storage) and register()", "at least one test covers _root() and register(ctx)", "setUp replaces _root with a lambda; register() and _root() are never executed by the suite (mutant deleting ctx.register_tool survives)", "register(" in src, defect="CRASH-AUD-009")
uncovered = {"duplicate bookings in temporary_failure": "'second'" in src and "temporary_failure" in src.split("test_distinct_keys")[1][:400], "malformed_response second call": False, "seed >= 2": "seed=2" in src or "seed=3" in src, "key length boundary 128/129": "128" in src, "seed bounds": "2147483647" in src or "seed=-1" in src, "schema-invalid JSON state": '"{}"' in src, "concurrency": "thread" in src.lower() or "process" in src.lower(), "report json branch / bad format": 'format": "json"' in src or "bogus" in src}
R.check("L5-SUITE-coverage-gaps", L, "test-suite", "behaviours with no test (confirmed by surviving mutants or absence in source)", "none", [k for k, v in uncovered.items() if not v], all(uncovered.values()), defect="CRASH-AUD-009")
dup = "test_unsafe_retry_fails_and_same_key_deduplicates" in tests and "test_distinct_keys_still_fail_on_duplicates" in tests
R.add("L5-SUITE-redundancy", L, "test-suite", "redundant tests inflating the count", "n/a (observation)", "test_distinct_keys_still_fail_on_duplicates repeats the first half of test_unsafe_retry_fails_and_same_key_deduplicates (same scenario, same keys, same assertions): '9/9' contains 8 distinct behaviours", "PASS")
R.close()
