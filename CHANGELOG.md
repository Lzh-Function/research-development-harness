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

- `rh log` — cross-issue research history. Filters by record kind, gate,
  outcome, decision status, issue, date range and free text; `--full` prints
  record bodies; works offline from the local cache. Answers "what has this
  project learned", which `rh status` and `rh resume` (single work unit)
  could not.

- `rh status` reports the next command for the current derived state.
- `rh ready` applies two structural checks to evidence-required work: the PR
  body must say what the work does not establish, and every Result Record must
  carry at least one filled Provenance field. Configurable under `[ready]`.
- Research Questions are first-class: `rh rq create|list|show`, `rh log --rq`.
- `rh pr create` opens the Draft PR once a new branch has its first commit.
- `rh issue close` implements SPEC 24 close semantics: experiments and
  analyses need a Result Record and a passed evidence gate first, because a
  merged PR is not a scientific conclusion. Closing is reversible; RDH never
  deletes an Issue.

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

### Found only by running against real GitHub
- GitHub refuses to open a pull request on a branch with no commits — exactly
  the state `rh work start` leaves a new branch in. It now reports that and
  defers to `rh pr create`; the fake `gh` reproduces the refusal.
- `gh repo view` rejects `--repo` (the repository is positional), so
  `default_branch()` always failed and silently returned `None`.

### Found only by writing the documentation
- `VALIDATING` was returned whenever the evidence gate was pending, which is
  true from the moment evidence-required work starts. `IN_PROGRESS` was
  therefore unreachable for every experiment, and `rh status` announced
  "evidence is being gathered" before the experiment existed. The phase the
  agent declares now drives it.
- `rh status` suggested `rh record result` after the evidence gate had already
  passed; it now points at the review checkpoint.

### Removed
- `issue_edit_body` and `pr_comment` wrappers. Rewriting a Work Issue body
  erases historical intent (SPEC 29) and PR comments are not a record store
  (SPEC 25); providing the wrappers only made those mistakes easy to reach.
