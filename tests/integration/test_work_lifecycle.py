"""Work Issue → Design Gate → Draft PR → records → READY_TO_MERGE (SPEC 64 D–H).

Everything runs against the vendored runtime inside an adopted repository and
the fake `gh`, so this exercises the deployment contract as well as the flow.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class LifecycleTestCase(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)

    # ------------------------------------------------------------------ helpers

    def rh(self, args, *, check=False, env=None):
        return self.sandbox.rh_local(self.repo, args, check=check, env=env)

    def rh_json(self, args, *, env=None):
        result = self.rh([*args, "--json"], check=True, env=env)
        return json.loads(result.stdout)

    def write(self, name, text):
        path = self.repo / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def create_issue(self, *, title="Probe layer 7", kind="experiment", risk="high", evidence=True):
        args = [
            "issue", "create", "--title", title, "--kind", kind, "--risk", risk,
            "--body-file", self.write("_body.md", "## Purpose\n\nProbe layer 7 chirality.\n"),
        ]
        if evidence:
            args.append("--evidence-required")
        payload = self.rh_json(args)
        (self.repo / "_body.md").unlink()
        return payload["issue"]

    def pass_gate(self, issue, gate, outcome="passed"):
        return self.rh_json(
            ["record", "gate", "--gate", gate, "--outcome", outcome, "--issue", str(issue),
             "--body-file", self.write("_gate.md", f"## Gate Record\n\n### Outcome\n{outcome}\n")]
        )

    def commit(self, name="analysis.py", text="print('x')\n", message="work"):
        self.write(name, text)
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", message])

    def start_work(self, issue, *, seed="probe.py"):
        """Start work the way the real flow goes.

        GitHub cannot open a pull request on a branch with no commits, so
        `rh work start` defers it: branch first, first commit, then the PR.
        """
        payload = self.rh_json(["work", "start", str(issue)])
        if payload.get("pr") is None:
            self.commit(seed, f"# work on #{issue}\n", f"begin work on #{issue}")
            self.sandbox.git(self.repo, ["push", "-q", "origin", "HEAD"])
            payload = {**payload, **self.rh_json(["pr", "create"])}
        return payload


class IssueCreationTests(LifecycleTestCase):
    def test_work_issue_carries_a_machine_marker(self):
        number = self.create_issue()
        body = self.sandbox.gh_data()["issues"][str(number)]["body"]
        self.assertIn("<!-- rh:work", body)
        marker = json.loads(body.split("<!-- rh:work ", 1)[1].split(" -->", 1)[0])
        self.assertEqual(marker["kind"], "experiment")
        self.assertEqual(marker["risk"], "high")
        self.assertTrue(marker["evidence_required"])
        self.assertIn("Probe layer 7 chirality.", body)

    def test_dry_run_creates_nothing(self):
        result = self.rh(
            ["issue", "create", "--title", "T", "--kind", "analysis", "--body", "b", "--dry-run"], check=True
        )
        self.assertIn("[dry-run]", result.stdout)
        self.assertEqual(self.sandbox.gh_data()["issues"], {})

    def test_body_is_required(self):
        result = self.rh(["issue", "create", "--title", "T"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("body is required", result.stderr)

    def test_invalid_risk_is_rejected_by_the_parser(self):
        result = self.rh(["issue", "create", "--title", "T", "--body", "b", "--risk", "catastrophic"])
        self.assertNotEqual(result.returncode, 0)


class DesignGateTests(LifecycleTestCase):
    def test_work_start_is_blocked_without_the_design_gate(self):
        number = self.create_issue()
        result = self.rh(["work", "start", str(number)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("design gate", result.stderr)
        self.assertEqual(self.sandbox.gh_data()["prs"], {})

    def test_low_risk_work_needs_no_gate(self):
        number = self.create_issue(title="Fix typo", kind="bug", risk="low", evidence=False)
        payload = self.rh_json(["work", "start", str(number)])
        self.assertEqual(payload["branch"], f"rh/{number}-fix-typo")

    def test_overridden_gate_unblocks_work(self):
        number = self.create_issue()
        self.rh_json(["work", "link", str(number)])
        self.pass_gate(number, "design", outcome="overridden")
        payload = self.rh_json(["work", "start", str(number)])
        self.assertTrue(payload["branch"].startswith(f"rh/{number}-"))

    def test_status_reports_the_pending_design_gate(self):
        number = self.create_issue()
        self.rh_json(["work", "link", str(number)])
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "DESIGN_GATE")
        self.assertIn("design", payload["pending_gates"])


class WorkStartTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.issue = self.create_issue()
        self.rh_json(["work", "link", str(self.issue)])
        self.pass_gate(self.issue, "design")

    def test_defers_the_pr_on_a_branch_with_no_commits(self):
        """GitHub refuses a PR with no commits; RDH says so instead of failing."""
        payload = self.rh_json(["work", "start", str(self.issue)])
        self.assertEqual(payload["branch"], f"rh/{self.issue}-probe-layer-7")
        self.assertIsNone(payload["pr"])
        self.assertTrue(payload["pr_deferred"])
        self.assertIn("no commits", payload["pr_error"])
        self.assertEqual(self.sandbox.gh_data()["prs"], {})
        self.assertIn("rh pr create", self.rh(["work", "start", str(self.issue)], check=True).stdout)

    def test_pr_create_is_refused_until_there_is_a_commit(self):
        self.rh_json(["work", "start", str(self.issue)])
        result = self.rh(["pr", "create"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no commits", result.stderr)

    def test_creates_branch_and_draft_pr(self):
        payload = self.start_work(self.issue)
        self.assertEqual(payload["branch"], f"rh/{self.issue}-probe-layer-7")
        self.assertIsNotNone(payload["pr"])
        pr = self.sandbox.gh_data()["prs"][str(payload["pr"])]
        self.assertTrue(pr["isDraft"], "PRs must be created as drafts")
        self.assertEqual(pr["headRefName"], payload["branch"])
        self.assertIn(f"Refs #{self.issue}", pr["body"])
        self.assertEqual(
            self.sandbox.git(self.repo, ["branch", "--show-current"]).stdout.strip(), payload["branch"]
        )

    def test_experiment_uses_refs_not_closes(self):
        payload = self.start_work(self.issue)
        self.assertIn("Refs #", self.sandbox.gh_data()["prs"][str(payload["pr"])]["body"])

    def test_implementation_uses_closes(self):
        number = self.create_issue(title="Add loader", kind="implementation", risk="low", evidence=False)
        payload = self.start_work(number, seed="loader.py")
        self.assertIn(f"Closes #{number}", self.sandbox.gh_data()["prs"][str(payload["pr"])]["body"])

    def test_existing_branch_is_adopted_not_renamed(self):
        self.sandbox.git(self.repo, ["switch", "-c", "probe-analysis"])
        self.commit("probe.py", "# existing work\n", "existing work")
        before = sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())
        payload = self.rh_json(["work", "start", str(self.issue), "--existing-branch", "probe-analysis"])
        after = sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())
        self.assertEqual(payload["branch"], "probe-analysis")
        self.assertEqual(before, after, "existing branches must never be renamed")
        self.assertTrue((self.repo / "probe.py").exists())

    def test_missing_existing_branch_is_an_error(self):
        result = self.rh(["work", "start", str(self.issue), "--existing-branch", "no-such-branch"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no such branch", result.stderr)

    def test_dirty_worktree_is_carried_not_destroyed(self):
        self.write("wip.py", "# uncommitted\n")
        self.rh_json(["work", "start", str(self.issue)])
        self.assertEqual((self.repo / "wip.py").read_text(encoding="utf-8"), "# uncommitted\n")

    def test_dry_run_creates_no_branch_and_no_pr(self):
        result = self.rh(["work", "start", str(self.issue), "--dry-run"], check=True)
        self.assertIn("[dry-run]", result.stdout)
        self.assertEqual(self.sandbox.gh_data()["prs"], {})
        self.assertNotIn(f"rh/{self.issue}", self.sandbox.git(self.repo, ["branch"]).stdout)

    def test_restarting_reuses_the_existing_pr(self):
        first = self.start_work(self.issue)
        second = self.rh_json(["work", "start", str(self.issue)])
        self.assertEqual(first["pr"], second["pr"])
        self.assertEqual(len(self.sandbox.gh_data()["prs"]), 1)

    def test_non_work_issue_is_refused(self):
        self.sandbox.run(["gh", "issue", "create", "--title", "Plain issue", "--body", "no marker"])
        plain = max(int(n) for n in self.sandbox.gh_data()["issues"])
        result = self.rh(["work", "start", str(plain)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rh:work marker", result.stderr)


class RecordAndStateTests(LifecycleTestCase):
    def setUp(self):
        super().setUp()
        self.issue = self.create_issue()
        self.rh_json(["work", "link", str(self.issue)])
        self.pass_gate(self.issue, "design")
        self.work = self.start_work(self.issue)

    def comments(self):
        return self.sandbox.gh_data()["issues"][str(self.issue)]["comments"]

    def test_records_land_as_issue_comments_with_markers(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nrun the sweep"])
        bodies = [c["body"] for c in self.comments()]
        self.assertTrue(any("rh:record" in body and '"kind":"checkpoint"' in body for body in bodies))

    def test_checkpoint_records_head_and_branch(self):
        self.commit()
        head = self.sandbox.git(self.repo, ["rev-parse", "HEAD"]).stdout.strip()
        payload = self.rh_json(["record", "checkpoint", "--body", "### Next Action\ngo"])
        self.assertEqual(payload["head"], head)
        marker = json.loads(self.comments()[-1]["body"].split("<!-- rh:record ", 1)[1].split(" -->", 1)[0])
        self.assertEqual(marker["head"], head)
        self.assertEqual(marker["branch"], self.work["branch"])

    def test_decision_requires_a_status(self):
        result = self.rh(["record", "decision", "--body", "x"])
        self.assertNotEqual(result.returncode, 0)

    def test_gate_requires_gate_and_outcome(self):
        result = self.rh(["record", "gate", "--body", "x"])
        self.assertNotEqual(result.returncode, 0)

    def test_state_advances_through_the_flow(self):
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "IN_PROGRESS")
        self.rh_json(["record", "checkpoint", "--phase", "validating", "--body", "### Next Action\nsweep"])
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "VALIDATING")
        self.rh_json(["record", "result", "--body", "### Observation\nno effect at layer 7"])
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "EVIDENCE_GATE")
        self.pass_gate(self.issue, "evidence")
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Next Action\nsynthesise"])
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "KNOWLEDGE_GATE")
        self.pass_gate(self.issue, "knowledge")
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "READY_TO_MERGE")

    def test_negative_result_completes_normally(self):
        """A hypothesis that was not supported is a finished experiment."""
        self.rh_json([
            "record", "result",
            "--body", "### Observation\nno separation\n\n### Supports\nnothing\n\n"
                      "### Does NOT Support\nthe chirality hypothesis\n\n"
                      "### Provenance\n- commit: abc1234\n- run ID: slurm-88213",
        ])
        self.pass_gate(self.issue, "evidence")
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Next Action\nwrite up"])
        self.pass_gate(self.issue, "knowledge")
        self.rh_json(["pr", "update", "--body-file", self.write(
            "_pr.md",
            "Refs #1\n\n## Purpose\n\nprobe\n\n## Does NOT Establish\n\n非線形保持の有無は区別できない。\n",
        )])
        (self.repo / "_pr.md").unlink()
        self.commit()
        payload = self.rh_json(["ready"])
        self.assertTrue(payload["ready"], payload["blockers"])
        self.assertEqual(payload["state"], "READY_TO_MERGE")

    def test_blocked_checkpoint_surfaces_as_a_blocker(self):
        self.rh_json([
            "record", "checkpoint", "--phase", "blocked",
            "--body", "### Blocked By\nthe GPU queue is down\n\n### Next Action\nwait",
        ])
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "BLOCKED")
        self.assertEqual(payload["blockers"], ["the GPU queue is down"])

    def test_deviation_gate_blocks_until_decided(self):
        self.pass_gate(self.issue, "deviation", outcome="blocked")
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "DEVIATION_GATE")
        self.rh_json(["record", "decision", "--status", "accepted", "--body", "### Decision\nswitch metric"])
        self.pass_gate(self.issue, "deviation", outcome="passed")
        self.assertNotEqual(self.rh_json(["status"])["state"]["state"], "DEVIATION_GATE")

    def test_ready_lists_blockers_and_exits_non_zero(self):
        result = self.rh(["ready"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOT READY_TO_MERGE", result.stdout)
        payload = json.loads(self.rh(["ready", "--json"]).stdout)
        self.assertFalse(payload["ready"])
        self.assertTrue(any("evidence gate" in b for b in payload["blockers"]))

    def test_dry_run_record_posts_nothing(self):
        before = len(self.comments())
        result = self.rh(["record", "checkpoint", "--body", "x", "--dry-run"], check=True)
        self.assertIn("[dry-run]", result.stdout)
        self.assertEqual(len(self.comments()), before)

    def test_pr_body_can_be_synthesised(self):
        synthesis = self.write("_pr.md", "## Purpose\n\nProbe layer 7.\n\n## Does NOT Establish\n\nCausality.\n")
        self.rh_json(["pr", "update", "--body-file", synthesis])
        self.assertIn("Does NOT Establish", self.sandbox.gh_data()["prs"][str(self.work["pr"])]["body"])

    def test_untracked_branch_reports_untracked(self):
        self.sandbox.git(self.repo, ["switch", "-c", "unrelated/branch"])
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "UNTRACKED")

    def test_record_without_a_linked_issue_is_refused(self):
        self.sandbox.git(self.repo, ["switch", "-c", "unrelated/branch"])
        result = self.rh(["record", "checkpoint", "--body", "x"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not linked to a Work Issue", result.stderr)


class AgentSwitchTests(LifecycleTestCase):
    """SPEC 64 E — a fresh session with no chat history must recover the work."""

    def test_resume_reconstructs_everything_from_durable_state(self):
        issue = self.create_issue()
        self.rh_json(["work", "link", str(issue)])
        self.pass_gate(issue, "design")
        self.start_work(issue)
        self.rh_json([
            "record", "decision", "--status", "accepted",
            "--body", "### Decision\nUse cosine similarity, not L2.\n\n### Rationale\nScale invariance.",
        ])
        self.rh_json([
            "record", "decision", "--status", "rejected",
            "--body", "### Decision\nRejected: switch datasets.",
        ])
        self.rh_json(["record", "result", "--body", "### Observation\nlayer 7 shows no separation"])
        self.commit("probe.py", "# probe\n", "add probe")
        self.rh_json([
            "record", "checkpoint",
            "--body", "### Done\nprobe implemented\n\n### Blocked By\nnone\n\n### Next Action\nsweep layers 4-9",
        ])
        self.commit("sweep.py", "# sweep\n", "start sweep")

        # A brand-new process, no cached conversation, only the repository.
        payload = self.rh_json(["resume"])
        self.assertEqual(payload["issue"]["number"], issue)
        self.assertIsNotNone(payload["pr"]["number"])
        self.assertEqual(len(payload["accepted_decisions"]), 1)
        self.assertIn("cosine similarity", payload["accepted_decisions"][0]["body"])
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["next_action"], "sweep layers 4-9")
        self.assertIn("sweep.py", payload["changes_since_checkpoint"])
        self.assertNotIn("probe.py", payload["changes_since_checkpoint"])
        self.assertIn("Probe layer 7 chirality.", payload["work_issue_body"])
        self.assertTrue(payload["workflow"].endswith("workflows/resume.md"))

    def test_records_are_readable_by_a_second_clone(self):
        """Claude records; Codex reads it back from GitHub, not from a cache."""
        issue = self.create_issue(risk="low", evidence=False)
        self.start_work(issue)
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nhand over to the other agent"])

        # The harness is committed like any other repository content, so a
        # fresh clone is self-contained: no distribution repo, no global install.
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "adopt research harness"], check=False)

        other = self.sandbox.base / "second-clone"
        self.sandbox.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        self.sandbox.git(other, ["switch", "-q", f"rh/{issue}-probe-layer-7"])
        payload = json.loads(
            self.sandbox.run(
                [sys.executable, str(other / ".research-harness" / "bin" / "rh"), "resume", "--json"],
                cwd=other,
                check=True,
            ).stdout
        )
        self.assertEqual(payload["issue"]["number"], issue)
        self.assertEqual(payload["next_action"], "hand over to the other agent")


class NoDestructiveOperationsTests(LifecycleTestCase):
    def test_no_merge_force_push_or_deletion_is_ever_invoked(self):
        issue = self.create_issue(risk="low", evidence=False)
        self.start_work(issue)
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Next Action\ndone"])
        self.commit()
        self.rh(["ready"])
        for call in self.sandbox.gh_calls():
            joined = " ".join(call)
            self.assertNotIn("pr merge", joined)
            self.assertNotIn("issue delete", joined)
            self.assertNotIn("--force", joined)

    def test_reflog_shows_no_history_rewrite(self):
        issue = self.create_issue(risk="low", evidence=False)
        self.commit("a.py", "# a\n", "commit a")
        before = self.sandbox.git(self.repo, ["log", "--all", "--format=%H"]).stdout.split()
        self.start_work(issue)
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nx"])
        after = self.sandbox.git(self.repo, ["log", "--all", "--format=%H"]).stdout.split()
        self.assertTrue(set(before) <= set(after), "no commit may disappear")


if __name__ == "__main__":
    unittest.main()


class HumanOutputTests(LifecycleTestCase):
    """Every command must render readable output, not only --json."""

    def test_human_readable_output_for_the_whole_flow(self):
        issue = self.create_issue(risk="medium", evidence=False)
        checks = [
            (["version"], "rh 0.1.0"),
            (["context"], "repo_root"),
            (["status"], "Derived State"),
            (["resume"], "next action"),
            (["audit"], "repository"),
            (["doctor"], "worst severity"),
        ]
        for args, expected in checks:
            with self.subTest(command=args[0]):
                result = self.rh(args)
                self.assertIn(expected, result.stdout)
                self.assertEqual(result.stderr, "")

        self.rh(["work", "link", str(issue)], check=True)
        self.assertIn("Pending Gates        design", self.rh(["status"], check=True).stdout)
        self.rh(["record", "gate", "--gate", "design", "--outcome", "passed", "--body", "### Outcome\npassed"], check=True)
        start = self.rh(["work", "start", str(issue)], check=True)
        self.assertIn("draft PR", start.stdout)
        self.assertIn("recorded checkpoint", self.rh(["record", "checkpoint", "--body", "### Next Action\ngo"], check=True).stdout)
        self.assertIn("NOT READY_TO_MERGE", self.rh(["ready"]).stdout)
        self.assertIn("pending", self.rh(["sync"], check=True).stdout)

    def test_untracked_status_renders_without_a_work_unit(self):
        result = self.rh(["status"], check=True)
        self.assertIn("Current Work         (none)", result.stdout)
        self.assertIn("UNTRACKED", result.stdout)

    def test_errors_go_to_stderr_with_a_hint(self):
        result = self.rh(["record", "checkpoint", "--body", "x"])
        self.assertEqual(result.stdout, "")
        self.assertIn("rh: ", result.stderr)
        self.assertIn("hint:", result.stderr)


class NextCommandGuidanceTests(LifecycleTestCase):
    """`rh status` must say what to do next, mechanically."""

    def test_status_names_the_next_command_at_each_stage(self):
        issue = self.create_issue()
        self.rh_json(["work", "link", str(issue)])

        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "DESIGN_GATE")
        self.assertIn(f"--gate design", payload["next_command"])
        self.assertIn(f"--issue {issue}", payload["next_command"])
        self.assertIn("passed|overridden", payload["next_command"])
        self.assertIn("Next Command", self.rh(["status"], check=True).stdout)

        self.pass_gate(issue, "design")
        self.assertIn(f"work start {issue}", self.rh_json(["status"])["next_command"])

        self.rh_json(["work", "start", str(issue)])
        # No PR yet — the branch has no commits, so that is the next step.
        self.assertEqual(self.rh_json(["status"])["next_command"], "rh pr create")
        self.commit("probe.py", "# probe\n", "begin work")
        self.sandbox.git(self.repo, ["push", "-q", "origin", "HEAD"])
        self.rh_json(["pr", "create"])
        # Implementation is under way; the evidence gate being open is not
        # evidence that an experiment is running.
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "IN_PROGRESS")
        self.assertIn("record checkpoint", self.rh_json(["status"])["next_command"])

        self.rh_json(["record", "checkpoint", "--phase", "validating", "--body", "### Next Action\nsweep"])
        self.assertEqual(self.rh_json(["status"])["state"]["state"], "VALIDATING")
        self.assertIn("record result", self.rh_json(["status"])["next_command"])

        self.rh_json(["record", "result", "--body", "### Observation\nx"])
        self.assertIn("--gate evidence", self.rh_json(["status"])["next_command"])

    def test_validating_after_the_evidence_gate_points_at_review(self):
        """Suggesting another result after the gate passed would misdirect."""
        issue = self.create_issue()
        self.rh_json(["work", "link", str(issue)])
        self.pass_gate(issue, "design")
        self.start_work(issue)
        self.rh_json(["record", "checkpoint", "--phase", "validating", "--body", "### Next Action\nsweep"])
        self.assertIn("record result", self.rh_json(["status"])["next_command"])
        self.rh_json(["record", "result", "--body", "### Observation\nx"])
        self.pass_gate(issue, "evidence")
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "VALIDATING")
        self.assertEqual(payload["next_command"], "rh record checkpoint --phase review")

    def test_terminal_state_explains_why_there_is_no_command(self):
        issue = self.create_issue(risk="low", evidence=False)
        self.start_work(issue)
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Next Action\ndone"])
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "READY_TO_MERGE")
        self.assertIsNone(payload["next_command"])
        self.assertIn("researcher merges", payload["next_command_note"])
        self.assertIn("(none —", self.rh(["status"], check=True).stdout)

    def test_untracked_branch_still_offers_a_way_in(self):
        self.sandbox.git(self.repo, ["switch", "-c", "unrelated"])
        payload = self.rh_json(["status"])
        self.assertEqual(payload["state"]["state"], "UNTRACKED")
        self.assertIn("work link", payload["next_command"])


class StructuralReadyTests(LifecycleTestCase):
    """Evidence-required work must state its limits and its provenance."""

    def setUp(self):
        super().setUp()
        self.issue = self.create_issue()
        self.rh_json(["work", "link", str(self.issue)])
        self.pass_gate(self.issue, "design")
        self.work = self.start_work(self.issue)
        self.pass_gate(self.issue, "evidence")
        self.pass_gate(self.issue, "knowledge")
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Blocked By\nnone"])

    def record_result(self, *, provenance=True):
        body = "### Observation\nAUROC 0.52\n\n### Does NOT Support\n情報の消失"
        if provenance:
            body += "\n\n### Provenance\n- commit: abc1234\n- run ID: slurm-88213"
        else:
            body += "\n\n### Provenance\n- commit:\n- run ID:"
        self.rh_json(["record", "result", "--body", body])

    def set_pr_body(self, does_not_establish):
        body = "Refs #1\n\n## Purpose\n\nprobe\n\n## Does NOT Establish\n\n" + does_not_establish
        path = self.write("_pr.md", body)
        self.rh_json(["pr", "update", "--body-file", path])
        (self.repo / "_pr.md").unlink()

    def test_empty_does_not_establish_blocks(self):
        self.record_result()
        self.set_pr_body("<!-- filled in by rh-finish -->\n")
        self.commit()
        payload = json.loads(self.rh(["ready", "--json"]).stdout)
        self.assertFalse(payload["ready"])
        self.assertTrue(any("does NOT establish" in b for b in payload["blockers"]))

    def test_unfilled_provenance_blocks(self):
        self.record_result(provenance=False)
        self.set_pr_body("非線形保持は区別できない。\n")
        self.commit()
        payload = json.loads(self.rh(["ready", "--json"]).stdout)
        self.assertFalse(payload["ready"])
        self.assertTrue(any("Provenance" in b for b in payload["blockers"]))

    def test_both_filled_passes(self):
        self.record_result()
        self.set_pr_body("非線形保持は区別できない。\n")
        self.commit()
        payload = self.rh_json(["ready"])
        self.assertTrue(payload["ready"], payload["blockers"])

    def test_config_can_disable_the_checks(self):
        config = self.repo / ".research-harness" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8")
            .replace("require_does_not_establish = true", "require_does_not_establish = false")
            .replace("require_provenance = true", "require_provenance = false"),
            encoding="utf-8",
        )
        self.record_result(provenance=False)
        self.set_pr_body("<!-- filled in by rh-finish -->\n")
        self.commit()
        self.assertTrue(self.rh_json(["ready"])["ready"])

    def test_low_risk_work_is_unaffected(self):
        number = self.create_issue(title="Rename helper", kind="refactor", risk="low", evidence=False)
        self.start_work(number, seed="rename.py")
        self.rh_json(["record", "checkpoint", "--phase", "review", "--body", "### Blocked By\nnone"])
        self.commit("helper.py", "# helper\n", "rename")
        self.assertTrue(self.rh_json(["ready"])["ready"])

    def test_offline_warns_instead_of_blocking(self):
        """Being unable to read the PR body must not stop finished work."""
        self.record_result()
        self.set_pr_body("非線形保持は区別できない。\n")
        self.commit()
        payload = self.rh_json(["--offline", "ready"])
        self.assertTrue(payload["ready"])
        self.assertTrue(any("not checked" in w for w in payload["warnings"]))


class IssueCloseTests(LifecycleTestCase):
    """SPEC 24: an experiment does not close just because a PR merged."""

    def test_evidence_required_work_will_not_close_without_evidence(self):
        issue = self.create_issue()
        result = self.rh(["issue", "close", str(issue)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a scientific conclusion", result.stderr)
        self.assertIn("evidence gate", result.stderr)
        self.assertEqual(self.sandbox.gh_data()["issues"][str(issue)]["state"], "OPEN")

    def test_closes_once_the_result_and_evidence_gate_exist(self):
        issue = self.create_issue()
        self.rh_json(["record", "result", "--issue", str(issue), "--body", "### Observation\nx"])
        self.pass_gate(issue, "evidence")
        self.rh_json(["issue", "close", str(issue), "--comment", "evidence recorded"])
        self.assertEqual(self.sandbox.gh_data()["issues"][str(issue)]["state"], "CLOSED")

    def test_implementation_work_closes_freely(self):
        issue = self.create_issue(title="Add loader", kind="implementation", risk="low", evidence=False)
        self.rh_json(["issue", "close", str(issue)])
        self.assertEqual(self.sandbox.gh_data()["issues"][str(issue)]["state"], "CLOSED")

    def test_force_overrides_the_precondition(self):
        issue = self.create_issue()
        self.rh_json(["issue", "close", str(issue), "--force"])
        self.assertEqual(self.sandbox.gh_data()["issues"][str(issue)]["state"], "CLOSED")

    def test_dry_run_closes_nothing(self):
        issue = self.create_issue(risk="low", evidence=False)
        self.rh(["issue", "close", str(issue), "--dry-run"], check=True)
        self.assertEqual(self.sandbox.gh_data()["issues"][str(issue)]["state"], "OPEN")

    def test_closing_twice_is_harmless(self):
        issue = self.create_issue(risk="low", evidence=False)
        self.rh_json(["issue", "close", str(issue)])
        payload = self.rh_json(["issue", "close", str(issue)])
        self.assertFalse(payload["changed"])

    def test_no_command_can_delete_an_issue(self):
        """Closing is reversible; deletion is never offered."""
        help_text = self.rh(["issue", "--help"], check=True).stdout
        subcommands = help_text.split("{", 1)[1].split("}", 1)[0].split(",")
        self.assertEqual(sorted(subcommands), ["close", "create"])
        result = self.rh(["issue", "delete", "1"])
        self.assertNotEqual(result.returncode, 0)
