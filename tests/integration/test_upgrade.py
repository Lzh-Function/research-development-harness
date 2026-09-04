"""Upgrade safety: preserve local edits, managed blocks only, no downgrades."""

import json
import shutil
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402

RESEARCHER_INSTRUCTIONS = "# CLAUDE.md\n\nAlways cite the preregistration.\n"


class UpgradeTests(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        (self.repo / "CLAUDE.md").write_text(RESEARCHER_INSTRUCTIONS, encoding="utf-8")
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.harness = self.repo / ".research-harness"

    def upgrade(self, *extra, check=True):
        return self.sandbox.rh(["upgrade", str(self.repo), *extra], cwd=self.sandbox.base, check=check)

    def test_upgrade_requires_an_existing_installation(self):
        other = self.sandbox.make_repo("unadopted")
        result = self.sandbox.rh(["upgrade", str(other)], cwd=self.sandbox.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no RDH installation", result.stderr)

    def test_upgrade_records_the_timestamp_and_keeps_adoption_date(self):
        adopted_at = tomllib.loads((self.harness / "manifest.toml").read_text(encoding="utf-8"))["adopted_at"]
        self.upgrade()
        manifest = tomllib.loads((self.harness / "manifest.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["adopted_at"], adopted_at)
        self.assertIn("upgraded_at", manifest)

    def test_config_and_baseline_are_never_overwritten(self):
        config = self.harness / "config.toml"
        config.write_text(config.read_text(encoding="utf-8").replace('branch_prefix = "rh/"', 'branch_prefix = "work/"'), encoding="utf-8")
        baseline = self.harness / "baseline.md"
        baseline.write_text("# my cutover notes\n", encoding="utf-8")
        self.upgrade()
        self.assertIn('branch_prefix = "work/"', config.read_text(encoding="utf-8"))
        self.assertEqual(baseline.read_text(encoding="utf-8"), "# my cutover notes\n")

    def test_researcher_content_outside_the_managed_block_survives(self):
        claude = self.repo / "CLAUDE.md"
        text = claude.read_text(encoding="utf-8").replace(
            "<!-- END RESEARCH-HARNESS -->", "<!-- END RESEARCH-HARNESS -->\n\n## Added after adoption\n\nUse seed 7."
        )
        claude.write_text(text, encoding="utf-8")
        self.upgrade()
        updated = claude.read_text(encoding="utf-8")
        self.assertTrue(updated.startswith(RESEARCHER_INSTRUCTIONS))
        self.assertIn("Use seed 7.", updated)
        self.assertIn("<!-- BEGIN RESEARCH-HARNESS -->", updated)

    def test_locally_modified_harness_files_are_reported_not_clobbered(self):
        workflow = self.harness / "workflows" / "resume.md"
        workflow.write_text("# my own resume workflow\n", encoding="utf-8")
        result = self.upgrade(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONFLICT", result.stdout)
        self.assertEqual(workflow.read_text(encoding="utf-8"), "# my own resume workflow\n")

    def test_force_overwrites_local_modifications(self):
        workflow = self.harness / "workflows" / "resume.md"
        workflow.write_text("# my own resume workflow\n", encoding="utf-8")
        self.upgrade("--force")
        self.assertIn("STATE DIVERGENCE DETECTED", workflow.read_text(encoding="utf-8"))

    def test_dry_run_changes_nothing(self):
        before = support.snapshot_tree(self.repo)
        result = self.upgrade("--dry-run")
        self.assertIn("Would upgrade", result.stdout)
        self.assertEqual(support.snapshot_tree(self.repo), before)

    def test_dry_run_reports_versions_and_conflicts(self):
        (self.harness / "policy" / "safety.md").write_text("edited\n", encoding="utf-8")
        payload = json.loads(self.upgrade("--dry-run", "--json", check=False).stdout)
        self.assertEqual(payload["mode"], "upgrade")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["from"]["runtime_version"], payload["to"]["runtime_version"])
        self.assertEqual(len(payload["conflicts"]), 1)
        self.assertEqual(payload["conflicts"][0]["path"], ".research-harness/policy/safety.md")

    def test_downgrade_is_refused_without_force(self):
        manifest = self.harness / "manifest.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8").replace('runtime_version = "0.1.0"', 'runtime_version = "9.9.9"'), encoding="utf-8")
        result = self.upgrade(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to downgrade", result.stderr)

    def test_restored_files_are_reinstated(self):
        shutil.rmtree(self.repo / ".claude" / "skills" / "rh-resume")
        (self.harness / "templates" / "result.md").unlink()
        self.upgrade()
        self.assertTrue((self.repo / ".claude" / "skills" / "rh-resume" / "SKILL.md").exists())
        self.assertTrue((self.harness / "templates" / "result.md").exists())

    def test_upgrade_does_not_touch_research_sources(self):
        (self.repo / "src").mkdir()
        (self.repo / "src" / "model.py").write_text("# model\n", encoding="utf-8")
        before = support.snapshot_tree(self.repo / "src")
        self.upgrade()
        self.assertEqual(support.snapshot_tree(self.repo / "src"), before)

    def test_upgraded_repository_still_passes_doctor(self):
        self.upgrade()
        result = self.sandbox.rh_local(self.repo, ["doctor"], check=True)
        self.assertNotIn("ERROR", result.stdout)


if __name__ == "__main__":
    unittest.main()
