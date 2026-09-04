"""$HOME zero-touch — the acceptance criterion RDH must never regress (SPEC 55).

Every command runs with an isolated temporary HOME. Git is pointed at config
files outside HOME and given its identity through environment variables, and
`gh` is a fake executable, so anything appearing under HOME afterwards came
from RDH itself.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class HomeSnapshotSanityTests(SandboxTestCase):
    """Prove the detector is not vacuous before trusting it."""

    def test_detector_notices_a_new_file(self):
        before = self.home_snapshot()
        (self.sandbox.home / ".claude").mkdir(parents=True)
        (self.sandbox.home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(AssertionError):
            self.assertHomeUnchanged(before)

    def test_detector_notices_a_modified_file(self):
        target = self.sandbox.home / ".bashrc"
        target.write_text("original\n", encoding="utf-8")
        before = self.home_snapshot()
        target.write_text("export PATH=$PATH:/opt/rh/bin\n", encoding="utf-8")
        with self.assertRaises(AssertionError):
            self.assertHomeUnchanged(before)

    def test_detector_notices_a_deletion(self):
        target = self.sandbox.home / ".gitconfig"
        target.write_text("[user]\n", encoding="utf-8")
        before = self.home_snapshot()
        target.unlink()
        with self.assertRaises(AssertionError):
            self.assertHomeUnchanged(before)


class HomeZeroTouchTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        # Pre-existing HOME content that must survive untouched.
        (self.sandbox.home / ".claude").mkdir(parents=True)
        (self.sandbox.home / ".claude" / "settings.json").write_text('{"theme":"dark"}\n', encoding="utf-8")
        (self.sandbox.home / ".codex").mkdir(parents=True)
        (self.sandbox.home / ".codex" / "config.toml").write_text("model = 'gpt-5'\n", encoding="utf-8")
        (self.sandbox.home / ".bashrc").write_text("# researcher's shell rc\n", encoding="utf-8")

    def test_baseline_environment_does_not_touch_home_by_itself(self):
        """Guard against a false pass: the environment must be quiet too."""
        before = self.home_snapshot()
        self.sandbox.git(self.repo, ["status", "--porcelain"])
        self.sandbox.run(["gh", "--version"])
        self.assertHomeUnchanged(before, "sandbox environment itself is not quiet")

    def test_adopt_touches_nothing_in_home(self):
        before = self.home_snapshot()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.assertHomeUnchanged(before, "rh adopt")

    def test_upgrade_touches_nothing_in_home(self):
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        before = self.home_snapshot()
        self.sandbox.rh(["upgrade", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.assertHomeUnchanged(before, "rh upgrade")

    def test_full_work_lifecycle_touches_nothing_in_home(self):
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        before = self.home_snapshot()
        rh = lambda args, **kw: self.sandbox.rh_local(self.repo, args, **kw)  # noqa: E731

        rh(["version"], check=True)
        rh(["doctor"])
        rh(["audit", "--json"], check=True)
        rh(["context", "--json"], check=True)

        body = self.repo / "issue-body.md"
        body.write_text("## Purpose\n\nProbe layer 7.\n", encoding="utf-8")
        created = rh(
            ["issue", "create", "--title", "Probe layer 7", "--kind", "experiment", "--risk", "high",
             "--evidence-required", "--body-file", str(body), "--json"],
            check=True,
        )
        self.assertIn('"issue": 1', created.stdout)
        body.unlink()

        gate = self.repo / "gate.md"
        gate.write_text("## Gate Record\n\n### Outcome\npassed\n", encoding="utf-8")
        rh(["work", "link", "1", "--json"], check=True)
        rh(["record", "gate", "--gate", "design", "--outcome", "passed", "--body-file", str(gate), "--json"], check=True)
        rh(["work", "start", "1", "--json"], check=True)
        rh(["record", "checkpoint", "--body", "### Next Action\ncontinue", "--json"], check=True)
        rh(["record", "result", "--body", "### Observation\nnothing exploded", "--json"], check=True)
        rh(["record", "decision", "--status", "accepted", "--body", "### Decision\nkeep going", "--json"], check=True)
        rh(["status", "--json"], check=True)
        rh(["resume", "--json"], check=True)
        rh(["ready", "--json"])
        rh(["sync", "--json"], check=True)
        gate.unlink()

        self.assertHomeUnchanged(before, "full work lifecycle through the vendored runtime")

    def test_offline_record_and_sync_touch_nothing_in_home(self):
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        before = self.home_snapshot()
        env = {"RH_FAKE_GH_FAIL": "network"}
        self.sandbox.rh_local(self.repo, ["work", "link", "1"], env=env)
        self.sandbox.rh_local(self.repo, ["record", "checkpoint", "--body", "### Next Action\nx"], env=env)
        self.sandbox.rh_local(self.repo, ["sync"], env=env)
        self.assertHomeUnchanged(before, "offline record + sync")

    def test_no_rdh_artifacts_are_created_under_home(self):
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.sandbox.rh_local(self.repo, ["doctor"])
        forbidden = [
            self.sandbox.home / ".claude" / "skills",
            self.sandbox.home / ".agents",
            self.sandbox.home / ".research-harness",
            self.sandbox.home / ".local",
            self.sandbox.home / "bin",
            self.sandbox.home / ".config",
        ]
        for path in forbidden:
            with self.subTest(path=path.name):
                self.assertFalse(path.exists(), f"RDH created {path}")

    def test_existing_home_config_is_never_read_into_the_install(self):
        """No global skill or global rh is required or produced."""
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.assertEqual(
            (self.sandbox.home / ".claude" / "settings.json").read_text(encoding="utf-8"), '{"theme":"dark"}\n'
        )
        self.assertEqual((self.sandbox.home / ".bashrc").read_text(encoding="utf-8"), "# researcher's shell rc\n")


if __name__ == "__main__":
    unittest.main()
