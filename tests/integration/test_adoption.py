"""Adoption into fresh and existing repositories (SPEC 64 A/B, 48, 54)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402

EXISTING_AGENTS = """# AGENTS.md

Codex: always run `make lint` before committing.

## Data policy

Never commit raw recordings.
"""

EXISTING_CLAUDE = """# CLAUDE.md

Use uv, not pip.
"""


class FreshAdoptionTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()

    def adopt(self, *extra):
        return self.sandbox.rh(["adopt", str(self.repo), *extra], cwd=self.sandbox.base, check=True)

    def test_installs_the_full_layout(self):
        self.adopt()
        harness = self.repo / ".research-harness"
        for relative in (
            "manifest.toml",
            "config.toml",
            "baseline.md",
            "inventory.json",
            "bin/rh",
            "runtime/research_harness/cli.py",
            "runtime/research_harness/github.py",
            "policy/workflow.md",
            "policy/human-gates.md",
            "policy/records.md",
            "policy/safety.md",
            "workflows/resume.md",
            "workflows/_common.md",
            "templates/checkpoint.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((harness / relative).exists(), f"missing {relative}")

    def test_vendored_launcher_is_executable(self):
        self.adopt()
        launcher = self.repo / ".research-harness" / "bin" / "rh"
        self.assertTrue(launcher.stat().st_mode & 0o111, "vendored rh must be executable")

    def test_both_agent_skill_trees_are_installed(self):
        self.adopt()
        expected = {"rh-scope", "rh-start", "rh-checkpoint", "rh-resume", "rh-status", "rh-decision", "rh-result", "rh-finish"}
        for base in (self.repo / ".claude" / "skills", self.repo / ".agents" / "skills"):
            with self.subTest(base=base.name):
                self.assertEqual({p.name for p in base.iterdir()}, expected)
                for name in expected:
                    self.assertTrue((base / name / "SKILL.md").exists())

    def test_skills_are_thin_adapters_not_workflow_copies(self):
        self.adopt()
        canonical = (self.repo / ".research-harness" / "workflows" / "resume.md").read_text(encoding="utf-8")
        skill = (self.repo / ".claude" / "skills" / "rh-resume" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(skill), len(canonical) * 1.5)
        self.assertIn(".research-harness/workflows/resume.md", skill)
        # The long workflow prose must live in exactly one place.
        distinctive = "WHY               the research question this serves"
        self.assertIn(distinctive, canonical)
        self.assertNotIn(distinctive, skill)

    def test_claude_and_codex_skills_share_the_canonical_source(self):
        self.adopt()
        claude = (self.repo / ".claude" / "skills" / "rh-checkpoint" / "SKILL.md").read_text(encoding="utf-8")
        codex = (self.repo / ".agents" / "skills" / "rh-checkpoint" / "SKILL.md").read_text(encoding="utf-8")
        for text in (claude, codex):
            self.assertIn(".research-harness/workflows/checkpoint.md", text)
            self.assertTrue(text.startswith("---\nname: rh-checkpoint\n"))

    def test_managed_blocks_are_created(self):
        self.adopt()
        for name in ("AGENTS.md", "CLAUDE.md"):
            text = (self.repo / name).read_text(encoding="utf-8")
            self.assertIn("<!-- BEGIN RESEARCH-HARNESS -->", text)
            self.assertIn("<!-- END RESEARCH-HARNESS -->", text)
            self.assertIn("Research Development Harness", text)

    def test_source_files_are_untouched(self):
        before = support.snapshot_tree(self.repo / "README.md")
        original = (self.repo / "README.md").read_text(encoding="utf-8")
        self.adopt()
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), original)
        self.assertEqual(support.snapshot_tree(self.repo / "README.md"), before)

    def test_git_history_and_branch_are_untouched(self):
        head_before = self.sandbox.git(self.repo, ["rev-parse", "HEAD"]).stdout.strip()
        log_before = self.sandbox.git(self.repo, ["log", "--oneline"]).stdout
        self.adopt()
        self.assertEqual(self.sandbox.git(self.repo, ["rev-parse", "HEAD"]).stdout.strip(), head_before)
        self.assertEqual(self.sandbox.git(self.repo, ["log", "--oneline"]).stdout, log_before)
        self.assertEqual(self.sandbox.git(self.repo, ["branch", "--show-current"]).stdout.strip(), "main")

    def test_adopt_does_not_commit(self):
        self.adopt()
        status = self.sandbox.git(self.repo, ["status", "--porcelain"]).stdout
        self.assertIn(".research-harness/", status)
        self.assertEqual(len(self.sandbox.git(self.repo, ["log", "--oneline"]).stdout.strip().splitlines()), 1)

    def test_dry_run_writes_nothing(self):
        before = support.snapshot_tree(self.repo)
        result = self.sandbox.rh(["adopt", str(self.repo), "--dry-run"], cwd=self.sandbox.base, check=True)
        self.assertIn("Would adopt", result.stdout)
        self.assertEqual(support.snapshot_tree(self.repo), before)

    def test_adopting_a_non_git_directory_is_refused(self):
        plain = self.sandbox.base / "plain"
        plain.mkdir()
        result = self.sandbox.rh(["adopt", str(plain)], cwd=self.sandbox.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a Git repository", result.stderr)

    def test_adopting_a_missing_directory_is_refused(self):
        result = self.sandbox.rh(["adopt", str(self.sandbox.base / "nope")], cwd=self.sandbox.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stderr)

    def test_self_adoption_is_refused(self):
        result = self.sandbox.rh(["adopt", str(support.REPO_ROOT)], cwd=self.sandbox.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("into itself", result.stderr)

    def test_repeated_adoption_is_idempotent(self):
        self.adopt()
        after_first = support.snapshot_tree(self.repo)
        result = self.adopt()
        after_second = support.snapshot_tree(self.repo)
        difference = support.diff_snapshots(after_first, after_second)
        # Only the regenerated manifest may differ (it carries a timestamp).
        self.assertEqual(difference["added"], [])
        self.assertEqual(difference["removed"], [])
        self.assertTrue(set(difference["changed"]) <= {".research-harness/manifest.toml", ".research-harness/inventory.json"})
        self.assertIn("unchanged", result.stdout)


class ExistingRepositoryAdoptionTests(SandboxTestCase):
    """The hard case: a real repository already in flight."""

    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        (self.repo / "AGENTS.md").write_text(EXISTING_AGENTS, encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text(EXISTING_CLAUDE, encoding="utf-8")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "model.py").write_text("def train():\n    ...\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_model.py").write_text("def test_train():\n    ...\n", encoding="utf-8")
        (self.repo / ".claude" / "skills" / "lab-style").mkdir(parents=True)
        (self.repo / ".claude" / "skills" / "lab-style" / "SKILL.md").write_text("---\nname: lab-style\n---\n", encoding="utf-8")
        (self.repo / ".agents" / "skills" / "lab-style").mkdir(parents=True)
        (self.repo / ".agents" / "skills" / "lab-style" / "SKILL.md").write_text("---\nname: lab-style\n---\n", encoding="utf-8")
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex" / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "existing project"])
        # Multiple branches, one of them checked out with dirty work.
        self.sandbox.git(self.repo, ["branch", "experiment/alpha"])
        self.sandbox.git(self.repo, ["branch", "wip/beta"])
        (self.repo / "src" / "model.py").write_text("def train():\n    # local uncommitted work\n    ...\n", encoding="utf-8")
        (self.repo / "scratch.py").write_text("# untracked scratch\n", encoding="utf-8")

    def adopt(self):
        return self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)

    def test_dirty_worktree_is_preserved(self):
        dirty_before = self.sandbox.git(self.repo, ["status", "--porcelain"]).stdout
        model_before = (self.repo / "src" / "model.py").read_text(encoding="utf-8")
        scratch_before = (self.repo / "scratch.py").read_text(encoding="utf-8")
        self.adopt()
        self.assertEqual((self.repo / "src" / "model.py").read_text(encoding="utf-8"), model_before)
        self.assertEqual((self.repo / "scratch.py").read_text(encoding="utf-8"), scratch_before)
        for line in dirty_before.splitlines():
            self.assertIn(line, self.sandbox.git(self.repo, ["status", "--porcelain"]).stdout)

    def test_existing_agents_and_claude_content_survives(self):
        self.adopt()
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        claude = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertTrue(agents.startswith(EXISTING_AGENTS))
        self.assertIn("make lint", agents)
        self.assertIn("Never commit raw recordings.", agents)
        self.assertTrue(claude.startswith(EXISTING_CLAUDE))
        self.assertIn("Use uv, not pip.", claude)
        self.assertIn("<!-- BEGIN RESEARCH-HARNESS -->", agents)
        self.assertIn("<!-- BEGIN RESEARCH-HARNESS -->", claude)

    def test_existing_skills_are_left_alone(self):
        before = (self.repo / ".claude" / "skills" / "lab-style" / "SKILL.md").read_text(encoding="utf-8")
        self.adopt()
        self.assertEqual((self.repo / ".claude" / "skills" / "lab-style" / "SKILL.md").read_text(encoding="utf-8"), before)
        self.assertTrue((self.repo / ".claude" / "skills" / "rh-scope" / "SKILL.md").exists())

    def test_existing_codex_config_is_untouched(self):
        before = (self.repo / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.adopt()
        self.assertEqual((self.repo / ".codex" / "config.toml").read_text(encoding="utf-8"), before)

    def test_existing_test_infrastructure_is_untouched(self):
        before = support.snapshot_tree(self.repo / "tests")
        self.adopt()
        self.assertEqual(support.snapshot_tree(self.repo / "tests"), before)

    def test_branches_are_not_renamed_or_deleted(self):
        before = sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())
        self.adopt()
        after = sorted(self.sandbox.git(self.repo, ["branch", "--format=%(refname:short)"]).stdout.split())
        self.assertEqual(before, after)
        self.assertIn("experiment/alpha", after)
        self.assertIn("wip/beta", after)

    def test_only_allowed_paths_change(self):
        before = support.snapshot_tree(self.repo)
        self.adopt()
        difference = support.diff_snapshots(before, support.snapshot_tree(self.repo))
        touched = difference["added"] + difference["changed"] + difference["removed"]
        self.assertEqual(difference["removed"], [])
        for path in touched:
            with self.subTest(path=path):
                self.assertTrue(
                    path.startswith(".research-harness")
                    or path.startswith(".claude/skills/rh-")
                    or path.startswith(".agents/skills/rh-")
                    or path in {"AGENTS.md", "CLAUDE.md", ".claude", ".claude/skills", ".agents", ".agents/skills"},
                    f"adoption touched an out-of-scope path: {path}",
                )

    def test_worktrees_are_preserved(self):
        worktree = self.sandbox.base / "wt-alpha"
        self.sandbox.git(self.repo, ["worktree", "add", str(worktree), "experiment/alpha"])
        before = support.snapshot_tree(worktree)
        self.adopt()
        self.assertEqual(support.snapshot_tree(worktree), before)
        self.assertIn(str(worktree), self.sandbox.git(self.repo, ["worktree", "list"]).stdout)


if __name__ == "__main__":
    unittest.main()
