# Workflow — Status

Read `_common.md` first.

```bash
"$RH" status          # human-readable
"$RH" status --json   # for your own reasoning
```

Reports: current work, derived state, risk, Issue, PR, branch, HEAD, latest
checkpoint, changes since that checkpoint, pending gates, blockers, and the
next recorded action.

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
