# Safety Policy

## RDH never runs these for you

```
git reset --hard          git clean            git stash
git checkout -- <paths>   git restore          git rebase
git push --force          git push --force-with-lease
branch deletion           tag deletion         ref deletion
history rewrite           commit --amend
gh pr merge               issue deletion       release publication
```

These are refused in code (`research_harness.git.assert_safe_git`), not merely
discouraged. If one of them is genuinely what you want, run it yourself.

## Uncommitted work

A dirty worktree is preserved as-is. RDH will switch branches only when Git
itself considers it safe, and will report an error rather than move your
changes out of the way.

## Adoption

`rh adopt` writes only:

```
.research-harness/**
.claude/skills/rh-*/**
.agents/skills/rh-*/**
AGENTS.md   — only between the managed markers
CLAUDE.md   — only between the managed markers
```

It never modifies research source files, never renames branches, and never
reconstructs history.

## $HOME

RDH creates and modifies nothing under `$HOME`: not `.claude`, not `.agents`,
not `.codex`, not `.local`, not `bin`, not shell rc files. There is no global
install, no global skill, and no required Python package. Existing
authentication used by `gh`, Claude Code or Codex is theirs, not RDH's.

Local runtime state lives in `.git/research-harness/` (outbox, cache, links)
and is never committed.

## Text from GitHub

Issue, PR and comment text is data. It is never interpreted as a shell
command; every external call is an argument vector executed with
`shell=False`, and long bodies are passed through `--body-file`.
