---
name: rh-start
description: Start implementing a scoped Work Issue: verify gate preconditions, create or adopt the branch, push it, and open the Draft PR. Use when the researcher says to begin work on an existing Work Issue.
---

# RDH Start

Move a scoped Work Issue into an implementable branch and Draft PR.

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
   - `.research-harness/workflows/start.md`

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
