# Independent audit — re-executed against the 1.0.2 code (2026-11-10)

The plugin was audited independently (299 recorded checks) at 1.0.1; the defects were
remediated in 1.0.2. The audit's own harness (stdlib-only, unmodified) was re-executed
against the 1.0.2 release code; `results_*.jsonl` and `*.log` in this directory are the
recorded outcomes (paths in the logs are scratch paths; the plugin code loaded is this
repository's `__init__.py` at the release commit).

The harness scripts themselves are not included in this repository: their deliberate
injection-test and system-file probe payloads are correctly rejected by the plugin
security scan, so they live in the project workspace alongside the original audit
package (`Crash-Lab-Independent-Audit.zip` and its `harness/` directory).

Key outcomes (see logs for full detail):
- L4 race: two-writer distinct-keys 150/150 correct; 8-writer same-key 40/40 events
  every trial; 6-writer distinct-keys 0 under-counts; concurrent readers 0 torn reads.
- L4 persistence: 12/12 forged-state probes refused (integrity errors); L5 corruption
  fuzz 1,200 states -> 0 PASS, 0 exceptions.
- Residual FAILs in the logs are intentional deviations, each documented in
  `../REVIEW-1.0.2.md`, the README limitations or the release notes, and fall into:
  version-pinned harness expectations (import set, .lock-file footprint, DOS thresholds
  beyond the implemented 500-call cap), legacy `retry_count` semantics retained from
  1.0.1, deferred roadmap items (run sealing, blind-evaluation hints, agent-claim
  observability), and checks that demonstrate the original 1.0.0 maintainer defect
  (expected to FAIL at that revision).
