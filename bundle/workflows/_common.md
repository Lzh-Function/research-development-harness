# Common preamble for every RDH workflow

## Locating the harness

Never assume the current directory is the repository root.

```bash
RH="$(git rev-parse --show-toplevel)/.research-harness/bin/rh"
"$RH" context --json
```

`rh context --json` is the first call of nearly every workflow. It reports
`repo_root`, `repo`, `branch`, `head`, `dirty`, `changed_paths`, `remote`,
`pr`, `issue`, `harness_version` and `outbox_pending`.

## Division of labour

`rh` does deterministic work: Git and GitHub state, records, state derivation,
gate prerequisite checks, outbox, sync. **You** do the semantic work: reading
research intent, classifying risk, running the grills, interpreting evidence,
detecting deviation, and writing the prose that goes into records.

Never ask `rh` to judge whether something matters scientifically, and never
reconstruct Git/GitHub state by hand when `rh` can report it.

## Failure handling

* GitHub unreachable → record commands queue to the outbox automatically; tell
  the researcher, and mention `rh sync`.
* `rh` exits non-zero → read the message; it names the unmet precondition.
  Do not work around it by running raw `git`/`gh` destructive commands.
* Unsafe operation refused → that is deliberate. Surface it; do not retry.
