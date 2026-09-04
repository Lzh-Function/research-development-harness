# Research Development Harness

A repository-local harness for human–AI research development.

Claude Code and Codex generate research code far faster than a researcher can
absorb it. RDH does not slow that down. It keeps four things recoverable, and
returns only the decisions that genuinely need a human:

| Meaning | Canonical source |
|---|---|
| **Intent** — why and what | Work Issue + accepted Decision Records |
| **Implementation** — how | Git |
| **Evidence** — what was observed | Result Records |
| **Understanding** — what the researcher owns | Gate Records |

Human-in-the-loop, not human-in-every-loop.

## Deployment contract

RDH is **fully repository-local**. It creates and modifies nothing under
`$HOME` — not `.claude`, `.agents`, `.codex`, `.local`, `bin`, `.config`, nor
any shell rc. There is no global skill, no global `rh`, and no Python package
to install. This is enforced by an integration test that snapshots a
temporary `HOME` before and after every command
([tests/integration/test_home_zero_touch.py](tests/integration/test_home_zero_touch.py)).

Requirements in a target repository: **Python 3.11+**, **git**, **gh**.

## Installing into a research repository

From a clone of this repository:

```bash
./bin/rh adopt /path/to/my-research-project
```

That vendors the runtime and workflows into the target. Afterwards the target
repository is self-contained: this distribution repository is no longer
needed. Preview first with `--dry-run`.

Adoption is **overlay + cutover**. It never rewrites history, never renames a
branch, never modifies research source files, and touches `AGENTS.md` /
`CLAUDE.md` only between its own markers. It writes exactly:

```
.research-harness/**
.claude/skills/rh-*/**
.agents/skills/rh-*/**
AGENTS.md   — managed block only
CLAUDE.md   — managed block only
```

Commit the result like any other repository content, so a fresh clone is
immediately usable.

## Using it

In the adopted repository the CLI is:

```bash
"$(git rev-parse --show-toplevel)/.research-harness/bin/rh" status
```

Agents reach it through eight project skills installed for both Claude Code
(`.claude/skills/`) and Codex (`.agents/skills/`): `rh-scope`, `rh-start`,
`rh-checkpoint`, `rh-resume`, `rh-status`, `rh-decision`, `rh-result`,
`rh-finish`. Each is a thin adapter over the canonical workflow in
`.research-harness/workflows/` — the workflow prose exists in exactly one
place, not duplicated per vendor.

A typical work unit:

```
rh-scope      → Work Issue, risk classified, [Gate A — Design]
rh-start      → branch + Draft PR
  … implement, checkpoint at meaningful boundaries …
rh-decision   → [Gate B — Deviation] when the meaning of the work changes
rh-result     → Result Record, [Gate C — Evidence]
rh-finish     → PR synthesis, [Gate D — Knowledge], READY_TO_MERGE
```

`READY_TO_MERGE` is the end of RDH's responsibility. **The harness never
merges.**

## What RDH will not do

Refused in code, not merely discouraged:

```
git reset --hard   git clean       git stash        git restore
git rebase         commit --amend  history rewrite
push --force       --force-with-lease
branch/tag/ref deletion            issue deletion   gh pr merge
```

Uncommitted work is always preserved. If one of these is what you want, run it
yourself.

## Commands

| Command | Purpose |
|---|---|
| `rh version` | runtime and bundle versions |
| `rh doctor` | read-only environment and installation diagnosis |
| `rh audit` | read-only repository inventory (no classification) |
| `rh adopt <target>` | vendor RDH into a research repository |
| `rh upgrade <target>` | re-vendor a newer RDH, preserving local edits |
| `rh context` | repo, branch, HEAD, dirty state, linked Issue/PR, outbox |
| `rh status` | derived state, pending gates, blockers, next action |
| `rh resume` | everything a fresh session needs to continue |
| `rh issue create` | Work Issue with an `rh:work` machine marker |
| `rh work start\|link` | branch + Draft PR, or link an existing branch |
| `rh record checkpoint\|decision\|result\|gate` | durable records as Issue comments |
| `rh ready` | deterministic `READY_TO_MERGE` preconditions |
| `rh sync` | replay queued records (idempotent) |
| `rh pr update` | replace the Draft PR body |

Read commands support `--json`; mutating commands support `--dry-run`.
Exit code `0` means success; anything else is a failure or an unmet
precondition.

## Design boundary

The split is strict, and it is the point of the system:

* **Agent / Skill** — research intent, risk classification, the Design Grill,
  semantic deviation detection, evidence interpretation, misconception
  repair, record and PR prose, the Knowledge Grill.
* **`rh` runtime** — Git and GitHub state, branch/Issue/PR operations, record
  parsing and serialization, context gathering, state derivation, gate
  prerequisite checks, adoption, outbox, sync, doctor, upgrade, managed
  blocks.

No scientific judgement is implemented in the CLI. No Git or GitHub state
management is left to natural language alone.

## Offline behaviour

Records that cannot reach GitHub are queued in
`.git/research-harness/outbox/` and replayed by `rh sync`. Replay is
idempotent: a record whose UUID already appears on the Issue is dropped, not
posted twice. `rh status --offline` works from the local cache.

## Development

```bash
python3 -m unittest discover -s tests -t . -q
```

Standard library only — no test dependencies, matching the runtime. GitHub is
exercised through a fake `gh` executable
([tests/fixtures/fake_gh.py](tests/fixtures/fake_gh.py)); no automated test
needs a GitHub account or a network.

The authoritative design document is [docs/SPEC.md](docs/SPEC.md).
Implementation notes and deliberate deviations are in
[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).
