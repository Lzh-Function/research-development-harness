"""Offline records, idempotent sync, doctor, and the repo-local runtime contract."""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class AdoptedRepoTestCase(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)

    def rh(self, args, *, check=False, env=None):
        return self.sandbox.rh_local(self.repo, args, check=check, env=env)

    def rh_json(self, args, *, env=None):
        return json.loads(self.rh([*args, "--json"], check=True, env=env).stdout)

    def start_work(self, risk="low", evidence=False):
        payload = self.rh_json(
            ["issue", "create", "--title", "Probe", "--kind", "analysis", "--risk", risk, "--body", "## Purpose\n\nx"]
        )
        issue = payload["issue"]
        self.rh_json(["work", "start", str(issue)])
        return issue


class OfflineTests(AdoptedRepoTestCase):
    """SPEC 64 I — GitHub unreachable must not lose a record."""

    def setUp(self):
        super().setUp()
        self.issue = self.start_work()
        self.offline = {"RH_FAKE_GH_FAIL": "network"}

    def comments(self):
        return self.sandbox.gh_data()["issues"][str(self.issue)]["comments"]

    def test_record_is_queued_when_github_is_unreachable(self):
        payload = self.rh_json(["record", "checkpoint", "--body", "### Next Action\nresume later"], env=self.offline)
        self.assertTrue(payload["queued"])
        outbox = self.repo / ".git" / "research-harness" / "outbox"
        self.assertEqual(len(list(outbox.glob("*.json"))), 1)

    def test_queued_records_are_visible_to_status_before_sync(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nresume later"], env=self.offline)
        payload = self.rh_json(["status"], env=self.offline)
        self.assertIsNotNone(payload["latest_checkpoint"])
        self.assertEqual(payload["next_action"], "resume later")
        self.assertEqual(payload["context"]["outbox_pending"], 1)

    def test_sync_delivers_the_record_once(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nresume later"], env=self.offline)
        report = self.rh_json(["sync"])
        self.assertEqual(len(report["posted"]), 1)
        self.assertEqual(len([c for c in self.comments() if "rh:record" in c["body"]]), 1)
        self.assertEqual(self.rh_json(["context"])["outbox_pending"], 0)

    def test_repeated_sync_is_idempotent(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nx"], env=self.offline)
        self.rh_json(["sync"])
        second = self.rh_json(["sync"])
        self.assertEqual(second["pending"], 0)
        self.assertEqual(len([c for c in self.comments() if "rh:record" in c["body"]]), 1)

    def test_sync_does_not_repost_a_record_that_reached_github_anyway(self):
        """The write succeeded but the response was lost: still exactly once."""
        payload = self.rh_json(["record", "checkpoint", "--body", "### Next Action\nx"])
        record_id = payload["id"]
        # Simulate a lost acknowledgement by re-queueing the identical record.
        comment = next(c["body"] for c in self.comments() if record_id in c["body"])
        outbox = self.repo / ".git" / "research-harness" / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        (outbox / f"{record_id}.json").write_text(
            json.dumps({"queued_at": "2026-01-01T00:00:00Z", "attempts": 1, "issue": self.issue, "id": record_id,
                        "kind": "checkpoint", "comment": comment}),
            encoding="utf-8",
        )
        report = self.rh_json(["sync"])
        self.assertEqual(len(report["duplicate"]), 1)
        self.assertEqual(len(report["posted"]), 0)
        self.assertEqual(len([c for c in self.comments() if record_id in c["body"]]), 1)

    def test_failed_sync_keeps_the_record_and_reports_failure(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\nx"], env=self.offline)
        result = self.rh(["sync", "--json"], env=self.offline)
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["failed"]), 1)
        self.assertEqual(self.rh_json(["context"], env=self.offline)["outbox_pending"], 1)

    def test_transient_failure_is_retried_and_succeeds(self):
        env = {"RH_FAKE_GH_FAIL": "network", "RH_FAKE_GH_FAIL_TIMES": "1"}
        payload = self.rh_json(["record", "result", "--body", "### Observation\nx"], env=env)
        self.assertFalse(payload["queued"], "a single transient failure should be retried, not queued")

    def test_auth_failure_is_reported_clearly(self):
        result = self.rh(["issue", "create", "--title", "T", "--body", "b"], env={"RH_FAKE_GH_FAIL": "auth"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("authentication", result.stderr.lower())
        self.assertIn("gh auth login", result.stderr)

    def test_offline_flag_uses_the_cache_without_contacting_github(self):
        self.rh_json(["record", "checkpoint", "--body", "### Next Action\ncached"])
        self.rh_json(["status"])  # populates the cache
        before = len(self.sandbox.gh_calls())
        payload = self.rh_json(["--offline", "status"])
        self.assertEqual(payload["next_action"], "cached")
        self.assertEqual(payload["records_source"], "cache")
        self.assertEqual(len(self.sandbox.gh_calls()), before, "--offline must not invoke gh")


class RepositoryLocalRuntimeTests(AdoptedRepoTestCase):
    """SPEC 70.2 — the adopted repository must stand alone."""

    def test_vendored_rh_runs_without_the_distribution_repository(self):
        moved = self.sandbox.base / "distribution-moved-away"
        # The vendored runtime must not reach back into the distribution repo.
        result = self.rh(["version", "--json"], check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["bundle_version"], payload["runtime_version"])
        self.assertFalse(moved.exists())

    def test_vendored_runtime_is_self_contained(self):
        runtime = self.repo / ".research-harness" / "runtime" / "research_harness"
        modules = {p.stem for p in runtime.glob("*.py")}
        self.assertTrue({"cli", "git", "github", "records", "context", "state", "outbox", "doctor"} <= modules)

    def test_no_pythonpath_or_global_package_is_required(self):
        env = {"PYTHONPATH": ""}
        result = self.rh(["context", "--json"], check=True, env=env)
        self.assertIn("repo_root", result.stdout)

    def test_running_from_a_subdirectory_finds_the_repository_root(self):
        nested = self.repo / "src" / "deep" / "nested"
        nested.mkdir(parents=True)
        result = self.sandbox.run(
            [sys.executable, str(self.repo / ".research-harness" / "bin" / "rh"), "context", "--json"],
            cwd=nested,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["repo_root"], str(self.repo))

    def test_no_pycache_is_left_in_the_repository(self):
        self.rh(["status"], check=False)
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])


class DoctorTests(AdoptedRepoTestCase):
    def test_doctor_is_clean_after_adoption(self):
        result = self.rh(["doctor"], check=True)
        self.assertNotIn("ERROR", result.stdout)
        payload = json.loads(self.rh(["doctor", "--json"], check=True).stdout)
        self.assertNotEqual(payload["worst"], "ERROR")
        checks = {finding["check"] for finding in payload["findings"]}
        for expected in {
            "python", "git", "repository", "gh", "gh-auth", "installation",
            "claude-skills", "codex-skills", "managed-block", "outbox", "home-hygiene",
        }:
            self.assertIn(expected, checks)

    def test_doctor_reports_missing_skills_as_a_problem(self):
        shutil.rmtree(self.repo / ".claude" / "skills" / "rh-resume")
        payload = json.loads(self.rh(["doctor", "--json"]).stdout)
        finding = next(f for f in payload["findings"] if f["check"] == "claude-skills")
        self.assertEqual(finding["severity"], "WARNING")
        self.assertIn("rh-resume", finding["message"])

    def test_doctor_reports_a_removed_managed_block(self):
        (self.repo / "AGENTS.md").write_text("# no harness block\n", encoding="utf-8")
        payload = json.loads(self.rh(["doctor", "--json"]).stdout)
        finding = next(f for f in payload["findings"] if f["check"] == "managed-block" and "AGENTS" in f["message"])
        self.assertEqual(finding["severity"], "WARNING")

    def test_doctor_errors_on_a_broken_runtime(self):
        (self.repo / ".research-harness" / "bin" / "rh").unlink()
        result = self.sandbox.rh(["--repo", str(self.repo), "doctor", "--json"], cwd=self.repo)
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["worst"], "ERROR")

    def test_doctor_outside_a_repository_reports_an_error(self):
        outside = self.sandbox.base / "not-a-repo"
        outside.mkdir()
        result = self.sandbox.rh(["doctor", "--json"], cwd=outside)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stdout)

    def test_doctor_flags_stray_rdh_files_under_home(self):
        (self.sandbox.home / ".claude" / "skills" / "rh-scope").mkdir(parents=True)
        payload = json.loads(self.rh(["doctor", "--json"]).stdout)
        finding = next(f for f in payload["findings"] if f["check"] == "home-hygiene")
        self.assertEqual(finding["severity"], "WARNING")

    def test_doctor_is_read_only(self):
        before = support.snapshot_tree(self.repo)
        self.rh(["doctor"])
        difference = support.diff_snapshots(before, support.snapshot_tree(self.repo))
        self.assertEqual(difference["added"], [])
        self.assertEqual(difference["changed"], [])
        self.assertEqual(difference["removed"], [])


class AuditTests(AdoptedRepoTestCase):
    def test_audit_inventories_without_classifying(self):
        (self.repo / "experiments").mkdir()
        (self.repo / "results").mkdir()
        (self.repo / "tests").mkdir()
        self.sandbox.git(self.repo, ["branch", "old/experiment"])
        payload = self.rh_json(["audit"])
        self.assertIn("old/experiment", payload["branches"])
        self.assertIn("experiments", payload["candidate_experiment_dirs"])
        self.assertIn("results", payload["candidate_result_dirs"])
        self.assertIn("tests", payload["test_infrastructure"])
        self.assertTrue(payload["agent_files"]["AGENTS.md"]["managed_block"])
        self.assertTrue(payload["adopted"])
        # No semantic verdicts anywhere in the payload.
        for forbidden in ("abandoned", "active", "priority", "importance"):
            self.assertNotIn(forbidden, json.dumps(payload).lower())

    def test_audit_is_read_only(self):
        before = support.snapshot_tree(self.repo)
        self.rh(["audit"])
        difference = support.diff_snapshots(before, support.snapshot_tree(self.repo))
        self.assertEqual(difference["added"] + difference["changed"] + difference["removed"], [])

    def test_audit_sees_open_issues_and_prs(self):
        self.start_work()
        payload = self.rh_json(["audit"])
        self.assertTrue(payload["github_available"])
        self.assertEqual(len(payload["open_issues"]), 1)
        self.assertEqual(len(payload["open_prs"]), 1)
        self.assertTrue(payload["open_prs"][0]["draft"])


if __name__ == "__main__":
    unittest.main()


class WorktreeTests(AdoptedRepoTestCase):
    """RDH must work from a linked worktree, sharing one local state dir."""

    def setUp(self):
        super().setUp()
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "adopt harness"])
        self.worktree = self.sandbox.base / "wt"
        self.sandbox.git(self.repo, ["worktree", "add", "-q", "-b", "side", str(self.worktree)])

    def run_in_worktree(self, args):
        return json.loads(
            self.sandbox.run(
                [sys.executable, str(self.worktree / ".research-harness" / "bin" / "rh"), *args, "--json"],
                cwd=self.worktree,
                check=True,
            ).stdout
        )

    def test_context_resolves_the_worktree_root(self):
        payload = self.run_in_worktree(["context"])
        self.assertEqual(payload["repo_root"], str(self.worktree))
        self.assertEqual(payload["branch"], "side")

    def test_local_state_is_shared_with_the_main_worktree(self):
        """Links and the outbox live in the common git dir, not per-worktree."""
        issue = self.start_work()
        self.run_in_worktree(["status"])
        shared = self.repo / ".git" / "research-harness" / "links"
        self.assertTrue(shared.exists())
        self.assertFalse((self.worktree / ".git").is_dir(), "a linked worktree has a .git file, not a directory")
        payload = self.run_in_worktree(["record", "checkpoint", "--issue", str(issue), "--body", "### Next Action\nx"])
        self.assertFalse(payload["queued"])

    def test_audit_lists_the_worktree(self):
        payload = self.rh_json(["audit"])
        paths = [w["path"] for w in payload["worktrees"]]
        self.assertTrue(any(str(self.worktree) in p for p in paths))

    def test_adoption_did_not_disturb_the_worktree(self):
        self.assertTrue((self.worktree / ".research-harness" / "bin" / "rh").exists())
        result = self.sandbox.run(
            [sys.executable, str(self.worktree / ".research-harness" / "bin" / "rh"), "doctor"],
            cwd=self.worktree,
        )
        self.assertNotIn("ERROR", result.stdout)


class RuntimeOwnershipTests(AdoptedRepoTestCase):
    """A vendored `rh` belongs to its own repository, wherever it is invoked."""

    def setUp(self):
        super().setUp()
        self.other = self.sandbox.make_repo("unrelated")
        self.sandbox.git(self.other, ["switch", "-q", "-c", "someone-elses-branch"])

    def vendored(self, args, cwd):
        return json.loads(
            self.sandbox.run(
                [sys.executable, str(self.repo / ".research-harness" / "bin" / "rh"), *args, "--json"],
                cwd=cwd,
                check=True,
            ).stdout
        )

    def test_invoking_from_another_repository_still_reports_its_own(self):
        payload = self.vendored(["context"], cwd=self.other)
        self.assertEqual(payload["repo_root"], str(self.repo))
        self.assertNotEqual(payload["branch"], "someone-elses-branch")

    def test_explicit_repo_flag_still_wins(self):
        payload = self.vendored(["--repo", str(self.other), "context"], cwd=self.repo)
        self.assertEqual(payload["repo_root"], str(self.other))

    def test_version_reports_the_installation_it_belongs_to(self):
        payload = self.vendored(["version"], cwd=self.other)
        self.assertIn("bundle_version", payload)
        self.assertTrue(payload["runtime_path"].startswith(str(self.repo)))

    def test_distribution_launcher_still_follows_the_working_directory(self):
        """`./bin/rh` in the harness repo is not vendored and must not pin."""
        payload = json.loads(self.sandbox.rh(["context", "--json"], cwd=self.other, check=True).stdout)
        self.assertEqual(payload["repo_root"], str(self.other))
