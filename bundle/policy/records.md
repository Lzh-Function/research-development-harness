# Durable Records

Canonical durable records are **Work Issue comments** (SPEC 25). PR comments
are not a record store. Every record begins with a machine marker:

```html
<!-- rh:record {"schema":1,"kind":"checkpoint","id":"<uuid>","issue":184,"head":"abcdef1234","created_at":"..."} -->
```

The marker is for `rh`; the Markdown below it is for humans. Records are
written with `rh record <kind>`, which generates the marker, posts the comment,
and falls back to the outbox when GitHub is unreachable.

## Checkpoint

The minimum sufficient state for a *fresh* agent session to resume the work.
Not a work diary, not a commit log.

Trigger a checkpoint when: a meaningful work session ends; before switching
agents; before and after a long experiment; after a major deviation; when work
is interrupted; and (should) before context compaction or after a large
implementation lands. Never per commit or per function.

Sections: Done / Current State / Important Decisions / Deviations / Evidence
Obtained / Unexpected Findings / Blocked By / Remaining / Next Action /
Provenance.

`--phase` declares what the work is doing (`implementing`, `validating`,
`blocked`, `review`) so that `rh status` can derive state without guessing.

## Decision

Written at a Deviation Gate. Sections: Trigger / Original Plan / Proposed
Change / Options / Research Impact / Decision / Rationale. Status is
`accepted`, `rejected` or `deferred`.

Current intent = **original Work Issue + accepted Decision Records**. Never
edit the Issue body to erase historical intent.

## Result

Sections: Question / Run / Observation / Primary Metrics / Interpretation /
Supports / Does NOT Support / Confounders / Unexpected Findings / Follow-up,
plus Provenance (commit SHA, configuration, dataset version, seed, run ID,
artifact path or URL).

Raw logs and artifacts stay where they are; GitHub holds the pointer, not the
payload.

## Gate

Sections: Validated Concepts / Misconceptions Repaired / Unresolved / Outcome.
The full grill transcript is never stored.

## Schema evolution

Readers tolerate older and unknown schema versions. RDH never rewrites
historical GitHub records to migrate them.
