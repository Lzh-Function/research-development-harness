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

The Provenance section is checked by `rh ready`: title it `Provenance` (or `出所`)
and write at least one `- key: value` line. Any other title is not recognised,
and a record cannot be edited afterwards.

## Gate

Sections: Validated Concepts / Misconceptions Repaired / Unresolved / Outcome.
The full grill transcript is never stored.

## Writing for the reader

Applies to every Work Issue, Research Question, PR body and record. The reader
arrives cold (often weeks later, often not the author). Optimise for **how
little effort it takes to understand**, not for how short or how precise the
text looks. A compressed sentence full of coined terms is a cost, not a saving.

**Describe what was done as steps.** For each step say four things in plain
words: *what* was done, *on which data* (which stage of the pipeline, how many
items), *how* (the method, not just its name), and *what came out*. Prefer a
small table, one row per step:

| Step | Data used (stage, count) | How | Output |
|---|---|---|---|

**Report what was learned as a lead sentence plus tables.**

- Start with one to three plain sentences: what became clear.
- Then show numbers in tables (rows = the things compared, columns = the few
  numbers that matter). Never list numbers in running prose.
- Put one line under each table saying how to read it, or what to notice.
- Keep observation and interpretation apart, as before.

**Wording.**

- Explain a term in a short phrase the first time it appears. Spell out
  abbreviations and code names (say what "stage 1.5" or "AD" is).
- Refer to a dataset by its role and stage ("the 40,000 molecules that passed
  the first filter"), with the path in Provenance, not the path alone.
- One idea per sentence; avoid stacked compound nouns and long chains of
  clauses.
- Say each thing once. Details that only a few readers need go behind a link
  or into an artifact, not into the body.
- A table has at most about seven rows and six columns; split it otherwise.

The test: could a colleague from another sub-field read the body once, from
top to bottom, and say what was done and what was found?

## Schema evolution

Readers tolerate older and unknown schema versions. RDH never rewrites
historical GitHub records to migrate them.
