---
name: rh-checkpoint
description: Write a durable Checkpoint Record capturing the minimum state a fresh agent session needs to resume this work. Use at the end of a work session, before switching agents, before or after a long experiment, after a major deviation, when work is interrupted, or before context compaction.
---

# RDH Checkpoint

Record resumable state for the current work unit.

This skill is a thin adapter. The canonical workflow — the one Claude Code and
Codex both follow — lives in the repository, not in this file.

## Do this

1. Locate the repository root and the repo-local harness CLI. Never assume the
   current directory is the root.

   ```bash
   RH="$(git rev-parse --show-toplevel)/.research-harness/bin/rh"
   ```

2. Run `"$RH" context --json` to get repo, branch, HEAD, dirty state, linked
   Issue and PR, and outbox depth.

3. Read the canonical workflow and follow it:

   - `.research-harness/workflows/_common.md`
   - `.research-harness/workflows/checkpoint.md`

   Read the policy files it references
   (`.research-harness/policy/`) when they apply.

4. Do the semantic work yourself — intent, risk, grills, deviation detection,
   evidence interpretation, record prose. Leave Git/GitHub state, record
   serialization, state derivation and gate prerequisite checks to `rh`.

## Boundaries

- Durable state beats chat history. When they disagree, say so.
- Never merge, force-push, rewrite history, stash, reset, or delete branches.
- Uncommitted researcher work is preserved as-is.
- If `rh` refuses an operation, that refusal is the answer; surface it.
