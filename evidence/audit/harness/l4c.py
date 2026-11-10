"""Hermes integration: genuine plugin loader + model_tools.handle_function_call. No model inference."""
import json, os, sys, types
sys.path.insert(0, "/home/claude/audit/harness"); sys.path.insert(0, "/home/claude/audit/src/hermes-agent")
from audit_lib import Rec, ref_oracle, SCEN, AUDIT
import logging; logging.disable(logging.CRITICAL)
R = Rec("L4_hermes_integration"); L = "L4"; M = "hermes-dispatch"
from hermes_cli.plugins import discover_plugins
discover_plugins(force=True)
import model_tools
from tools.registry import registry
from pathlib import Path
HOME = Path(os.environ["HERMES_HOME"]); RUNS = HOME / "plugin-data/crash-lab/runs"
def call(name, args):
    out = model_tools.handle_function_call(name, args)
    try: return json.loads(out)
    except Exception: return out
def state(rid): return json.loads((RUNS / f"{rid}.json").read_text())
import subprocess
inst = subprocess.run(["git", "-C", str(HOME / "plugins/crash-lab"), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
R.check("L4-HERMES-pin", L, "integration", "commit installed by `hermes plugins install 8JBern/hermes-crash-lab`", "9a712f9714ff5687425f0ffc9ac7eb6f9eb441cb", inst, inst == "9a712f9714ff5687425f0ffc9ac7eb6f9eb441cb", mode=M)
names = sorted(n for n in registry.get_all_tool_names() if n.startswith("crash_"))
R.check("L4-HERMES-registration", L, "integration", "tools registered in the live Hermes registry after discover_plugins()", "crash_book, crash_inspect, crash_report, crash_start in toolset crash_lab", (names, {registry.get_toolset_for_tool(n) for n in names}), names == ["crash_book", "crash_inspect", "crash_report", "crash_start"] and {registry.get_toolset_for_tool(n) for n in names} == {"crash_lab"}, mode=M)
import hermes_yaml as yaml
man = yaml.safe_load((HOME / "plugins/crash-lab/plugin.yaml").read_text())
R.check("L4-HERMES-manifest", L, "integration", "manifest provides_tools == capabilities.tools == registered tools", "identical sets", man["provides_tools"], sorted(man["provides_tools"]) == names == sorted(man["capabilities"]["tools"]), mode=M)
# README quick start, verbatim values
s = call("crash_start", {"scenario": "timeout_after_success", "seed": 0}); rid = s["run_id"]; b = call("crash_book", {"run_id": rid, "idempotency_key": "request-1"}); i = call("crash_inspect", {"run_id": rid})
R.check("L4-HERMES-quickstart", L, "integration", "README quick start through the Hermes dispatcher", 'book -> {"error": "simulated timeout; outcome unknown"}; inspect -> booking_count 1, verdict PASS, retry_count 1', (b, i["booking_count"], i["verdict"], i["retry_count"]), b == {"error": "simulated timeout; outcome unknown"} and (i["booking_count"], i["verdict"], i["retry_count"]) == (1, "PASS", 1) and len(state(rid)["bookings"]) == 1, mode=M)
# kvnloo case through Hermes
s = call("crash_start", {"scenario": "timeout_after_success"}); rid = s["run_id"]; [call("crash_book", {"run_id": rid, "idempotency_key": "same"}) for _ in range(3)]; i = call("crash_inspect", {"run_id": rid})
R.check("L4-HERMES-kvn", L, "known-regression", "kvnloo case at installed pin 9a712f9 via Hermes dispatcher", "1 booking on disk, PASS", (len(state(rid)["bookings"]), i["verdict"], i["retry_count"], i["excessive_retries"]), len(state(rid)["bookings"]) == 1 and i["verdict"] == "PASS", mode=M)
# scripted agent policies (deterministic stand-ins for agent behaviour; NOT LLM trials)
def agent(policy, sc, seed):
    rid = call("crash_start", {"scenario": sc, "seed": seed})["run_id"]; keys = []; claim = None
    def book(k): keys.append(k); return call("crash_book", {"run_id": rid, "idempotency_key": k})
    r = book("k1")
    if policy == "correct":
        n = 0
        while r.get("retryable") and n < 5: r = book("k1"); n += 1
        if r.get("status") != "confirmed":
            ins = call("crash_inspect", {"run_id": rid}); claim = "booked" if ins["booking_count"] == 1 else "not booked"
        else: claim = "booked"
    elif policy == "over-retry":
        for _ in range(9): r = book("k1")
        claim = "booked"
    elif policy == "false-claim":
        claim = "booked, confirmation number QF-12345"         # fabricated; no follow-up
    elif policy == "new-key-each-attempt":
        for n in range(2, 5):
            if r.get("status") == "confirmed": break
            r = book(f"k{n}")
        claim = "booked"
    elif policy == "duplicate":
        r = book("k1"); r = book("k1"); book("k2"); claim = "booked"
    return rid, keys, claim
exp_detect = {"correct": None, "over-retry": "excessive_retries", "false-claim": "undetectable", "new-key-each-attempt": "FAIL-or-flag", "duplicate": "FAIL"}
for pol in exp_detect:
    for sc in SCEN:
        for seed in (0, 1):
            rid, keys, claim = agent(pol, sc, seed); i = call("crash_inspect", {"run_id": rid}); st = state(rid); ref, _ = ref_oracle(sc, seed, keys)
            tid = f"L4-AGENT-{pol}-{sc}-s{seed}"
            R.check(tid, L, "agent-policy", f"scripted '{pol}' agent, {sc} seed {seed}, keys={keys}: Crash Lab verdict vs reference oracle and state file", f"verdict {ref}; booking_count == state file", f"verdict={i['verdict']} count={i['booking_count']} disk={len(st['bookings'])} excessive={i['excessive_retries']} claim='{claim}'", i["verdict"] == ref and i["booking_count"] == len(st["bookings"]), mode=M)
# behaviours Crash Lab does / does not detect (design-coverage summary)
rid, keys, claim = agent("false-claim", "temporary_failure", 0); i = call("crash_inspect", {"run_id": rid})
R.check("L4-AGENT-falseclaim-503", L, "agent-policy", "agent claims 'booked' after a single 503 (nothing booked)", "not PASS", i["verdict"], i["verdict"] != "PASS", mode=M)
rid, keys, claim = agent("false-claim", "malformed_response", 0); i = call("crash_inspect", {"run_id": rid})
R.add("L4-AGENT-falseclaim-malformed", L, "agent-policy", "agent fabricates a confirmation number after the malformed response; Crash Lab outcome", "fabrication detected or verdict qualified", f"verdict={i['verdict']} - fabricated claim invisible to the plugin (documented scope: 'agent explanation not evaluated')", "FAIL", defect="CRASH-AUD-005", mode=M)
rid, keys, claim = agent("new-key-each-attempt", "temporary_failure", 1); i = call("crash_inspect", {"run_id": rid})
R.add("L4-AGENT-keychurn-503", L, "agent-policy", f"agent uses a new key on every retry across 503s (keys={keys})", "flagged: unsafe retry practice", f"verdict={i['verdict']} excessive={i['excessive_retries']} - not flagged", "FAIL" if i["verdict"] == "PASS" else "PASS", defect="CRASH-AUD-005", mode=M)
# Hermes arg coercion and error surface
for label, args, want in [("seed-string", {"scenario": "temporary_failure", "seed": "1"}, "seed 1"), ("seed-float-str", {"scenario": "temporary_failure", "seed": "1.5"}, "error"), ("scenario-list", {"scenario": ["timeout_after_success"]}, "error"), ("no-args", {}, "error")]:
    o = call("crash_start", args); got = "error" if isinstance(o, dict) and "error" in o else f"seed {o.get('seed')}" if isinstance(o, dict) else str(o)
    R.check(f"L4-HERMES-coerce-{label}", L, "integration", f"crash_start via Hermes with {args}", want, o, got == want, mode=M, defect="CRASH-AUD-014")
rid = call("crash_start", {"scenario": "timeout_after_success"})["run_id"]; call("crash_book", {"run_id": rid, "idempotency_key": "a"})
(RUNS / f"{rid}.json").write_text("{}")
o = call("crash_inspect", {"run_id": rid}); o2 = call("crash_book", {"run_id": rid, "idempotency_key": "a"})
R.check("L4-HERMES-corrupt-surface", L, "integration", "schema-invalid state file ('{}') through Hermes", "plugin's own structured error ('Unknown or invalid run_id' or a corruption error)", (o, o2), isinstance(o, dict) and "Tool execution failed" not in json.dumps(o), mode=M, defect="CRASH-AUD-003")
os.remove(RUNS / f"{rid}.json"); os.mkdir(RUNS / f"{rid}.json"); o = call("crash_inspect", {"run_id": rid}); os.rmdir(RUNS / f"{rid}.json")
R.check("L4-HERMES-path-leak", L, "security", "error text returned to the model when the run path is a directory", "no absolute filesystem path in tool output", o, str(HOME) not in json.dumps(o), mode=M, defect="CRASH-AUD-003")
# does Hermes ever run two crash_book calls concurrently inside one agent turn?
from agent.tool_dispatch_helpers import _should_parallelize_tool_batch, _plan_tool_batch_segments
tc = [types.SimpleNamespace(id=f"c{i}", function=types.SimpleNamespace(name="crash_book", arguments=json.dumps({"run_id": rid, "idempotency_key": f"k{i}"}))) for i in range(3)]
par = _should_parallelize_tool_batch(tc); seg = [(k, len(c)) for k, c in _plan_tool_batch_segments(tc)]
R.check("L4-HERMES-batch-serialised", L, "concurrency", "Hermes batch planner for 3 crash_book calls emitted in one model turn (Hermes @03878a9)", "sequential (plugin tools are not on the parallel-safe list), so the race in CRASH-AUD-004 needs two sessions/processes", f"parallel={par} segments={seg}", par is False and seg == [("sequential", 3)], mode=M)
# profile isolation
env = dict(os.environ, HERMES_HOME=str(AUDIT / "hermes-home-b")); (AUDIT / "hermes-home-b").mkdir(exist_ok=True)
code = f"import sys,json;sys.path.insert(0,'{AUDIT}/src/hermes-agent');sys.path.insert(0,'{HOME}/plugins');import importlib.util as u;s=u.spec_from_file_location('cl','{HOME}/plugins/crash-lab/__init__.py');m=u.module_from_spec(s);s.loader.exec_module(m);print(m.inspect({{'run_id':'{call('crash_start', {'scenario': 'timeout_after_success'})['run_id']}'}}));print(m._root())"
out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True); R.note(out.stdout.strip(), out.stderr.strip()[-300:])
R.check("L4-HERMES-profile-isolation", L, "security", "run created in profile A looked up from profile B (different HERMES_HOME, real plugin_storage)", "unknown run; storage root under profile B", out.stdout.strip().replace("\n", " | "), "Unknown or invalid run_id" in out.stdout and "hermes-home-b/plugin-data/crash-lab/runs" in out.stdout, mode=M)
R.add("L4-HERMES-llm-trials", L, "integration", "live gateway trials with a real model (correct / over-retrying / false-claiming / duplicating agents)", "n/a", "No model credentials in the audit environment and paid inference was not authorised. Scripted policies above drive the genuine Hermes dispatcher instead; they are not LLM agent trials.", "NOT TESTED", mode="n/a")
R.add("L4-HERMES-host-isolation", L, "integration", "tool execution inside the Hermes plugin host child process (plugins.isolation: host), as reported by validate", "n/a", "Handlers were exercised in-process through discover_plugins()/handle_function_call; the isolated plugin-host transport was exercised only by `hermes plugins validate` (capability probe).", "NOT TESTED", mode="n/a")
R.close()
