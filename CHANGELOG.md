# Changelog

All notable changes to Research Development Harness are recorded here.
This project follows semantic versioning for `runtime_version`,
`bundle_version` and `record_schema_version` independently (SPEC 59).

## [Unreleased]

### Added
- Phase 0 — distribution repository scaffold, `bin/rh` launcher, command
  runner abstraction (`SubprocessRunner`, `FakeRunner`, `RecordingRunner`).
- Phase 1 — repository discovery, Git context, manifest/config parsing,
  record markers and (de)serialization, derived state model, managed blocks,
  `rh doctor`.
- Phase 2 — `rh adopt` / `rh upgrade` overlay installation with an
  allow-listed write area, install inventory and conflict detection.
- Phase 3 — `gh` adapter with failure classification, retry, pagination and
  idempotent record posting; outbox for offline operation.
- Phase 4 — `rh issue create`, `rh work start|link`, `rh record
  checkpoint|decision|result|gate`, `rh context`, `rh status`, `rh resume`,
  `rh ready`, `rh sync`, `rh pr update`, `rh audit`.
- Phase 5 — canonical workflows and policies in `bundle/`, thin Claude and
  Codex project skills generated into `.claude/skills/` and `.agents/skills/`.
- Acceptance scenarios from SPEC 64 exercised end to end: existing-project
  migration (audit → baseline → adopt the in-flight branch without renaming
  it), the Knowledge Gate blocking and then releasing `READY_TO_MERGE`, and
  self-containment of an adopted repository including a relocated copy.

### Fixed during implementation
- `READY_TO_MERGE` is reachable only from a declared `--phase review`
  checkpoint; previously gate-free low-risk work reached it the moment work
  started.
- Branch links survive across processes (`hash()` → SHA-256 digest).
- A transient network failure during repository resolution no longer caches a
  negative result and queues records that should have been retried.
- Record timestamps carry milliseconds and ordering is stable on ties, so a
  deviation gate can no longer outrank the gate that closed it.
- Repository slug detection falls back to `gh` for remotes a URL parser
  cannot read (ssh aliases, `insteadOf` rewrites, enterprise hosts).
