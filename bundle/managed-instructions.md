## Research Development Harness

This repository uses Research Development Harness (RDH). The harness is
repository-local: everything lives in `.research-harness/`, and there is
nothing to install globally.

**Reconstruct tracked work from repository-local harness state, not from chat
history.** Start with:

```bash
"$(git rev-parse --show-toplevel)/.research-harness/bin/rh" context --json
"$(git rev-parse --show-toplevel)/.research-harness/bin/rh" status
```

- Scope medium/high-impact new work before implementing it.
- Do not interrupt the researcher for routine implementation details
  (naming, typing, fixtures, layout, routine refactors, logging, lint).
- Do interrupt when research intent, experimental validity, semantic
  definitions of data/labels/metrics, major architecture, significant scope or
  cost, or evidence interpretation need a human decision — and at every
  explicit Human Gate.
- Record meaningful checkpoints (`rh record checkpoint`), not per-commit
  diaries.
- Implementation completion is not a scientific conclusion.
- Never auto-merge, force-push, rewrite history, or destroy uncommitted work.

Canonical workflow documents live in `.research-harness/workflows/` and policy
in `.research-harness/policy/`. The agent skills in `.claude/skills/` and
`.agents/skills/` are thin adapters over those files.
