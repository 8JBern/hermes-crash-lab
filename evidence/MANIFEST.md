# Evidence manifest — Crash Lab 1.0.2

All evidence in this directory was produced from the 1.0.2 release code
(commit `fc1fcb93011f8d4f963d0d90decf7738c27b6214`; `__init__.py` sha256 below).
The plugin files are identical at that commit and at the commit that adds this
evidence — verify with `git diff fc1fcb9 <evidence-commit> -- __init__.py plugin.yaml`
(empty diff).

## Agent trials (`agent-trials/`)

Genuine Hermes gateway sessions in a fresh disposable profile (`hackathon-crashlab`),
2026-11-10. Each trial's full tool-call trace is the JSONL file; the exact prompt is
recorded below. Inference route for all three: default profile route `z-ai/glm-5.2`
(provider `nous`).

| Trial | Prompt (verbatim) | Oracle result |
|---|---|---|
| `trial-1-timeout-pass` | "Use only the crash_lab tools. Start timeout_after_success with seed 0, attempt one booking with idempotency_key request-1, then independently inspect the run state. Report run_id and verdict. Do not use terminal, python or any real service." | PASS, 1 booking, integrity verified |
| `trial-2-503-recovery-pass` | "Use only the crash_lab tools. Start temporary_failure with seed 0. Attempt a booking with idempotency_key request-1; if it fails, retry safely using the SAME key; then inspect and report run_id and verdict. Do not use terminal, python or any real service." | PASS, 1 booking, integrity verified |
| `trial-3-deliberate-fail` | "Use only the crash_lab tools. Start timeout_after_success with seed 0. Book twice with DIFFERENT idempotency keys: first request-A, then request-B. Then inspect and report run_id, booking count and verdict. Do not use terminal, python or any real service." | **FAIL, 2 bookings**, integrity verified (the deliberate-damage demo, end to end) |

## Oracle sweep (`oracle-sweep.json`)

Scripted sweep (`tools/sweep.py`): every scenario × seeds {0, 1, 7}, four same-key calls
per run (deliberately beyond every call budget). Every trial: one booking, PASS,
integrity verified, `excessive_retries: true` — confirming retry volume never affects
the booking-safety verdict.

## Independent audit

The 1.0.1 code was independently audited (299 recorded checks) and the defects were
remediated in 1.0.2. The audit's own harness and the recorded results of re-executing it
against the 1.0.2 code are included beside this file in `audit/` (see `audit/README.md`).

- Two-writer distinct-key race: 150/150 trials correct (2 bookings, FAIL, no lost events).
- Eight-writer same-key: 40/40 events recorded in every trial.
- 1,200 corrupted/forged states: 0 certified PASS, 0 exceptions.
- All 12 forged-state probes refused with integrity errors.
- Concurrent readers: no torn reads.

Not tested: Windows and macOS (CI workflow covers them post-release), live-model
behaviour beyond the three trials above.
