# Workflow — Finish (PR synthesis and Knowledge Gate)

Read `_common.md` and `policy/human-gates.md` (Gate D) first.

## 1. Check what is missing

```bash
"$RH" ready --json
```

It lists the deterministic blockers: missing Draft PR, pending gates, missing
Result Record when evidence is required, missing checkpoint, uncommitted work.

## 2. Synthesise the PR body

Use `templates/pull-request.md` and update the Draft PR:

```bash
"$RH" pr update --body-file <file>
```

Sections: Linked Work / Purpose / Behavioral Change / Important Implementation
/ Key Design Decisions / Deviations / Validation / Evidence / Interpretation /
Does NOT Establish / Known Limitations / Follow-up / Understanding Gate.

Write it from durable records, not from memory of the session.

## 3. Knowledge Gate

Ask the questions in `policy/human-gates.md` (Gate D). If the researcher
cannot yet own the work, repair and let them restate — do not pass them.

```bash
"$RH" record gate --gate knowledge --outcome passed   --body-file <file>
"$RH" record gate --gate knowledge --outcome repaired --body-file <file>
"$RH" record gate --gate knowledge --outcome blocked  --body-file <file>
```

## 4. Mark ready

```bash
"$RH" ready
```

When it exits 0 the work is `READY_TO_MERGE`. **Stop there.** The researcher
merges; RDH never runs `gh pr merge`, never force-pushes, never deletes a
branch.

## 5. Issue closing semantics

* Implementation work whose purpose is complete on merge → `Closes #<n>`.
* Experiment or analysis → `Refs #<n>`; the Issue closes after the Result
  Record and Evidence Gate, not on merge.
