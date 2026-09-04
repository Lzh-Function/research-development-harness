"""The vendored skills must load in both Claude Code and Codex.

Verified against official documentation (2026-09):

* Claude Code — project skills live at `.claude/skills/<name>/SKILL.md`;
  frontmatter is YAML between `---` markers with the opening `---` on the
  first line. Fields portable outside Claude Code are limited to the Agent
  Skills spec's six: allowed-tools, compatibility, description, license,
  metadata, name. A Claude-only field makes the file fail validation on other
  distribution paths.
  https://code.claude.com/docs/en/skills
* Codex — repository skills live at `.agents/skills/<name>/SKILL.md`, scanned
  from the working directory up to the repository root; `SKILL.md` must
  include `name` and `description`.
  https://learn.chatgpt.com/docs/build-skills
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402

BUNDLE = support.REPO_ROOT / "bundle"

#: Fields accepted on every distribution path (Agent Skills open standard).
PORTABLE_FIELDS = {"allowed-tools", "compatibility", "description", "license", "metadata", "name"}

EXPECTED_SKILLS = {
    "rh-scope", "rh-start", "rh-checkpoint", "rh-resume",
    "rh-status", "rh-decision", "rh-result", "rh-finish",
}


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal front-matter reader: the shape both products actually require."""
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("SKILL.md must open with '---' on the very first line")
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line == "---":
            return fields
        if line.startswith((" ", "\t")):
            continue  # continuation of a folded value
        key, separator, value = line.partition(":")
        if not separator:
            raise AssertionError(f"malformed frontmatter line: {line!r}")
        fields[key.strip()] = value.strip()
    raise AssertionError("frontmatter was never closed with '---'")


class SkillBundleTests(unittest.TestCase):
    def skill_files(self):
        for vendor in ("claude-skills", "codex-skills"):
            base = BUNDLE / vendor
            for directory in sorted(p for p in base.iterdir() if p.is_dir()):
                yield vendor, directory.name, directory / "SKILL.md"

    def test_both_vendors_ship_the_same_skill_set(self):
        for vendor in ("claude-skills", "codex-skills"):
            with self.subTest(vendor=vendor):
                self.assertEqual({p.name for p in (BUNDLE / vendor).iterdir()}, EXPECTED_SKILLS)

    def test_every_skill_has_a_skill_md(self):
        for vendor, name, path in self.skill_files():
            with self.subTest(vendor=vendor, skill=name):
                self.assertTrue(path.exists(), f"{vendor}/{name} has no SKILL.md")

    def test_frontmatter_uses_only_portable_fields(self):
        for vendor, name, path in self.skill_files():
            with self.subTest(vendor=vendor, skill=name):
                fields = parse_frontmatter(path.read_text(encoding="utf-8"))
                self.assertEqual(set(fields) - PORTABLE_FIELDS, set(), "non-portable frontmatter field")
                self.assertIn("name", fields)
                self.assertIn("description", fields)

    def test_name_matches_the_directory(self):
        for vendor, name, path in self.skill_files():
            with self.subTest(vendor=vendor, skill=name):
                self.assertEqual(parse_frontmatter(path.read_text(encoding="utf-8"))["name"], name)

    def test_description_says_what_and_when_and_fits_the_listing_budget(self):
        for vendor, name, path in self.skill_files():
            with self.subTest(vendor=vendor, skill=name):
                description = parse_frontmatter(path.read_text(encoding="utf-8"))["description"]
                self.assertLessEqual(len(description), 1536, "truncated in the skill listing")
                self.assertGreater(len(description), 40)
                self.assertIn("Use", description, "a description must say when to use the skill")

    def test_skills_delegate_to_the_canonical_workflow(self):
        """No long workflow prose may be duplicated per vendor."""
        for vendor, name, path in self.skill_files():
            with self.subTest(vendor=vendor, skill=name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(".research-harness/workflows/", text)
                self.assertIn("git rev-parse --show-toplevel", text)
                self.assertLess(len(text), 3000, "a thin adapter should not grow into a workflow copy")

    def test_every_referenced_workflow_exists(self):
        workflows = {p.name for p in (BUNDLE / "workflows").iterdir()}
        for vendor, name, path in self.skill_files():
            text = path.read_text(encoding="utf-8")
            referenced = {
                line.split(".research-harness/workflows/")[1].split("`")[0].strip()
                for line in text.splitlines()
                if ".research-harness/workflows/" in line
            }
            with self.subTest(vendor=vendor, skill=name):
                self.assertTrue(referenced <= workflows, f"{name} references a missing workflow: {referenced - workflows}")

    def test_claude_and_codex_adapters_stay_in_step(self):
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                claude = (BUNDLE / "claude-skills" / name / "SKILL.md").read_text(encoding="utf-8")
                codex = (BUNDLE / "codex-skills" / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertEqual(claude, codex, "both vendors must describe the same behaviour")

    def test_cross_issue_history_has_an_agent_side_entry_point(self):
        """`rh log` must be reachable from a workflow, not researcher-only."""
        workflow = (BUNDLE / "workflows" / "status.md").read_text(encoding="utf-8")
        self.assertIn('"$RH" log', workflow)
        self.assertIn("--kind result", workflow)
        description = parse_frontmatter(
            (BUNDLE / "claude-skills" / "rh-status" / "SKILL.md").read_text(encoding="utf-8")
        )["description"]
        self.assertIn("rh log", description)
        self.assertIn("project", description)

    def test_managed_instructions_stay_short_and_point_at_the_canon(self):
        text = (BUNDLE / "managed-instructions.md").read_text(encoding="utf-8")
        self.assertLess(len(text), 2000, "AGENTS.md/CLAUDE.md must not carry the whole workflow")
        self.assertIn(".research-harness/workflows/", text)
        flat = " ".join(text.split())  # the source is hard-wrapped
        for rule in ("Never auto-merge", "Record meaningful checkpoints", "not from chat history"):
            self.assertIn(rule, flat)


if __name__ == "__main__":
    unittest.main()
