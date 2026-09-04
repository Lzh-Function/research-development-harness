"""Record marker parsing, serialization and schema tolerance."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402  (path setup)

from research_harness.errors import RecordError  # noqa: E402
from research_harness.records import (  # noqa: E402
    RECORD_TAG,
    Record,
    WorkMarker,
    extract_section,
    headline,
    latest,
    parse_marker,
    parse_record,
    render_marker,
    sections,
    sort_records,
    strip_markers,
)


class MarkerTests(unittest.TestCase):
    def test_round_trip(self):
        payload = {"schema": 1, "kind": "checkpoint", "id": "abc"}
        text = render_marker(RECORD_TAG, payload)
        self.assertEqual(parse_marker(text, RECORD_TAG), payload)

    def test_double_hyphen_is_escaped(self):
        """`--` cannot appear inside an HTML comment."""
        marker = render_marker(RECORD_TAG, {"note": "a--b"})
        self.assertNotIn("a--b", marker)
        self.assertEqual(parse_marker(marker, RECORD_TAG)["note"], "a--b")

    def test_missing_marker(self):
        self.assertIsNone(parse_marker("just prose", RECORD_TAG))

    def test_malformed_json_is_not_fatal(self):
        self.assertIsNone(parse_marker("<!-- rh:record {not json} -->", RECORD_TAG))

    def test_strip_markers_leaves_body(self):
        record = Record(kind="result", body="## Result Record\n\nbody", issue=3)
        self.assertEqual(strip_markers(record.to_comment()), "## Result Record\n\nbody")


class RecordTests(unittest.TestCase):
    def test_comment_round_trip(self):
        record = Record(
            kind="checkpoint",
            body="## Research Harness Checkpoint\n\n### Next Action\nrun the sweep",
            issue=184,
            head="abcdef1234",
            branch="rh/184-x",
        )
        parsed = parse_record(record.to_comment())
        self.assertEqual(parsed.kind, "checkpoint")
        self.assertEqual(parsed.issue, 184)
        self.assertEqual(parsed.head, "abcdef1234")
        self.assertEqual(parsed.branch, "rh/184-x")
        self.assertEqual(parsed.id, record.id)
        self.assertEqual(parsed.section("Next Action"), "run the sweep")

    def test_extra_fields_survive(self):
        record = Record(kind="checkpoint", issue=1)
        record.extra["phase"] = "validating"
        parsed = parse_record(record.to_comment())
        self.assertEqual(parsed.extra["phase"], "validating")

    def test_gate_and_decision_fields(self):
        gate = Record(kind="gate", gate="design", outcome="overridden", issue=7)
        self.assertEqual(parse_record(gate.to_comment()).outcome, "overridden")
        decision = Record(kind="decision", status="accepted", issue=7)
        self.assertEqual(parse_record(decision.to_comment()).status, "accepted")

    def test_unknown_kind_rejected_on_write(self):
        with self.assertRaises(RecordError):
            Record(kind="speculation")

    def test_unknown_kind_tolerated_on_read(self):
        """A newer harness' records must not break an older reader."""
        text = '<!-- rh:record {"schema":9,"kind":"vibe","id":"x"} -->\nbody'
        self.assertIsNone(parse_record(text))

    def test_future_schema_is_readable(self):
        text = '<!-- rh:record {"schema":99,"kind":"result","id":"x","issue":4,"novel":true} -->\nbody'
        record = parse_record(text)
        self.assertEqual(record.schema, 99)
        self.assertEqual(record.extra["novel"], True)

    def test_non_numeric_issue_is_ignored(self):
        text = '<!-- rh:record {"schema":1,"kind":"result","id":"x","issue":"not-a-number"} -->'
        self.assertIsNone(parse_record(text).issue)

    def test_latest_and_sort(self):
        old = Record(kind="checkpoint", issue=1, created_at="2026-01-01T00:00:00Z")
        new = Record(kind="checkpoint", issue=1, created_at="2026-02-01T00:00:00Z")
        result = Record(kind="result", issue=1, created_at="2026-03-01T00:00:00Z")
        self.assertIs(latest([old, new, result], "checkpoint"), new)
        self.assertEqual([r.kind for r in sort_records([result, new, old])], ["checkpoint", "checkpoint", "result"])
        self.assertIsNone(latest([], "checkpoint"))


class WorkMarkerTests(unittest.TestCase):
    def test_round_trip(self):
        marker = WorkMarker(kind="experiment", risk="high", evidence_required=True, rq=12)
        marker.validate()
        parsed = WorkMarker.parse("intro\n" + marker.render() + "\nbody")
        self.assertEqual((parsed.kind, parsed.risk, parsed.evidence_required, parsed.rq), ("experiment", "high", True, 12))

    def test_invalid_values_rejected(self):
        with self.assertRaises(RecordError):
            WorkMarker(kind="vibes").validate()
        with self.assertRaises(RecordError):
            WorkMarker(risk="extreme").validate()

    def test_absent_marker(self):
        self.assertIsNone(WorkMarker.parse("An ordinary issue body."))


class HeadlineTests(unittest.TestCase):
    """One-line summaries used by `rh log`."""

    def test_prefers_the_section_that_carries_the_point(self):
        cases = [
            (Record(kind="result", body="### Question\nq\n\n### Observation\nAUROC 0.52"), "AUROC 0.52"),
            (Record(kind="decision", status="accepted", body="### Trigger\nt\n\n### Decision\n除外する"), "除外する"),
            (Record(kind="checkpoint", body="### Done\nd\n\n### Next Action\nsweep を投入"), "sweep を投入"),
            (Record(kind="gate", gate="design", outcome="passed",
                    body="### Validated Concepts\n- v\n\n### Misconceptions Repaired\n- 混同を修復"), "混同を修復"),
        ]
        for record, expected in cases:
            with self.subTest(kind=record.kind):
                self.assertEqual(headline(record), expected)

    def test_falls_back_to_the_first_prose_line(self):
        self.assertEqual(headline(Record(kind="decision", body="## Title\n\nfree prose")), "free prose")

    def test_never_echoes_the_outcome_it_sits_next_to(self):
        record = Record(kind="gate", gate="design", outcome="overridden",
                        body="### Outcome\noverridden\n\n探索的のため skip")
        self.assertEqual(headline(record), "探索的のため skip")

    def test_strips_list_bullets_and_skips_tables(self):
        record = Record(kind="result", body="### Observation\n| a | b |\n- 実測値 0.52")
        self.assertEqual(headline(record), "実測値 0.52")

    def test_truncates_long_lines(self):
        record = Record(kind="result", body="### Observation\n" + "あ" * 200)
        self.assertEqual(len(headline(record, limit=40)), 40)
        self.assertTrue(headline(record, limit=40).endswith("…"))

    def test_empty_body_is_empty_not_an_error(self):
        self.assertEqual(headline(Record(kind="checkpoint", body="")), "")


class SectionTests(unittest.TestCase):
    BODY = "## A\nalpha\n\n### A1\nnested\n\n## B\nbeta\n"

    def test_extract_top_level(self):
        self.assertEqual(extract_section(self.BODY, "A"), "alpha\n\n### A1\nnested")
        self.assertEqual(extract_section(self.BODY, "B"), "beta")

    def test_extract_nested(self):
        self.assertEqual(extract_section(self.BODY, "A1"), "nested")

    def test_case_insensitive_and_missing(self):
        self.assertEqual(extract_section(self.BODY, "b"), "beta")
        self.assertIsNone(extract_section(self.BODY, "C"))

    def test_sections_mapping(self):
        self.assertEqual(sorted(sections(self.BODY)), ["A", "A1", "B"])


if __name__ == "__main__":
    unittest.main()
