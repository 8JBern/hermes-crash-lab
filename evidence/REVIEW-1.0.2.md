# Independent review — Crash Lab 1.0.2 (release code fc1fcb9)

**Reviewer:** claude-sonnet (separate model route from the implementer), read-only
one-shot review session, 2026-11-10. Confirmed no files modified; all probes ran in a
scratch directory.

**Checks the reviewer re-ran:** 40/40 unit tests OK; `hermes plugins doctor . --ci`
pass; `hermes plugins validate . --install-deps` "Validation passed."; evidence
manifest sha256 match and empty code diff between the release and evidence commits.

## Verdict: CONDITIONAL-PASS

"The code fixes hold. The conditions are documentation and evidence claims that the repo
does not support."

Confirmed fixed: AUD-001 (PASS requires exactly one booking in every branch), AUD-002/
007/017 (no state reaches PASS without replay verification; run_id match; symlink
refusal), AUD-004 (flock double-entry analysis: sound; no TOCTOU in the O_EXCL fallback;
busy-timeout leaks nothing), AUD-003/014 (no exception or path escaped any handler under
the reviewer's malformed-argument probes).

## Reviewer findings and remediation status

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | README's "independently reviewed" line referenced the superseded 1.0.0-rc.1 review | Medium | **Fixed** — this file now records the 1.0.2 review; README cites it |
| 2 | Audit-harness outcome numbers (150/150, 1,200 states, 12 probes) not reproducible from the repo | Medium | **Fixed** — harness and recorded results now in `audit/` |
| 3 | Scenarios table implied `reconciled` proves the agent reconciled | Medium-Low | **Fixed** — README wording corrected: `reconciled` = "service confirmed or same-key retry after a failure", an observable-behaviour flag |
| 4 | CHANGELOG test-count arithmetic (29+6=35, actual 25+6+9=40) | Low | **Fixed** |
| 5 | Lock files created for non-existent run_ids; never swept | Low | **Accepted residual** — documented in README limitations; harmless (empty files in plugin-data) |
| 6 | Replay `==` accepts `True`/`1.0` for the event `call` field; `_guard` catches only OSError | Low | **Accepted residual** — no effect on booking facts; documented |
| 7 | CI matrix not yet run on Windows/macOS | Info | **Disclosed** in README and release notes |

Verdict quoted verbatim from the review session; findings 1–4 were remediated
immediately after the review (documentation and evidence only — no plugin code changed;
`git diff` of `__init__.py`/`plugin.yaml` across the remediation is empty).
