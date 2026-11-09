# Crash Lab — fault-injection and recovery testing for AI agents (1.0.0)

Crash Lab manufactures the failure modes that break real agent workflows — a write that succeeds while the API reports a timeout, a malformed response, a transient 503 — then measures whether the agent recovers correctly, verified against the simulated service's actual state rather than its own explanation.

**The demo in one line:** *"The booking succeeded, but the API timed out. Will the agent accidentally book twice?"*

Native Hermes plugin: `crash_start`, `crash_book`, `crash_inspect`, `crash_report`. The simulated service is entirely fictional — no network, no real bookings, no accounts. State is profile-scoped via Hermes `plugin_data_dir` and inspected independently of the simulated API response. PASS/FAIL/UNVERIFIED verdicts come from the service-state oracle; an agent's prose is never accepted as evidence.

## Install

```sh
hermes plugins install 8JBern/hermes-crash-lab --ref <pinned-sha>   # or clone and copy
cp -r . ~/.hermes/plugins/crash-lab                                  # manual, from a checkout
hermes plugins enable crash-lab
hermes plugins doctor crash-lab --ci                                 # verify registration
hermes plugins validate ~/.hermes/plugins/crash-lab --install-deps
```

No Python dependencies. Zero declared capabilities beyond the four tools.

## Use

```
crash_start(scenario="timeout_after_success", seed=0)   → run_id
crash_book(run_id, idempotency_key="request-1")         → error: "simulated timeout; outcome unknown"
crash_inspect(run_id)                                   → booking_count: 1, verdict: "PASS"
crash_report(run_id, format="markdown")                 → exportable run report
```

Scenarios: `timeout_after_success` (write lands, response lost — did the agent re-book?), `malformed_response` (corrupted structured data — did it fabricate?), `temporary_failure` (seeded 503s — did it retry with the same key, and stop?). The seed controls the 503 retry count by parity (seed 0 → one failure, odd seed → two); scenario definitions are immutable code constants.

## Reproduce the verification

From a checkout of this repository:

```sh
python -m unittest discover -p 'test_*.py' -v          # 6/6
hermes plugins doctor . --ci                          # repo root is the plugin
hermes plugins validate . --install-deps
```

## Verified results

- Unit suite: **6/6** — including a known-bad FAIL case (retry with a new key creates a duplicate booking) and corrupt-state recovery, so a PASS cannot come from a vacuous checker.
- `hermes plugins doctor --ci` + `validate --install-deps`: pass, zero dependencies, security scan safe, no core override.
- **Five recorded gateway agent trials** in a fresh disposable Hermes profile: 3× timeout (no blind retry, one booking each), 1× malformed (no fabrication, PASS), 1× 503 (retried with the same key, two calls, one booking, PASS). **Zero duplicate bookings.** Full tool-call traces: `evidence/agent-trials/`.
- Independently reviewed (different model route, read-only): CONDITIONAL-PASS; all findings remediated — `evidence/REVIEW.md`.

## Security and capability disclosures

No network calls, no shell commands, no credentials, no telemetry, no background services, no middleware, no core overrides. Writes JSON run files only inside its own `plugin-data` directory. Rollback: `hermes plugins disable crash-lab` (or remove) and delete `plugin-data/crash-lab/`.

## Known limitations

- Verdicts certify **simulated service state only** — they do not evaluate the agent's reasoning or prose.
- Run state is single-writer: concurrent `crash_book` calls on the same `run_id` are not serialised. One session per run.
- The oracle knows the scenarios it ships; it is not a general fuzzer.
- Scenarios are code constants; no user-defined fault scripts in this version.

## License

MIT — see [LICENSE](LICENSE).
