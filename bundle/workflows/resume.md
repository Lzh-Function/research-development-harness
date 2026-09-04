# Workflow — Resume

Reconstruct a work unit from durable state alone. This is RDH's most important
capability: it must work with **no chat history at all**, and it must work
across agents (Claude ↔ Codex).

Read `_common.md` first.

## Read in this order

1. `"$RH" context --json`
2. `"$RH" status --json` — derived state, pending gates, blockers
3. `"$RH" resume --json` — Work Issue, accepted Decisions, Results, latest
   Checkpoint, PR, and the Git changes since that checkpoint, in one payload
4. The diff itself, for anything the checkpoint does not explain
5. Tests / CI signal, if relevant

Do not modify research code until the resume briefing is complete.

## Produce this briefing

```
WHY               the research question this serves
WHAT              what this work unit does
CURRENT STATE     derived state, branch, HEAD, PR
DONE              from the checkpoint, corrected against Git
IMPORTANT DECISIONS   accepted Decision Records only
KNOWN EVIDENCE    Result Records, with what they do and do not support
LIMITATIONS       what this work cannot establish
UNRESOLVED        pending gates, blockers, open questions
NEXT              the single next action
```

## If durable state and the code disagree

Say `STATE DIVERGENCE DETECTED`, then classify: undocumented implementation
drift, an intentional but unrecorded change, or a stale checkpoint. If it
matters scientifically, go to `workflows/decision.md` instead of quietly
reconciling it.

## If there is no checkpoint

Say so plainly, reconstruct what you can from the Issue, Decisions, Results
and Git, mark the reconstruction as inferred, and write a checkpoint once the
researcher confirms it.
