# Human Gates

A gate is a place where the *researcher*, not the agent, decides. Gates are
recorded with `rh record gate`; only the outcome and the concepts covered are
stored — never the full transcript of the questioning, never chain-of-thought.

Outcomes: `passed`, `repaired`, `overridden`, `blocked`.

## Gate A — Design / Intent

*Before implementation of medium/high-risk work.*

Ask open-ended questions (roughly 3–5 for medium work, 5–8 for high) about:

- What is being tested or built, and why this method answers the question
- The main input → output data flow
- Key assumptions
- Failure modes and confounders
- What observation would support or refute the hypothesis
- What this design cannot establish

Stop early once understanding is demonstrated. Do not read the list aloud as a
checklist; ask what is actually unclear.

## Gate B — Deviation

*When the meaning of the work changes mid-flight.*

Do not silently re-scope. Present:

```
What changed
Why the change is needed
The original design
The options
Your recommendation
Research and architecture impact
```

Then record the researcher's answer with `rh record decision --status ...`.

Deviation-worthy: research question, target, label definition, dataset
definition, experimental validity, metric semantics, major architecture,
persistent public API, material scope expansion, large added compute cost,
interpretation.

## Gate C — Evidence

*After results exist, before conclusions are asserted.*

The agent organises, the researcher concludes:

```
Observed facts
Possible interpretation
Alternative interpretations
Confounders
What this supports
What this does NOT establish
```

A negative result is a completed experiment, not a failure.

## Gate D — Knowledge

*Before READY_TO_MERGE.*

Check that the researcher can own this work unit:

- Explain this PR in one sentence
- What was the original research question?
- What is the main data flow?
- Which design decisions mattered?
- What changed relative to the Issue?
- What does the validation guarantee — and what does it not?
- What can be claimed from the evidence, and what cannot?
- What is the next thing to investigate?

Never quiz on function names or line numbers.

## Repair loop

```
Researcher answer
  ├── sufficient    → continue
  ├── partial       → explain the missing concept → ask again
  └── misconception → repair → researcher restates in their own words
```

Never fill in a half-answer on the researcher's behalf and call it a pass.
Record `outcome = repaired` when repair was needed and succeeded.

## Override

The researcher may skip any gate ("exploratory prototype, skip it"). Record:

```
outcome = overridden
reason  = <their reason, in their words>
```

The harness is never a higher decision-making authority than the researcher.
