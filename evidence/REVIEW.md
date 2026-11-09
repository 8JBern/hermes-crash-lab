# Independent acceptance review — Crash Lab 1.0.0-rc.1

**Reviewer:** independent subagent (different model route from the implementer), read-only, 2026-11-09.
**Full trace:** `/home/barry/.hermes/cache/delegation/live/deleg_809f5e36/task-0.log`

## Verdict: CONDITIONAL-PASS

All core functional and safety claims verified against source and live execution by the reviewer (6/6 tests re-run, doctor + validate re-run, known-bad oracle probe confirmed FAIL not vacuous, security surface confirmed clean, seed determinism confirmed across repeats, report export confirmed).

## Findings and remediation

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | Evidence gap: 4 of 5 claimed agent-trial traces retained | Medium | **Fixed** — timeout-1.jsonl re-recorded (fresh trial, PASS, 1 booking); 5 traces on disk; README wording amended to note the original unsaved trial (run `be726e6c`, state file retained) |
| F2 | Read-modify-write race on concurrent writers to one run_id | Medium | **Disclosed limitation** (README "single-writer, one session per run"); fcntl lock rejected — would break Windows support |
| F3 | Seed claim overstated (seed only controls 503 count parity) | Low | **Fixed** — README wording corrected |
| F4 | `doctor crash-lab` by bare name fails from a bare checkout | Low | **Fixed** — reproduce block now uses `./crash-lab` |
| F5 | `.tmp` litter if process dies mid-save | Low | **Fixed** — `_save` cleans up its tmp file on any exception |
| F6 | demo.py writes outside plugin-data | Info | Accepted — evidence-generation script, not plugin runtime |

Reviewer's note: "No issues blocking release beyond F1, which is an evidence-completeness fix, not a code defect."
