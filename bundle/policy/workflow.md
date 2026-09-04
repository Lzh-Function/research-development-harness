# Research Development Harness — Workflow Policy

RDH keeps four things recoverable long after the chat window is gone:

| Meaning | Canonical source |
|---|---|
| Intent | Work Issue + accepted Decision Records |
| Implementation | Git |
| Evidence | Result Records |
| Understanding | Gate Records |
| Progress | latest Checkpoint + its diff against Git |

**Agent chat history is never the source of truth.** If durable state and
your memory of the conversation disagree, durable state wins and the
discrepancy is itself a finding (see *State Divergence* below).

## The flow

```
Research idea
  → Scope draft            (rh-scope)
  → Researcher confirms scope
  → Work Issue             (rh issue create)
  → [Gate A — Design]      (rh record gate --gate design)
  → Draft PR + work        (rh work start)
      ↳ significant deviation → [Gate B] → Decision Record
  → Validation / experiment
  → Result Record          (rh record result)
  → [Gate C — Evidence]
  → PR synthesis           (rh-finish)
  → [Gate D — Knowledge]
  → READY_TO_MERGE
```

`READY_TO_MERGE` is where RDH stops. **The harness never merges.**

## One PR ≈ one conceptual unit

Not a line count. The rule is: *the researcher can explain this PR as one
purpose and one mechanism.* A 3000-line vendored dataset loader can be one
unit; two unrelated 20-line changes are two.

## Work risk

Risk is about research consequence, never about diff size (SPEC 20). Judge on:
research impact, interpretation impact, experimental validity, irreversibility,
scope, cost, recoverability.

* **low** — typos, docs, logging, obvious bugs, test-only changes, refactors
  with no behavioural change. Normally no gate.
* **medium** — a new analysis module, added evaluation, a non-trivial API, a
  pipeline change, reusable functionality. Design + Knowledge gates; Evidence
  gate too if it produces scientific evidence.
* **high** — model architecture, objective/loss, data or label definitions,
  the central hypothesis, conclusion-critical analysis, metric semantics,
  expensive experiments. Design + Evidence + Knowledge gates, and a Deviation
  gate whenever the meaning of the work changes.

## When to interrupt the researcher

Interrupt when: research intent changes; experimental validity changes; data or
label semantics change; metric meaning changes; scope materially expands; major
persistent architecture changes; experiment cost changes significantly;
unexpected evidence changes the interpretation; or an explicit Human Gate is
reached.

Do **not** interrupt for: function or class names, typing, fixtures, file
organisation, routine refactors, ordinary error handling, logging, lint,
serialization plumbing, or test boilerplate. Human-in-the-loop, not
human-in-every-loop.

## State divergence

When the Issue, the accepted Decisions, the latest Checkpoint and the code
disagree, say so explicitly:

```
STATE DIVERGENCE DETECTED
```

Then classify it: undocumented implementation drift, an intentional but
unrecorded change, or a stale checkpoint. If the divergence matters
scientifically, raise a Deviation Gate rather than quietly reconciling it.

## Concurrency

One active writer per branch. Parallel work goes on parallel branches
(work A → branch A, work B → branch B). Never run two agents writing the same
branch.
