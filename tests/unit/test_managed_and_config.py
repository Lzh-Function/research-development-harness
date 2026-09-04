"""Managed instruction blocks, manifest/config parsing and version ordering."""

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.config import Config, Manifest, render_toml  # noqa: E402
from research_harness.errors import AdoptionError  # noqa: E402
from research_harness.managed import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    apply_to_file,
    extract_block,
    find_block,
    has_block,
    remove_block,
    upsert_block,
)
from research_harness.util import compare_versions, parse_version, slugify, version_at_least  # noqa: E402

EXISTING = """# Lab conventions

Always seed with 1234.

## House rules

- Never commit raw data.
"""


class ManagedBlockTests(unittest.TestCase):
    def test_append_preserves_existing_content_exactly(self):
        result = upsert_block(EXISTING, "RDH instructions")
        self.assertTrue(result.startswith(EXISTING))
        self.assertIn(BEGIN_MARKER, result)
        self.assertIn(END_MARKER, result)

    def test_update_replaces_only_the_block(self):
        first = upsert_block(EXISTING, "v1")
        second = upsert_block(first, "v2")
        self.assertTrue(second.startswith(EXISTING))
        self.assertIn("v2", second)
        self.assertNotIn("v1", second)
        self.assertEqual(extract_block(second), "v2")

    def test_content_before_and_after_block_survives(self):
        text = f"before\n\n{BEGIN_MARKER}\nold\n{END_MARKER}\n\nafter\n"
        result = upsert_block(text, "new")
        self.assertTrue(result.startswith("before\n\n"))
        self.assertTrue(result.endswith("\n\nafter\n"))
        self.assertIn("new", result)

    def test_remove_restores_original(self):
        self.assertEqual(remove_block(upsert_block(EXISTING, "x")), EXISTING)

    def test_empty_file_gets_only_the_block(self):
        self.assertEqual(upsert_block("", "x"), f"{BEGIN_MARKER}\nx\n{END_MARKER}\n")

    def test_malformed_markers_refuse_to_guess(self):
        for text in (
            f"{BEGIN_MARKER}\nx\n",
            f"{END_MARKER}\n",
            f"{BEGIN_MARKER}\nx\n{BEGIN_MARKER}\ny\n{END_MARKER}\n",
            f"{END_MARKER}\nx\n{BEGIN_MARKER}\n",
        ):
            with self.subTest(text=text[:40]):
                with self.assertRaises(AdoptionError):
                    find_block(text)

    def test_has_block_and_extract_on_plain_text(self):
        self.assertFalse(has_block(EXISTING))
        self.assertIsNone(extract_block(EXISTING))

    def test_apply_to_file_reports_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            path.write_text(EXISTING, encoding="utf-8")
            self.assertEqual(apply_to_file(path, "a")[0], "updated")
            self.assertEqual(apply_to_file(path, "a")[0], "unchanged")
            self.assertEqual(apply_to_file(path, "b")[0], "updated")
            self.assertTrue(path.read_text(encoding="utf-8").startswith(EXISTING))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CLAUDE.md"
            path.write_text(EXISTING, encoding="utf-8")
            apply_to_file(path, "a", dry_run=True)
            self.assertEqual(path.read_text(encoding="utf-8"), EXISTING)


class TomlTests(unittest.TestCase):
    def test_manifest_round_trip(self):
        manifest = Manifest(bundle_version="0.2.0", runtime_version="0.2.1")
        parsed = Manifest.parse(tomllib.loads(manifest.render()))
        self.assertEqual(parsed.bundle_version, "0.2.0")
        self.assertEqual(parsed.runtime_version, "0.2.1")
        self.assertEqual(parsed.min_runtime_version, manifest.min_runtime_version)

    def test_config_round_trip(self):
        config = Config(project_name="lab", github_repo="octo/research", branch_prefix="work/")
        parsed = Config.parse(tomllib.loads(config.render()))
        self.assertEqual(parsed.project_name, "lab")
        self.assertEqual(parsed.github_repo, "octo/research")
        self.assertEqual(parsed.branch_prefix, "work/")

    def test_empty_github_repo_becomes_none(self):
        self.assertIsNone(Config.parse({"github": {"repo": "  "}}).github_repo)

    def test_render_toml_escapes_strings(self):
        rendered = render_toml({"a": 'say "hi"', "t": {"b": True, "n": 3}})
        data = tomllib.loads(rendered)
        self.assertEqual(data["a"], 'say "hi"')
        self.assertEqual(data["t"], {"b": True, "n": 3})


class VersionTests(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(compare_versions("0.2.0", "0.10.0"), -1)
        self.assertEqual(compare_versions("1.0.0", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.2.3", "1.2.2"), 1)

    def test_prerelease_suffix_is_tolerated(self):
        self.assertEqual(parse_version("1.2.3-rc1"), (1, 2, 3))

    def test_at_least(self):
        self.assertTrue(version_at_least("0.1.0", "0.1.0"))
        self.assertFalse(version_at_least("0.0.9", "0.1.0"))

    def test_invalid_version(self):
        with self.assertRaises(ValueError):
            parse_version("not-a-version")


class SlugTests(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(slugify("Probe: Layer-7 Emergence!"), "probe-layer-7-emergence")

    def test_non_ascii_is_empty_not_invalid(self):
        self.assertEqual(slugify("キラリティ"), "")

    def test_truncation_has_no_trailing_dash(self):
        slug = slugify("a" * 40 + " " + "b" * 40, max_length=45)
        self.assertLessEqual(len(slug), 45)
        self.assertFalse(slug.endswith("-"))


if __name__ == "__main__":
    unittest.main()
