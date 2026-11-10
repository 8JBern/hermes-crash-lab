# Changelog

## 1.0.2 (2026-11-10)

Remediation release following an independent audit (299 recorded checks) and the
maintainer review on catalogue PR #151695.

### Fixed

- **False PASS with zero bookings** (audit CRASH-AUD-001): the verdict now requires
  exactly one booking in every scenario. `temporary_failure` no longer certifies a run
  whose booking list is empty. Duplicates are checked first and always FAIL.
- **Concurrent-writer race** (CRASH-AUD-004): `crash_book` now holds a per-run exclusive
  lock across the read-modify-write. Two writers can no longer silently discard each
  other's bookings and return an incorrect PASS. On Linux/macOS the lock is a kernel
  `flock` (crash-safe: released automatically if the owning process dies, no stale-lock
  handling and no lock-breaking race possible). On other platforms an O_EXCL lock file is
  used with no automatic stale-break — a killed writer leaves the run "busy" until its
  lock file is removed manually, which is the conservative failure mode. On lock timeout
  the caller receives a structured "run is busy" error — never a raced write.
- **State integrity** (CRASH-AUD-002/007/017): every read verifies the stored state —
  structure, types, scenario, seed, call counter — and replays the event history through
  the deterministic service, requiring exact equality. A state file that the service could
  not have produced (edited, damaged, cross-run mixups, symlinked) yields a structured
  `integrity: failed` error with `verdict: UNVERIFIED`, never a PASS and never an
  exception. The `run_id` inside the file must match the one requested.
- **Unhandled exceptions and path disclosure** (CRASH-AUD-003/014): all tool handlers are
  guarded. Malformed arguments, schema-invalid state and storage faults return
  structured errors; no filesystem path or internal detail leaves the plugin.
- **Loose input handling** (CRASH-AUD-011): blank/whitespace idempotency keys rejected;
  tool schemas now declare seed bounds, key length bounds and the run_id pattern;
  scenario and seed error messages split.

### Added

- Diagnostics that never affect the verdict: `call_count`, `allowed_calls` (seed-aware),
  `unnecessary_calls`, `distinct_keys`, `key_changes`, `service_confirmed`, plus
  `integrity: verified` on successful inspection.
- Hard bounds: 500 `crash_book` calls per run; 1 MB state-file read guard; stale
  `.tmp` sweep on `crash_start` and `crash_book`.
- `reconciled` diagnostic (with `service_confirmed` and the other diagnostics) making
  the "PASS for a single unreconciled call" fact visible in the output itself.
- 25 audit regression tests plus 6 remediation tests alongside the 9 original tests
  (40 total), including concurrency (no lost events under 2/6/8 writers), corruption
  fuzz, forged state, boundary and mutation-targeted cases.

### Documentation

- README now states precisely what Crash Lab measures (booking safety) and what it does
  not (agent reasoning, recovery intelligence, fabrication); seed semantics corrected;
  UNVERIFIED definition corrected; lock behaviour and platform caveats documented.

## 1.0.1 (2026-11-10)

- Verdict is service-state only; retries reported separately (`retry_count`,
  `excessive_retries`). Fixes the maintainer-reported false FAIL on repeated same-key
  retries (kvnloo, PR #151695).

## 1.0.0 (2026-11-09)

- Initial release: four tools, three seeded scenarios, independent state oracle,
  PASS/FAIL/UNVERIFIED verdicts, Markdown/JSON reports.
