"""The mandatory acceptance scenarios from SPEC 64, end to end.

These run the vendored runtime inside an adopted repository, against the fake
`gh`, in an isolated HOME — the same conditions a researcher would have,
minus the real network.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class ScenarioTestCase(SandboxTestCase):
    def rh_dist(self, args, **kw):
        return self.sandbox.rh(args, cwd=self.sandbox.base, **kw)

    def rh(self, repo, args, *, check=False, env=None):
        return self.sandbox.rh_local(repo, args, check=check, env=env)

    def rh_json(self, repo, args, *, env=None):
        return json.loads(self.rh(repo, [*args, "--json"], check=True, env=env).stdout)


class ScenarioC_ExistingProjectMigration(ScenarioTestCase):
    """audit → researcher correction → baseline → adopt the active work."""

    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo("legacy")
        (self.repo / "experiments").mkdir()
        (self.repo / "experiments" / "sweep_v3.py").write_text("# the current experiment\n", encoding="utf-8")
        (self.repo / "results").mkdir()
        (self.repo / "results" / "sweep_v2.json").write_text("{}\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("# AGENTS.md\n\nLab rule: never delete results/.\n", encoding="utf-8")
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "eighteen months of research"])
        self.sandbox.git(self.repo, ["switch", "-q", "-c", "sweep-v3"])
        self.sandbox.git(self.repo, ["switch", "-q", "-c", "abandoned-idea"])
        self.sandbox.git(self.repo, ["switch", "-q", "sweep-v3"])
        (self.repo / "experiments" / "sweep_v3.py").write_text("# in-flight edit\n", encoding="utf-8")

    def test_migration_is_overlay_not_reconstruction(self):
        commits_before = self.sandbox.git(self.repo, ["log", "--all", "--format=%H"]).stdout.split()
        branches_before = sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())

        self.rh_dist(["adopt", str(self.repo)], check=True)

        # 1. The agent gets an unclassified inventory to reason over.
        audit = self.rh_json(self.repo, ["audit"])
        self.assertIn("sweep-v3", audit["branches"])
        self.assertIn("abandoned-idea", audit["branches"])
        self.assertIn("experiments", audit["candidate_experiment_dirs"])
        self.assertIn("results", audit["candidate_result_dirs"])

        # 2. A baseline stub exists for the researcher to correct.
        baseline = (self.repo / ".research-harness" / "baseline.md").read_text(encoding="utf-8")
        for heading in ("Current Research Objectives", "Active Work", "Deferred Work", "Abandoned Work",
                        "Important Historical Decisions", "Known Cognitive Debt", "Immediate Next Work"):
            self.assertIn(heading, baseline)
        self.assertIn("never mark existing work abandoned on an", baseline)

        # 3. History is preserved: nothing rewritten, nothing renamed.
        self.assertEqual(self.sandbox.git(self.repo, ["log", "--all", "--format=%H"]).stdout.split(), commits_before)
        self.assertEqual(
            sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split()), branches_before
        )
        self.assertEqual((self.repo / "experiments" / "sweep_v3.py").read_text(encoding="utf-8"), "# in-flight edit\n")
        self.assertIn("never delete results/.", (self.repo / "AGENTS.md").read_text(encoding="utf-8"))

        # 4. The in-flight branch is adopted as tracked work without renaming.
        issue = self.rh_json(
            self.repo,
            ["issue", "create", "--title", "Finish sweep v3", "--kind", "experiment", "--risk", "medium",
             "--evidence-required", "--body", "## Purpose\n\nFinish the sweep already in flight."],
        )["issue"]
        self.rh_json(self.repo, ["work", "link", str(issue)])
        self.rh_json(self.repo, ["record", "gate", "--gate", "design", "--outcome", "passed", "--body", "### Outcome\npassed"])
        payload = self.rh_json(self.repo, ["work", "start", str(issue), "--existing-branch", "sweep-v3"])
        self.assertEqual(payload["branch"], "sweep-v3")
        self.assertIn("sweep-v3", self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())
        self.assertEqual((self.repo / "experiments" / "sweep_v3.py").read_text(encoding="utf-8"), "# in-flight edit\n")

        # 5. No historical reconstruction: exactly one Issue, not one per commit.
        self.assertEqual(len(self.sandbox.gh_data()["issues"]), 1)


class ScenarioH_KnowledgeGate(ScenarioTestCase):
    """A researcher who cannot yet own the work does not reach READY_TO_MERGE."""

    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.rh_dist(["adopt", str(self.repo)], check=True)
        self.issue = self.rh_json(
            self.repo,
            ["issue", "create", "--title", "Chirality probe", "--kind", "analysis", "--risk", "medium",
             "--body", "## Purpose\n\nProbe."],
        )["issue"]
        self.rh_json(self.repo, ["work", "link", str(self.issue)])
        self.rh_json(self.repo, ["record", "gate", "--gate", "design", "--outcome", "passed", "--body", "### Outcome\npassed"])
        self.rh_json(self.repo, ["work", "start", str(self.issue)])
        (self.repo / "probe.py").write_text("# probe\n", encoding="utf-8")
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "probe"])
        self.rh_json(self.repo, ["record", "checkpoint", "--phase", "review", "--body", "### Blocked By\nnone\n\n### Next Action\nsynthesise"])

    def test_blocked_knowledge_gate_prevents_ready(self):
        self.rh_json(
            self.repo,
            ["record", "gate", "--gate", "knowledge", "--outcome", "blocked",
             "--body", "### Unresolved\nresearcher could not state what the validation does not cover"],
        )
        status = self.rh_json(self.repo, ["status"])
        self.assertEqual(status["state"]["state"], "KNOWLEDGE_GATE")
        result = self.rh(self.repo, ["ready", "--json"])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)["ready"])

    def test_repair_then_restatement_reaches_ready(self):
        self.rh_json(self.repo, ["record", "gate", "--gate", "knowledge", "--outcome", "blocked", "--body", "### Unresolved\nconfounders"])
        self.rh_json(
            self.repo,
            ["record", "gate", "--gate", "knowledge", "--outcome", "repaired",
             "--body", "### Misconceptions Repaired\nconflated correlation with the causal claim\n\n### Outcome\nrepaired"],
        )
        self.assertEqual(self.rh_json(self.repo, ["status"])["state"]["state"], "READY_TO_MERGE")
        payload = self.rh_json(self.repo, ["ready"])
        self.assertTrue(payload["ready"])

    def test_override_is_recorded_as_the_researchers_choice(self):
        self.rh_json(
            self.repo,
            ["record", "gate", "--gate", "knowledge", "--outcome", "overridden",
             "--body", "### Outcome\noverridden\n\nExploratory prototype; the researcher chose to skip."],
        )
        self.assertTrue(self.rh_json(self.repo, ["ready"])["ready"])
        comments = self.sandbox.gh_data()["issues"][str(self.issue)]["comments"]
        override = next(c for c in comments if '"outcome":"overridden"' in c["body"])
        self.assertIn("researcher chose to skip", override["body"])

    def test_harness_never_merges_even_when_ready(self):
        self.rh_json(self.repo, ["record", "gate", "--gate", "knowledge", "--outcome", "passed", "--body", "### Outcome\npassed"])
        self.assertTrue(self.rh_json(self.repo, ["ready"])["ready"])
        for call in self.sandbox.gh_calls():
            self.assertNotEqual(call[:2], ["pr", "merge"])
        pr = self.sandbox.gh_data()["prs"]
        self.assertTrue(all(item["state"] == "OPEN" and item["isDraft"] for item in pr.values()))


class ScenarioSelfContainment(ScenarioTestCase):
    """SPEC 70.2 — an adopted repository must not need the distribution repo."""

    def test_vendored_runtime_executes_from_the_target_only(self):
        repo = self.sandbox.make_repo()
        self.rh_dist(["adopt", str(repo)], check=True)
        payload = self.rh_json(repo, ["version"])
        self.assertTrue(
            payload["runtime_path"].startswith(str(repo)),
            f"vendored rh executed {payload['runtime_path']}, not the target's own runtime",
        )
        self.assertNotIn(str(support.REPO_ROOT / "src"), payload["runtime_path"])

    def test_a_relocated_copy_still_works(self):
        repo = self.sandbox.make_repo()
        self.rh_dist(["adopt", str(repo)], check=True)
        self.sandbox.git(repo, ["add", "-A"])
        self.sandbox.git(repo, ["commit", "-q", "-m", "adopt harness"])
        moved = self.sandbox.base / "relocated" / "project"
        moved.parent.mkdir(parents=True)
        shutil.copytree(repo, moved)
        payload = json.loads(
            self.sandbox.run(
                [sys.executable, str(moved / ".research-harness" / "bin" / "rh"), "version", "--json"],
                cwd=moved,
                check=True,
            ).stdout
        )
        self.assertTrue(payload["runtime_path"].startswith(str(moved)))
        self.sandbox.run(
            [sys.executable, str(moved / ".research-harness" / "bin" / "rh"), "doctor"], cwd=moved
        )


if __name__ == "__main__":
    unittest.main()
