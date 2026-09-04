"""Destructive Git operations must be refused in code, not just in docs."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.errors import UnsafeOperationError  # noqa: E402
from research_harness.git import assert_safe_git  # noqa: E402

FORBIDDEN = [
    ["git", "reset", "--hard"],
    ["git", "reset", "--hard", "HEAD~3"],
    ["git", "reset", "--merge"],
    ["git", "clean", "-fd"],
    ["git", "clean", "-xfd"],
    ["git", "stash"],
    ["git", "stash", "push", "-u"],
    ["git", "checkout", "--force", "main"],
    ["git", "checkout", "--", "."],
    ["git", "restore", "src/model.py"],
    ["git", "switch", "--force", "main"],
    ["git", "switch", "--discard-changes", "main"],
    ["git", "branch", "-D", "rh/1-x"],
    ["git", "branch", "--delete", "rh/1-x"],
    ["git", "tag", "-d", "v1"],
    ["git", "push", "--force", "origin", "main"],
    ["git", "push", "--force-with-lease", "origin", "main"],
    ["git", "push", "-f", "origin", "main"],
    ["git", "push", "origin", "--delete", "rh/1-x"],
    ["git", "push", "origin", ":rh/1-x"],
    ["git", "push", "origin", "+refs/heads/main:refs/heads/main"],
    ["git", "rebase", "-i", "HEAD~5"],
    ["git", "filter-branch", "--all"],
    ["git", "filter-repo", "--path", "x"],
    ["git", "commit", "--amend", "-m", "oops"],
    ["git", "update-ref", "-d", "refs/heads/x"],
    ["git", "reflog", "delete", "HEAD@{0}"],
    ["git", "gc", "--prune=now"],
    ["git", "worktree", "remove", "../wt"],
    ["git", "-C", "/repo", "reset", "--hard"],
]

ALLOWED = [
    ["git", "status", "--porcelain=v1"],
    ["git", "rev-parse", "HEAD"],
    ["git", "log", "-5"],
    ["git", "diff", "--name-only"],
    ["git", "switch", "--create", "rh/12-probe"],
    ["git", "switch", "main"],
    ["git", "push", "--set-upstream", "origin", "rh/12-probe"],
    ["git", "worktree", "list", "--porcelain"],
    ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
    ["git", "-C", "/repo", "status"],
    ["git", "commit", "-m", "message"],
]


class GitSafetyTests(unittest.TestCase):
    def test_destructive_commands_refused(self):
        for argv in FORBIDDEN:
            with self.subTest(argv=argv):
                with self.assertRaises(UnsafeOperationError):
                    assert_safe_git(argv)

    def test_ordinary_commands_allowed(self):
        for argv in ALLOWED:
            with self.subTest(argv=argv):
                assert_safe_git(argv)

    def test_guard_accepts_argv_without_git_prefix(self):
        with self.assertRaises(UnsafeOperationError):
            assert_safe_git(["clean", "-fd"])

    def test_empty_and_flag_only_argv_are_inert(self):
        assert_safe_git(["git"])
        assert_safe_git(["git", "--no-pager"])


class RepoSafetyTests(support.SandboxTestCase):
    def test_gitrepo_refuses_destructive_run(self):
        from research_harness.git import GitRepo
        from research_harness.proc import SubprocessRunner

        repo_path = self.sandbox.make_repo()
        repo = GitRepo(repo_path, SubprocessRunner(env_overlay=self.sandbox.env))
        with self.assertRaises(UnsafeOperationError):
            repo.run(["reset", "--hard"])
        with self.assertRaises(UnsafeOperationError):
            repo.run(["clean", "-fd"])

    def test_dirty_worktree_survives_branch_creation(self):
        from research_harness.git import GitRepo
        from research_harness.proc import SubprocessRunner

        repo_path = self.sandbox.make_repo()
        (repo_path / "experiment.py").write_text("# work in progress\n", encoding="utf-8")
        (repo_path / "README.md").write_text("# research\nlocal edit\n", encoding="utf-8")
        repo = GitRepo(repo_path, SubprocessRunner(env_overlay=self.sandbox.env))
        self.assertTrue(repo.is_dirty())
        repo.create_branch("rh/1-probe")
        self.assertEqual(repo.branch(), "rh/1-probe")
        self.assertEqual((repo_path / "experiment.py").read_text(encoding="utf-8"), "# work in progress\n")
        self.assertIn("local edit", (repo_path / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(repo.is_dirty())


if __name__ == "__main__":
    unittest.main()
