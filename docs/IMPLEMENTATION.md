# Implementation Notes

Companion to [SPEC.md](SPEC.md), which remains authoritative. This file records
what the v0.1 implementation decided where the specification left room, and
where it deliberately differs.

## Module map

| Module | Responsibility |
|---|---|
| `proc.py` | command runner abstraction; every external call is an argv vector, `shell=False` |
| `errors.py` | exception hierarchy carrying stable CLI exit codes |
| `git.py` | Git reads, the small allowed set of Git writes, and `assert_safe_git` |
| `github.py` | `gh` adapter: failure classification, retry, pagination, idempotent records |
| `records.py` | markers, record (de)serialization, section extraction |
| `state.py` | branch↔work links, gate evaluation, derived state |
| `config.py` | `manifest.toml` / `config.toml`, gate thresholds |
| `managed.py` | AGENTS.md / CLAUDE.md managed blocks |
| `context.py` | session assembly, record cache, `rh context` payload |
| `adopt.py` / `upgrade.py` | overlay installation with an allow-listed write area |
| `outbox.py` | offline record queue and idempotent replay |
| `doctor.py` | read-only diagnosis |
| `cli.py` | argument parsing and output |

`proc.py`, `errors.py` and `managed.py` are additions to the module list
sketched in SPEC 7; each isolates something the spec requires but did not name
a home for (shell-free execution, exit-code policy, marker-block merging).

The complete package — including `adopt.py` and `upgrade.py` — is vendored
into the target, rather than the subset listed in SPEC 4. A superset costs a
few kilobytes and lets an adopted repository run `rh doctor` and `rh upgrade`
without reaching back to the distribution repository, which is the deployment
contract the spec actually asks for.

## Decisions the spec left open

**Checkpoint `--phase`.** State derivation must be deterministic (SPEC 10),
but `VALIDATING` and `READY_TO_MERGE` are not derivable from Git and records
alone: nothing in a diff says "the implementation is finished" or "the
experiment is running". Rather than have the CLI guess, checkpoints carry an
explicit `phase` (`implementing` | `validating` | `blocked` | `review`)
written by the agent, which is a report of an agent-side judgement, not a
judgement made by the CLI. `READY_TO_MERGE` is reachable only from a declared
`review` checkpoint — "no gate is outstanding" is not evidence that work is
done, and low-risk work requires no gates at all.

**Gate thresholds live in `config.toml`.** SPEC 19 gives risk→gate policy in
prose. It is implemented as threshold arithmetic over the declared risk level
(`gates.design_from` etc.), which is deterministic and researcher-editable.
The deviation gate is deliberately *not* schedulable by risk: it is raised
semantically by the agent and recorded, never predicted from a risk level.

**Branch links.** `.git/research-harness/links/` caches branch → Issue/PR. It
is a cache, not a database: the `rh/<n>-<slug>` convention and the Draft PR's
head ref both re-derive it, and a missing link degrades to "UNTRACKED" rather
than an error.

**Record ordering.** Timestamps carry milliseconds and ties preserve source
order. Second precision plus a UUID tie-break made a deviation gate able to
outrank the gate that closed it, when both were written in the same second.

**Repo slug resolution.** Config override → `github.repo` → remote URL parse →
`gh repo view`. The final fallback covers ssh aliases, `insteadOf` rewrites
and enterprise hosts, where URL parsing cannot work.

**Install inventory.** `.research-harness/inventory.json` records a SHA-256 per
installed file. `rh upgrade` uses it to distinguish "this file changed because
the bundle changed" from "the researcher edited this file"; the latter is
reported as a conflict and left alone unless `--force` is given.

**Byte-code.** `bin/rh` sets `sys.dont_write_bytecode` before importing the
runtime, so running the harness never leaves `__pycache__` in a research
repository (and never makes the worktree look dirty).

**Temporary files.** `--body-file` payloads are written under
`.git/research-harness/tmp` when a repository is available, not the system
temp directory, because `TMPDIR` can point inside `$HOME`.

## Marker escaping

`--` cannot appear inside an HTML comment. Marker payloads escape it as
`--` on write and JSON decoding reverses it on read, so record text
containing `--` cannot corrupt the comment that carries it.

## Schema tolerance

`parse_record` returns `None` for unknown record kinds and accepts unknown
schema versions and unknown fields (kept in `extra`). A newer harness'
records never break an older reader, and RDH never rewrites historical GitHub
records to migrate them (SPEC 61).

## Testing approach

`unittest` from the standard library; `pytest` is not required, matching the
runtime's zero-dependency rule. Three substitution layers keep tests hermetic:

* `FakeRunner` — scripted argv responses for unit tests.
* `RecordingRunner` — records argv for absence assertions.
* `tests/fixtures/fake_gh.py` — a fake `gh` executable on `PATH`, backed by a
  JSON state file, with injectable auth/network failures and a retry counter.
  `gh pr merge` exits 99 so a regression that merges is loud rather than
  silent.

The `$HOME` zero-touch tests snapshot a temporary HOME by content digest
before and after each command. Git is pointed at config files outside HOME
and given its identity through environment variables, so the environment
itself is quiet — there is an explicit test asserting that, plus three canary
tests proving the detector notices additions, modifications and deletions.

## Known limitations in v0.1

* Live end-to-end tests against a real GitHub repository are not included;
  the fake `gh` covers the adapter's contract. A live suite would go under
  `tests/e2e/` gated on an explicit test-repository environment variable.
* `rh` does not close Work Issues automatically. Issue close semantics
  (SPEC 24) are documented in the finish workflow and left to the researcher.
* Concurrency is documented (one writer per branch) but not locked;
  `.git/research-harness/lock/` is reserved for a future advisory lock.
