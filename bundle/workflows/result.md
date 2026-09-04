# Workflow — Result & Evidence Gate

Read `_common.md` and `policy/human-gates.md` (Gate C) first.

## 1. Record what was observed

Use `templates/result.md`. Separate observation from interpretation ruthlessly:

```
Question             what this run was supposed to answer
Run / Evidence       what was actually executed
Observation          what happened, without adjectives
Primary Metrics      the numbers that matter
Interpretation       your reading, marked as a reading
Supports             what the evidence supports
Does NOT Support     what it cannot establish
Confounders          what could explain this instead
Unexpected Findings
Follow-up
Provenance           commit SHA, config, dataset/version, seed, run ID, artifact path
```

```bash
"$RH" record result --body-file <file>
```

Keep raw logs where they live. GitHub gets the pointer, not the payload.

## 2. Evidence Gate

Do not settle the conclusion yourself. Present observed facts, plausible
interpretations, alternatives, and confounders; the researcher decides how
strong the claim is.

```bash
"$RH" record gate --gate evidence --outcome passed --body-file <file>
```

A hypothesis that was not supported is a completed experiment. Record it as a
result, not as a failure.
