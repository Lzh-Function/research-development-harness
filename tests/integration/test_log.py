"""`rh log` — the cross-issue research history.

`rh status` and `rh resume` answer "what is this work unit". This answers
"what has this project learned", across every Work Issue.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class LogTestCase(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)
        self.issues = {}

    def rh(self, args, *, check=False, env=None):
        return self.sandbox.rh_local(self.repo, args, check=check, env=env)

    def rh_json(self, args, *, env=None):
        return json.loads(self.rh([*args, "--json"], check=True, env=env).stdout)

    def make_work(self, title, *, kind="experiment", risk="high", evidence=True, records=()):
        args = ["issue", "create", "--title", title, "--kind", kind, "--risk", risk,
                "--body", f"## Purpose\n\n{title} の目的。"]
        if evidence:
            args.append("--evidence-required")
        number = self.rh_json(args)["issue"]
        self.issues[title] = number
        for record_args, body in records:
            self.rh_json(["record", *record_args, "--issue", str(number), "--body", body])
        return number


class LogTests(LogTestCase):
    def setUp(self):
        super().setUp()
        self.make_work(
            "Chirality probe",
            records=[
                (["gate", "--gate", "design", "--outcome", "passed"],
                 "### Misconceptions Repaired\n- AUROC 低下と情報消失の混同を修復\n\n### Outcome\npassed"),
                (["decision", "--status", "accepted"], "### Decision\nラベル未定義を除外する"),
                (["result"], "### Observation\nlayer 5 で AUROC 0.52"),
            ],
        )
        self.make_work(
            "Scaffold leakage audit",
            kind="analysis", risk="medium",
            records=[
                (["gate", "--gate", "design", "--outcome", "overridden"],
                 "### Outcome\noverridden\n\n探索的のため skip"),
                (["result"], "### Observation\n3.1% の骨格が重複"),
            ],
        )
        self.make_work("Rename helper", kind="refactor", risk="low", evidence=False,
                       records=[(["checkpoint", "--phase", "review"], "### Next Action\nmerge 待ち")])

    # ------------------------------------------------------------------ basics

    def test_spans_every_work_issue(self):
        payload = self.rh_json(["log"])
        self.assertEqual(sorted({e["issue"] for e in payload["entries"]}), [1, 2, 3])
        self.assertEqual(payload["counts"]["result"], 2)
        self.assertEqual(payload["counts"]["gate"], 2)
        self.assertEqual(payload["counts"]["work"], 3)

    def test_newest_first_by_default(self):
        stamps = [e["at"] for e in self.rh_json(["log"])["entries"]]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_reverse_is_oldest_first(self):
        stamps = [e["at"] for e in self.rh_json(["log", "--reverse"])["entries"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_human_output_names_the_work_unit(self):
        out = self.rh(["log", "--kind", "result"], check=True).stdout
        self.assertIn("#1  Chirality probe", out)
        self.assertIn("#2  Scaffold leakage audit", out)
        self.assertIn("layer 5 で AUROC 0.52", out)
        self.assertIn("2 entries", out)

    def test_touches_nothing_but_the_local_record_cache(self):
        """Reading refreshes `.git/research-harness/cache` so --offline works later.

        Nothing in the working tree, and nothing on GitHub, may change.
        """
        before_tree = support.snapshot_tree(self.repo)
        calls_before = len(self.sandbox.gh_calls())

        self.rh(["log"], check=True)

        difference = support.diff_snapshots(before_tree, support.snapshot_tree(self.repo))
        touched = difference["added"] + difference["changed"] + difference["removed"]
        self.assertTrue(touched, "expected the record cache to be refreshed")
        for path in touched:
            with self.subTest(path=path):
                self.assertTrue(
                    path.startswith(".git/research-harness/cache/"),
                    f"rh log wrote outside the local cache: {path}",
                )
        for call in self.sandbox.gh_calls()[calls_before:]:
            with self.subTest(call=call):
                self.assertFalse(
                    {"create", "edit", "comment", "close", "delete", "merge"} & set(call[:2]),
                    f"rh log performed a write: {call}",
                )

    # ----------------------------------------------------------------- filters

    def test_filter_by_kind(self):
        payload = self.rh_json(["log", "--kind", "result"])
        self.assertEqual({e["kind"] for e in payload["entries"]}, {"result"})
        self.assertEqual(len(payload["entries"]), 2)

    def test_filter_by_several_kinds(self):
        payload = self.rh_json(["log", "--kind", "result", "--kind", "decision"])
        self.assertEqual({e["kind"] for e in payload["entries"]}, {"result", "decision"})

    def test_filter_by_gate_and_outcome(self):
        payload = self.rh_json(["log", "--kind", "gate", "--outcome", "overridden"])
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["gate"], "design")
        self.assertEqual(payload["entries"][0]["issue"], 2)

    def test_filter_by_decision_status(self):
        payload = self.rh_json(["log", "--status", "accepted"])
        self.assertEqual(len(payload["entries"]), 1)
        self.assertEqual(payload["entries"][0]["kind"], "decision")

    def test_filter_by_issue(self):
        payload = self.rh_json(["log", "--issue", "1"])
        self.assertEqual({e["issue"] for e in payload["entries"]}, {1})

    def test_grep_searches_body_and_title(self):
        self.assertEqual(len(self.rh_json(["log", "--grep", "骨格"])["entries"]), 1)
        self.assertTrue(self.rh_json(["log", "--grep", "Chirality"])["entries"])
        self.assertEqual(self.rh_json(["log", "--grep", "存在しない語"])["entries"], [])

    def test_since_and_until_accept_prefixes(self):
        self.assertTrue(self.rh_json(["log", "--since", "2026-01"])["entries"])
        self.assertEqual(self.rh_json(["log", "--since", "2099-01"])["entries"], [])
        self.assertEqual(self.rh_json(["log", "--until", "2000-01"])["entries"], [])

    def test_no_work_omits_opening_events(self):
        payload = self.rh_json(["log", "--no-work"])
        self.assertNotIn("work", {e["kind"] for e in payload["entries"]})

    def test_limit_truncates_and_reports_it(self):
        payload = self.rh_json(["log", "--limit", "2"])
        self.assertEqual(len(payload["entries"]), 2)
        self.assertTrue(payload["truncated"])
        self.assertGreater(payload["total_matched"], 2)

    def test_entry_count_is_pluralised(self):
        self.assertIn("2 entries", self.rh(["log", "--kind", "result"], check=True).stdout)
        self.assertIn("1 entry", self.rh(["log", "--kind", "decision"], check=True).stdout)

    def test_no_match_is_not_an_error(self):
        result = self.rh(["log", "--grep", "nothing here"], check=True)
        self.assertIn("no records matched", result.stdout)
        self.assertEqual(result.returncode, 0)

    # ---------------------------------------------------------------- content

    def test_headline_summarises_each_kind(self):
        entries = {(e["issue"], e["kind"], e["gate"]): e["headline"] for e in self.rh_json(["log"])["entries"]}
        self.assertEqual(entries[(1, "result", None)], "layer 5 で AUROC 0.52")
        self.assertEqual(entries[(1, "decision", None)], "ラベル未定義を除外する")
        self.assertIn("混同を修復", entries[(1, "gate", "design")])
        self.assertEqual(entries[(3, "checkpoint", None)], "merge 待ち")

    def test_gate_headline_does_not_echo_the_outcome(self):
        """The outcome is already shown beside the kind."""
        entry = next(
            e for e in self.rh_json(["log", "--kind", "gate", "--outcome", "overridden"])["entries"]
        )
        self.assertNotEqual(entry["headline"].lower(), "overridden")
        self.assertIn("探索的", entry["headline"])

    def test_work_entry_uses_the_stated_purpose(self):
        entry = next(e for e in self.rh_json(["log", "--kind", "work"])["entries"] if e["issue"] == 1)
        self.assertIn("の目的", entry["headline"])
        self.assertEqual(entry["label"], "experiment/high")

    def test_full_prints_record_bodies(self):
        out = self.rh(["log", "--kind", "result", "--issue", "1", "--full"], check=True).stdout
        self.assertIn("### Observation", out)

    def test_ordinary_issues_are_ignored(self):
        """Only issues carrying an rh:work marker are research work units."""
        self.sandbox.run(["gh", "issue", "create", "--title", "CI is flaky", "--body", "no marker here"])
        payload = self.rh_json(["log"])
        self.assertNotIn("CI is flaky", json.dumps(payload, ensure_ascii=False))


class LogOfflineTests(LogTestCase):
    def test_falls_back_to_the_local_cache(self):
        self.make_work("Cached work", kind="analysis", risk="medium", evidence=False,
                       records=[(["result"], "### Observation\ncached observation")])
        self.rh_json(["log"])  # populates the cache
        payload = self.rh_json(["--offline", "log"])
        self.assertTrue(any(e["headline"] == "cached observation" for e in payload["entries"]))

    def test_offline_contacts_nothing(self):
        self.make_work("Cached work", kind="analysis", risk="medium", evidence=False,
                       records=[(["result"], "### Observation\nx")])
        self.rh_json(["log"])
        before = len(self.sandbox.gh_calls())
        self.rh_json(["--offline", "log"])
        self.assertEqual(len(self.sandbox.gh_calls()), before)

    def test_empty_repository_reports_nothing_rather_than_failing(self):
        result = self.rh(["log"], check=True)
        self.assertIn("no records matched", result.stdout)


if __name__ == "__main__":
    unittest.main()
