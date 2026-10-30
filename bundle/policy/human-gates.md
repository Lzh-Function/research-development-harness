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

For a large, open-ended theme, Gate A comes **after** the direction-setting
discussion (`workflows/scope.md`, step 0), not before it. Take it only when
the researcher says the discussion is complete, and draw the questions from the
discussion records.

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

Gate D asks whether the researcher can carry this work out of the session:
defend it to someone who was not there, resume it cold, and recognise later if
it turns out to be wrong. It is not a recall test of documents that already
exist, and it does not re-run Gate C — what the evidence supports was settled
there.

Draw each question from this work unit's own records: name the actual number,
the actual deviation, the actual decision. Asking the generic form invites a
generic answer.

- **One sentence.** What does this work unit do, said to a colleague who was
  not there?
- **One number, traced.** Take a headline number: which data produced it, what
  was run on it, how was it reduced to that figure? For a work unit with
  no numbers, trace the behaviour that changed instead.
- **Load-bearing decisions.** Which decisions would change the conclusion if
  they had gone the other way?
- **Drift.** What changed relative to the Work Issue, and where was each change
  decided?
- **Misreading.** What would someone wrongly conclude from reading only the
  headline?
- **Next.** What is the next thing to do, and what observation would make you
  revisit this conclusion?

Roughly 3–4 of these for medium-risk work, all six for high. Stop early once
ownership is demonstrated. Do not read the list aloud as a checklist; ask what
is actually unclear.

Never quiz on function names or line numbers, and never ask the researcher to
recite something they could read off the Issue.

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
