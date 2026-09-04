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
