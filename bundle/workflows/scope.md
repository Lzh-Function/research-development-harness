# Workflow — Scope

Turn a research idea into a Work Issue the researcher has agreed to, and take
the Design Gate if the work warrants one.

Read `_common.md` first.

## 1. Understand the request

Read `rh context --json`. Read the surrounding code and any linked Research
Question Issue. Ask the researcher for what is genuinely missing — not a
questionnaire.

Check which long-lived question this serves:

```bash
"$RH" rq list
"$RH" rq show <n>     # what is already established under that question
```

`rq show` is how you avoid proposing work that has already been done. If the
question does not exist yet and the work is part of a continuing line of
enquiry, create it before the Work Issue:

```bash
"$RH" rq create --title "When and where does chirality information emerge?"
```

Then link the work to it with `--rq <n>` in step 5.

## 2. Draft the scope

Produce a short draft covering:

```
Research question this serves
What will be built or run
Method, and why it answers the question
Main data flow (input → output)
Key assumptions
What would count as success / failure
What this will NOT establish
Rough cost (compute, time, data)
```

## 3. Classify

Choose `kind` (experiment | analysis | implementation | bug | refactor |
infrastructure | migration) and `risk` (low | medium | high) using
`policy/workflow.md`. Judge research consequence, not diff size. Decide
whether the work produces scientific evidence (`--evidence-required`).

State your classification and your reason in one or two sentences, and let the
researcher correct it.

## 4. Confirm with the researcher

Do not create the Issue until the researcher has agreed to the scope. This is
the cheapest possible moment to be wrong.

## 5. Create the Work Issue

```bash
"$RH" issue create \
  --title "<one-line purpose>" \
  --kind experiment --risk high --evidence-required \
  --body-file <(...)          # or --body-file path/to/draft.md
```

Use `templates/work-issue.md` as the body shape. `rh` inserts the `rh:work`
machine marker itself.

## 6. Design Gate

If `rh status --json` lists `design` in `pending_gates`, run the Design Gate
now (`policy/human-gates.md`, Gate A), then record it:

```bash
"$RH" record gate --gate design --outcome passed --body-file <file>
```

Record `overridden` with the researcher's own reason if they choose to skip.

## 7. Hand off

Report the Issue number and tell the researcher the next step is `rh-start`.
