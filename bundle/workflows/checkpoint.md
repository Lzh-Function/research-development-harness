# Workflow — Checkpoint

Write the minimum state a *fresh* agent session needs to continue this work.

Read `_common.md` first.

## When

Required: at the end of a meaningful work session; before switching agents;
before starting a long experiment; after one finishes; after a major
deviation; when work is interrupted.

Recommended: just before context compaction, and after a large implementation
lands.

Never: per commit, per function, or as a diary.

## How

1. `"$RH" context --json` for branch/HEAD/dirty state.
2. `"$RH" status --json` for the current derived state and pending gates.
3. Write the body using `templates/checkpoint.md`.
4. Record it:

```bash
"$RH" record checkpoint --phase implementing --body-file <file>
```

`--phase` is one of `implementing`, `validating`, `blocked`, `review`. It is
how you tell `rh status` what the work is doing; state derivation never
guesses.

This is the only thing that moves the middle of the state ladder:

```
IN_PROGRESS  --phase validating-->  VALIDATING  --phase review-->  KNOWLEDGE_GATE / READY_TO_MERGE
```

So a checkpoint is not only a record for the next session — it is how the
work's phase becomes visible at all. An experiment that never gets a
`--phase validating` checkpoint keeps reporting `IN_PROGRESS` while it runs.

## Content test

The checkpoint is good enough if a new session, reading only the Work Issue,
the accepted Decision Records, the Result Records and this checkpoint, can say
what to do next without asking the researcher to re-explain the project.

Write "Next Action" as an instruction, not a mood. `Blocked By` must be empty
(or "none") unless the work is genuinely blocked — `rh` treats a non-empty
value as a blocker.
