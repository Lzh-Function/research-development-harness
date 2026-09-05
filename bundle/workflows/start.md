# Workflow — Start work

Move a scoped Work Issue into an implementable branch and Draft PR.

Read `_common.md` first.

## 1. Check preconditions

```bash
"$RH" status --json
```

`rh work start` refuses when the design gate is required and has no passing
Gate Record. That is a precondition, not a suggestion — take the gate first
(`workflows/scope.md`, step 6) or record an explicit override.

## 2. Start

```bash
"$RH" work start <issue>                              # new rh/<n>-<slug> branch
"$RH" work start <issue> --existing-branch probe-x    # adopt existing branch
```

This creates or links the branch, pushes it, and opens a **Draft** PR whose
body comes from `templates/pull-request.md`. Existing branches are adopted,
never renamed.

**A brand-new branch has no commits, and GitHub refuses to open a pull request
on one.** When that happens `rh work start` says so and defers; open the PR
yourself after the first commit:

```bash
"$RH" pr create
```

`rh status` will point you there too. Nothing is lost in the meantime: the
branch, the link and the Work Issue all exist already.

If the worktree is dirty, RDH keeps the changes. If Git itself refuses the
switch, tell the researcher; never stash or reset on their behalf.

## 3. Orient before writing code

Restate, in two or three lines: the research question, what this work unit
does, and what would make it wrong. Then implement.

## 4. While implementing

* Routine decisions are yours — make them and move on.
* A change to intent, validity, semantics, architecture, scope or cost is a
  Deviation Gate: stop and use `workflows/decision.md`.
* Checkpoint at meaningful boundaries (`workflows/checkpoint.md`).
