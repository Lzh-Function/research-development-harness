# Workflow — Decision (Deviation Gate)

Used when the *meaning* of the work changes: research question, target, label
or dataset definition, experimental validity, metric semantics, major
architecture, persistent public API, material scope expansion, large added
compute cost, or interpretation.

Read `_common.md` and `policy/human-gates.md` (Gate B) first.

## 1. Stop before implementing the change

Do not re-scope silently, and do not implement "just the small part" first.

## 2. Present the decision

Use `templates/decision.md`:

```
Trigger            what forced this
Original Plan      what the Issue and accepted Decisions say today
Proposed Change    precisely what would change
Options            at least two, with honest trade-offs
Research Impact    validity, interpretation, cost, reversibility
Recommendation     yours, with the reason
```

Recommend, then wait. The researcher decides.

## 3. Record the outcome

```bash
"$RH" record decision --status accepted  --body-file <file>
"$RH" record decision --status rejected  --body-file <file>
"$RH" record decision --status deferred  --body-file <file>
```

Current intent is the original Work Issue **plus accepted Decision Records**.
Never edit the Issue body to make history agree with the present.

## 4. If a gate was opened

If you opened a deviation gate with `rh record gate --gate deviation
--outcome blocked`, close it after the decision:

```bash
"$RH" record gate --gate deviation --outcome passed --body-file <file>
```
