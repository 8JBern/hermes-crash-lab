# Independent audit harness — re-executed against the 1.0.2 code (2026-11-10)

`harness/` is the audit's own test harness (stdlib only, unmodified). `results_*.jsonl`
and `*.log` are the recorded outcomes of re-executing it against the 1.0.2 release code
(paths in the logs are scratch paths; the plugin code loaded is this repository's
`__init__.py` at the release commit).

Key outcomes (see logs for full detail):
- L4 race: two-writer distinct-keys 150/150 correct; 8-writer same-key 40/40 events
  every trial; 6-writer distinct-keys 0 under-counts; concurrent readers 0 torn reads.
- L4 persistence: 12/12 forged-state probes refused (integrity errors); L5 corruption
  fuzz 1,200 states -> 0 PASS, 0 exceptions.
- Residual FAILs in the logs are documented in the release notes (RELEASE notes in the
  project workspace) and fall into: version-pinned harness expectations (import set,
  .lock-file footprint, DOS thresholds beyond the implemented 500-call cap), legacy
  `retry_count` semantics retained from 1.0.1, deferred roadmap items (run sealing,
  blind-evaluation hints, agent-claim observability), and checks that demonstrate the
  original 1.0.0 maintainer defect (expected to FAIL at that revision).
