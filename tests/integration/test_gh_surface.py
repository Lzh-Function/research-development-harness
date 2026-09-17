"""The gh surface is a contract, not an implementation detail.

People isolate the GitHub token from the agent by putting `gh` behind an
allow-list. They build that list from docs/GH-SURFACE.md. If RDH ever issues a
gh call the document does not list — or relies on `gh api`, which would let
the agent reach any endpoint — their harness breaks or their isolation leaks.
This test exercises every GitHub-facing command and holds the implementation
to the document.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402

DOC = support.REPO_ROOT / "docs" / "GH-SURFACE.md"
PINNED_REPO = "octo/research"


def documented_surface() -> dict[str, set[str]]:
    """Parse the machine-readable allow-list out of docs/GH-SURFACE.md."""
    text = DOC.read_text(encoding="utf-8")
    match = re.search(r"```text rh-gh-surface\n(.*?)```", text, re.S)
    if not match:
        raise AssertionError("docs/GH-SURFACE.md has no ```text rh-gh-surface block")
    surface: dict[str, set[str]] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        head, _, flags = line.partition(":")
        surface[head.strip()] = set(flags.split())
    return surface


def command_head(call: list[str]) -> str:
    if call and call[0].startswith("-"):
        return call[0]
    return " ".join(call[:2])


class GhSurfaceContractTests(SandboxTestCase):
    @classmethod
    def setUpClass(cls):
        cls.surface = documented_surface()

    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        config = self.repo / ".research-harness" / "config.toml"
        config.write_text(config.read_text().replace('repo = ""', f'repo = "{PINNED_REPO}"'), encoding="utf-8")
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "adopt"])
        self.calls = self.exercise_every_github_command()

    def rh(self, *args, check=True):
        return self.sandbox.rh_local(self.repo, list(args), check=check)

    def exercise_every_github_command(self) -> list[list[str]]:
        before = len(self.sandbox.gh_calls())
        self.rh("doctor", check=False)
        self.rh("rq", "create", "--title", "Q")
        self.rh("issue", "create", "--title", "W", "--kind", "experiment", "--risk", "medium",
                "--evidence-required", "--rq", "1", "--label", "research", "--body", "## Purpose\n\nx")
        self.rh("work", "link", "2")
        self.rh("record", "gate", "--gate", "design", "--outcome", "passed", "--body", "### Outcome\npassed")
        self.rh("work", "start", "2")
        (self.repo / "probe.py").write_text("# probe\n", encoding="utf-8")
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "probe"])
        self.sandbox.git(self.repo, ["push", "-q", "origin", "HEAD"])
        self.rh("pr", "create")
        self.rh("status")
        self.rh("resume")
        self.rh("pr", "update", "--body", "Refs #2\n\n## Does NOT Establish\n\nx")
        self.rh("ready", check=False)
        self.rh("log")
        self.rh("rq", "list")
        self.rh("rq", "show", "1")
        self.rh("audit")
        # sync with something actually queued, so its gh calls are exercised
        self.rh("record", "checkpoint", "--body", "### Next Action\nx")
        self.rh("sync")
        self.rh("issue", "close", "2", "--force", "--comment", "done")
        return self.sandbox.gh_calls()[before:]

    # ---------------------------------------------------------------- contract

    def test_never_calls_gh_api(self):
        """`gh api` would hand the agent unrestricted API access."""
        offenders = [call for call in self.calls if call[:1] == ["api"]]
        self.assertEqual(offenders, [], "RDH must not depend on `gh api`")

    def test_every_call_is_on_the_documented_allow_list(self):
        for call in self.calls:
            head = command_head(call)
            with self.subTest(call=" ".join(call)):
                self.assertIn(head, self.surface, f"`gh {head}` is not in docs/GH-SURFACE.md")

    def test_every_flag_is_documented(self):
        for call in self.calls:
            head = command_head(call)
            flags = {a for a in call if a.startswith("--") and a != head}
            with self.subTest(call=" ".join(call)):
                undocumented = flags - self.surface.get(head, set())
                self.assertEqual(undocumented, set(), f"`gh {head}` used undocumented flags")

    def test_the_document_lists_nothing_rdh_does_not_use(self):
        """A phantom entry would make brokers grant more than they need."""
        used = {command_head(call) for call in self.calls}
        self.assertEqual(set(self.surface) - used, set())

    def test_body_files_stay_inside_the_repository_state_directory(self):
        """A broker can then refuse any other path, closing file exfiltration."""
        allowed = (self.repo / ".git" / "research-harness" / "tmp").resolve()
        paths = [call[call.index("--body-file") + 1] for call in self.calls if "--body-file" in call]
        self.assertTrue(paths, "expected at least one --body-file call")
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(Path(path).resolve().parent, allowed)

    def test_repo_flag_is_always_the_pinned_repository(self):
        values = {call[call.index("--repo") + 1] for call in self.calls if "--repo" in call}
        self.assertEqual(values, {PINNED_REPO})

    def test_repo_scoped_calls_all_carry_the_flag(self):
        """Except `repo view`, which takes the repository positionally."""
        for call in self.calls:
            head = command_head(call)
            if head.split()[0] in {"issue", "pr"}:
                with self.subTest(call=" ".join(call)):
                    self.assertIn("--repo", call)

    def test_repo_view_takes_the_repository_positionally(self):
        views = [call for call in self.calls if command_head(call) == "repo view"]
        self.assertTrue(views)
        for call in views:
            with self.subTest(call=" ".join(call)):
                self.assertNotIn("--repo", call)
                self.assertIn(PINNED_REPO, call)

    def test_forbidden_commands_never_appear(self):
        forbidden = {"api", "auth token", "issue edit", "issue delete", "pr comment", "pr merge"}
        for call in self.calls:
            head = command_head(call)
            with self.subTest(call=" ".join(call)):
                self.assertNotIn(head, forbidden)
                self.assertNotIn(call[0] if call else "", {"api"})
                self.assertNotIn("--show-token", call)


class GhSurfaceDocumentTests(unittest.TestCase):
    def test_the_allow_list_block_parses(self):
        surface = documented_surface()
        self.assertIn("issue view", surface)
        self.assertNotIn("api", surface)

    def test_document_warns_against_granting_gh_api(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("`api`", text)
        self.assertIn("許可すべきでないもの", text)


if __name__ == "__main__":
    unittest.main()
