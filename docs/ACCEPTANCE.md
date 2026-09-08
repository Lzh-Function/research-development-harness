# Acceptance Evidence

Every requirement in SPEC 64 (Mandatory Acceptance Scenarios) and SPEC 70
(Definition of Done) mapped to the test that verifies it. Run everything with:

```bash
./run-tests -q
```

## Definition of Done (SPEC 70)

| # | Requirement | Verified by |
|---|---|---|
| 1 | Adopt from the distribution repo into a target repo | `integration.test_adoption.FreshAdoptionTests.test_installs_the_full_layout` |
| 2 | Target runs repo-local `rh` with no distribution repo and no global install | `e2e.ScenarioSelfContainment.test_vendored_runtime_executes_from_the_target_only`, `test_a_relocated_copy_still_works`, `integration.RepositoryLocalRuntimeTests.test_no_pythonpath_or_global_package_is_required` |
| 3 | No RDH files under `$HOME` | `integration.test_home_zero_touch.HomeZeroTouchTests` (7 tests, plus 3 canaries proving the detector works) |
| 4 | Existing dirty repo adopted without damage | `integration.test_adoption.ExistingRepositoryAdoptionTests` (8 tests) |
| 5 | Claude and Codex project skills installed | `integration.test_adoption.FreshAdoptionTests.test_both_agent_skill_trees_are_installed`, `unit.test_skill_bundle` |
| 6 | Issue → Design Gate → Draft PR → Checkpoint works | `integration.test_work_lifecycle.DesignGateTests`, `WorkStartTests`, `RecordAndStateTests` |
| 7 | Resume from a fresh agent session | `integration.AgentSwitchTests.test_resume_reconstructs_everything_from_durable_state`, `test_records_are_readable_by_a_second_clone` |
| 8 | Decision / Result / Gate Records persisted as Issue comments | `integration.RecordAndStateTests.test_records_land_as_issue_comments_with_markers`, `unit.test_records` |
| 9 | `READY_TO_MERGE` reachable | `integration.RecordAndStateTests.test_state_advances_through_the_flow` |
| 10 | The harness never merges | `integration.NoDestructiveOperationsTests`, `e2e.ScenarioH.test_harness_never_merges_even_when_ready`, and `gh pr merge` exits 99 in the fake `gh` |
| 11 | Outbox + idempotent sync on GitHub failure | `integration.OfflineTests` (9 tests), `unit.test_outbox` |
| 12 | Main behaviours covered by automated tests | 332 tests, standard library only |

## Mandatory Acceptance Scenarios (SPEC 64)

| Scenario | Verified by |
|---|---|
| A. Fresh repository | `integration.test_adoption.FreshAdoptionTests` (13 tests) |
| B. Existing dirty repository | `integration.test_adoption.ExistingRepositoryAdoptionTests` |
| C. Existing project migration | `e2e.ScenarioC_ExistingProjectMigration.test_migration_is_overlay_not_reconstruction` |
| D. Medium new work | `integration.DesignGateTests`, `WorkStartTests` |
| E. Agent switch | `integration.AgentSwitchTests` |
| F. Significant deviation | `integration.RecordAndStateTests.test_deviation_gate_blocks_until_decided`, `unit.test_state.DeriveStateTests.test_deviation_gate_wins` |
| G. Negative experiment | `integration.RecordAndStateTests.test_negative_result_completes_normally` |
| H. Knowledge Gate | `e2e.ScenarioH_KnowledgeGate` (4 tests: blocked, repaired, overridden, never-merges) |
| I. Offline record | `integration.OfflineTests` |
| J. Zero-touch HOME | `integration.test_home_zero_touch` |

## Required test coverage (SPEC 63)

**Unit** — config parsing, manifest parsing, record marker parser, record
serialization, state inference, gate requirement logic, managed block merge,
version comparison, outbox idempotency: `unit.test_records`,
`unit.test_state`, `unit.test_managed_and_config`, `unit.test_outbox`.

**Git integration** — dirty tree preserved, branch creation, existing branch
adoption, HEAD detection, worktree handling, no reset, no stash, no history
rewrite: `unit.test_safety.RepoSafetyTests`,
`integration.WorktreeTests`, `integration.NoDestructiveOperationsTests`,
`integration.WorkStartTests.test_existing_branch_is_adopted_not_renamed`.
The 30 destructive invocations in `unit.test_safety.FORBIDDEN` are refused by
`assert_safe_git` before reaching a subprocess.

**GitHub integration** — issue create/read, comment records, Draft PR
creation, PR read/update, pagination, auth failure, network failure, retry,
duplicate UUID prevention: `unit.test_github_adapter` (24 tests) against a
fake runner, and `integration.OfflineTests` against the fake `gh` executable.
No automated test requires a GitHub account or a network.

## Beyond the spec

`rh log` (cross-issue research history) is an addition, not a SPEC 33
requirement. It is read-only and additive: no existing command, record schema
or deployment contract changed. Covered by
`integration.test_log` (24 tests) and `unit.test_records.HeadlineTests`.

## Live end-to-end run

Executed 2026-09-05 against the real `Lzh-Function/research-development-harness`
repository with `gh` 2.100.0, from a clone adopted by `rh adopt`:
Research Question, Work Issue with an `rh:work` marker, refused `work start`
before the design gate, Design/Evidence/Knowledge Gate Records, real work
branch and Draft PR, checkpoint and result records, the structural `rh ready`
block and its release, `rh rq show`, `rh log`, offline queueing and
exactly-once `rh sync`, and a clean `rh doctor`. Verified independently
through `gh`: six durable records with correct markers, the PR still Draft,
and remote `main` untouched.

It found two defects the fake `gh` could not:

* GitHub refuses to open a pull request on a branch with no commits, which is
  the state `rh work start` leaves a new branch in.
* `gh repo view` rejects `--repo` ("unknown flag"); the repository is a
  positional argument. Every repo-scoped call appended the flag, so
  `default_branch()` always failed and returned `None`, silently falling back
  to local branch detection.

Every `gh` wrapper reachable from the CLI has now been exercised against the
real API: `--version`, `auth status`, `repo view` (with and without a known
repository), `issue create|view|list|comment|close`, paginated
`api .../comments`, `pr create|view|list|edit`, plus offline queueing and
`rh sync`.

## Not covered in v0.1

* An *automated* live suite. The run above was manual; a scripted version
  would live in `tests/e2e/` gated on an explicit test-repository environment
  variable, so ordinary CI still needs no GitHub account.
* Concurrency is documented (one writer per branch) but not enforced by a
  lock.
