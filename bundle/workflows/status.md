# Workflow — Status

Read `_common.md` first.

```bash
"$RH" status          # human-readable
"$RH" status --json   # for your own reasoning
```

Reports: current work, derived state, risk, Issue, PR, branch, HEAD, latest
checkpoint, changes since that checkpoint, pending gates, blockers, and the
next recorded action.

`rh status` also reports **Next Command**: the command that mechanically
advances the current state. Gate outcomes are always offered as the full set
of choices (`passed|overridden`) — the researcher decides which, never you and
never the CLI.

## Reading it

* `changes_since_checkpoint` non-empty and large → the checkpoint is stale;
  write a new one before doing anything else.
* `pending_gates` non-empty → those are human decisions, not tasks you can
  complete alone.
* `blockers` non-empty → say so first; do not start new work on top.
* `state: UNTRACKED` → this branch is not linked to a Work Issue. Either
  `rh work link <issue>` it, or scope the work properly.
* `outbox_pending` non-zero → records exist locally that GitHub has not seen;
  mention `rh sync`.

Report state to the researcher in plain language. Do not paste raw JSON at
them unless they ask.

## Zooming out to the whole project

`rh status` is scoped to one work unit. When the question is about the
project — what has been established so far, what was tried and did not work,
where the researcher's understanding needed repair — use the cross-issue
history instead:

```bash
"$RH" log                                  # every record, newest first
"$RH" log --kind result                    # every result, including negative ones
"$RH" log --kind result --since 2026-06
"$RH" log --kind decision --status accepted   # what the current intent is built on
"$RH" log --kind gate --outcome repaired   # where understanding needed repair
"$RH" log --grep leakage --full
```

Reach for this when the researcher asks what the project has learned, when
writing up results, when a new work unit might duplicate an old one, or when
you need to know whether a question has already been answered. It is
read-only and works offline from the local cache.

Do not use it as a substitute for `rh resume` on the current work unit: `log`
is breadth, `resume` is depth.
