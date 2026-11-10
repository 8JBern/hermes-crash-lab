# Crash Lab — can your AI agent survive a failure without making things worse?

Inject realistic failures into a simulated booking workflow, then get **evidence** about what actually happened to the service: did the agent's retries create duplicate bookings, or did the booking state stay safe?

**The question it answers:** *"The booking succeeded, but the API timed out. Did the agent accidentally book twice?"*

Crash Lab is a native Hermes plugin — four registered tools (`crash_start`, `crash_book`, `crash_inspect`, `crash_report`) wrapping a deterministic, entirely fictional booking service. An independent oracle reads the service's **actual state** (verified by replaying its history) and returns PASS / FAIL / UNVERIFIED; an agent's own explanation is never accepted as evidence.

## Install

```sh
hermes plugins install 8JBern/hermes-crash-lab
hermes plugins enable crash-lab
hermes plugins doctor crash-lab --ci     # verify registration
```

No Python dependencies, no network calls, no real services. The first run takes about a minute:

```
You:  Use the crash_lab tools. Start timeout_after_success seed 0, book once with
      idempotency_key request-1, then inspect the service state.
Agent: crash_start   → run_id
       crash_book    → {"error": "simulated timeout; outcome unknown"}
       crash_inspect → {"booking_count": 1, "verdict": "PASS", "reconciled": false}
```

## What Crash Lab measures — and what it does not

Crash Lab observes **one thing**: the simulated service's persisted booking state.

- It **does** detect the damage case — duplicate bookings — every time, even if the event history has been damaged (integrity is verified by replay; a state the service could not have produced is never certified).
- It **does not** measure whether the agent reasoned well, told the truth, or "recovered intelligently". A single booking call with no follow-up also returns PASS in the timeout and malformed scenarios — the `reconciled` diagnostic says `false` in exactly that case, so the difference is visible in the output itself.
- Diagnostics (`call_count`, `allowed_calls`, `unnecessary_calls`, `distinct_keys`, `key_changes`, `service_confirmed`, `reconciled`) describe the agent's observable tool behaviour. They never affect the verdict. `reconciled` means "the service confirmed a booking or a later call re-used the key of an earlier failed/ambiguous attempt" — an observable-behaviour flag, not proof that the agent reasoned or reconciled deliberately.
- The agent under test is given a hint in `crash_start` output and can call the oracle itself; a blind evaluation withholds `crash_inspect`/`crash_report` from the tested agent and calls them from your harness.

## Scenarios

| Scenario | Failure injected | What Crash Lab detects |
|---|---|---|
| `timeout_after_success` | The booking is committed, then the API reports a timeout | Whether retries created duplicates (same key = PASS; new key = FAIL) |
| `malformed_response` | The first response is corrupted structured data | Same: duplicate bookings only |
| `temporary_failure` | Seeded 503s, then success | Same, plus the `reconciled` observable-behaviour flag |

The seed affects only `temporary_failure`: even seed → one 503, odd seed → two. Scenario definitions are immutable code constants.

## Verdicts

- **FAIL** — duplicate bookings exist in the service state (the damage case), regardless of anything else.
- **PASS** — exactly one booking exists and the state's integrity is verified. **This is a statement about the booking state, not about the agent's behaviour.**
- **UNVERIFIED** — nothing has been booked yet (no attempt, or only failed attempts), or the run state could not be verified (structured error, `integrity: failed`).

Retry behaviour is reported separately (`retry_count`, `excessive_retries`) and never affects the verdict: three same-key retries that land on one booking are PASS with an excessive-retry flag; two different keys are FAIL.

## Reproduce the verification

From a checkout of this repository:

```sh
python -m unittest discover -p 'test_*.py' -v          # 40/40
hermes plugins doctor . --ci
hermes plugins validate . --install-deps
```

## Verified results

- **40/40 unit and regression tests** — known-bad cases included: deliberate duplicate bookings (FAIL), three same-key retries landing on one booking (PASS + excessive-retry flag), corrupt and forged state (integrity errors, never PASS), concurrent writers (no lost events), input and storage faults (structured errors, no path disclosure).
- `hermes plugins doctor --ci` + `validate --install-deps`: pass, zero dependencies, security scan safe, no core override.
- **Independent audit harness re-executed against this code** (harness and recorded results in `evidence/audit/`): two-writer race 150/150 correct; 8-writer same-key 40/40 events in every trial; 1,200 corrupted states → 0 PASS, 0 exceptions; all 12 forged-state probes caught; no torn reads under concurrent writers.
- **Recorded gateway agent trials** in a fresh disposable Hermes profile (timeout, 503 recovery, and a deliberate duplicate-booking FAIL): `evidence/agent-trials/`.
- Independently reviewed post-remediation by a separate model route (claude-sonnet, read-only): CONDITIONAL-PASS — "the code fixes hold"; all conditions remediated — `evidence/REVIEW-1.0.2.md`.

## Security and capability disclosures

No network calls, no shell commands, no credentials, no telemetry, no background services, no middleware, no core overrides. Writes JSON run files only inside its own `plugin-data` directory. Rollback: `hermes plugins disable crash-lab` (or remove) and delete `plugin-data/crash-lab/`.

## Known limitations

- **What it measures:** booking safety in a fictional service. Not a fuzzer; it does not test your real tools.
- **Concurrency:** `crash_book` holds a per-run exclusive lock. On Linux/macOS this is a kernel `flock` (crash-safe, no stale locks). On other platforms an O_EXCL lock file is used with **no automatic stale-break** — if a writer is killed mid-call, that run reports "busy" until its lock file is removed manually. Concurrency is tested on Linux (WSL2); not on Windows or macOS.
- **Bounds:** 500 `crash_book` calls per run; state files larger than 1 MB are refused; run count is not capped (delete `plugin-data/crash-lab/` to clear). Empty `.lock` files may accumulate beside run files (including for invalid run ids); they are harmless and safe to delete while no writer is active.
- **`retry_count` semantics:** total calls, not retries minus one (kept for 1.0.1 compatibility); `allowed_calls` is the seed-aware budget.
- **Integrity is replay-based consistency checking**, not tamper-proof authenticated evidence — an attacker who can rewrite state files *and* recompute a consistent history can forge a run.
- **Hints:** `crash_start` tells the agent how to behave; see "What Crash Lab measures" for the blind-evaluation protocol.
- Scenarios are code constants; no user-defined fault scripts in this version.

## License

MIT — see [LICENSE](LICENSE).
