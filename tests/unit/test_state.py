"""Derived state, gate policy and READY_TO_MERGE preconditions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.config import Config  # noqa: E402
from research_harness.records import Record, WorkMarker  # noqa: E402
from research_harness.state import (  # noqa: E402
    branch_name,
    checkpoint_phase,
    derive_state,
    gate_satisfied,
    issue_from_branch,
    pending_gates,
    ready_blockers,
)


def gate(name, outcome, at="2026-01-01T00:00:00Z"):
    return Record(kind="gate", gate=name, outcome=outcome, issue=1, created_at=at)


def checkpoint(phase="implementing", body="", at="2026-01-02T00:00:00Z"):
    record = Record(kind="checkpoint", issue=1, body=body, created_at=at)
    record.extra["phase"] = phase
    return record


class GatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def test_low_risk_needs_no_gates(self):
        self.assertEqual(self.config.required_gates("low"), [])

    def test_medium_risk_needs_design_and_knowledge(self):
        self.assertEqual(self.config.required_gates("medium"), ["design", "knowledge"])

    def test_evidence_gate_only_when_evidence_required(self):
        self.assertNotIn("evidence", self.config.required_gates("high"))
        self.assertIn("evidence", self.config.required_gates("high", evidence_required=True))

    def test_deviation_gate_is_never_scheduled_by_risk(self):
        """Deviation is a semantic call by the agent, not risk arithmetic."""
        self.assertFalse(self.config.gate_required("deviation", "high", evidence_required=True))

    def test_thresholds_are_configurable(self):
        strict = Config(design_gate_from="low")
        self.assertIn("design", strict.required_gates("low"))

    def test_gate_satisfied_uses_latest_outcome(self):
        records = [gate("design", "blocked", "2026-01-01T00:00:00Z"), gate("design", "passed", "2026-01-02T00:00:00Z")]
        self.assertTrue(gate_satisfied(records, "design"))
        reversed_records = [gate("design", "passed", "2026-01-01T00:00:00Z"), gate("design", "blocked", "2026-01-02T00:00:00Z")]
        self.assertFalse(gate_satisfied(reversed_records, "design"))

    def test_override_counts_as_satisfied(self):
        self.assertTrue(gate_satisfied([gate("design", "overridden")], "design"))
        self.assertTrue(gate_satisfied([gate("knowledge", "repaired")], "knowledge"))

    def test_open_deviation_gate_is_pending(self):
        records = [gate("design", "passed"), gate("deviation", "blocked", "2026-01-05T00:00:00Z")]
        self.assertEqual(pending_gates(records, Config(), WorkMarker(risk="medium"))[0], "deviation")


class DeriveStateTests(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.marker = WorkMarker(kind="experiment", risk="high", evidence_required=True)

    def state(self, **kwargs):
        params = {"config": self.config, "issue": 1, "marker": self.marker, "records": []}
        params.update(kwargs)
        return derive_state(**params).state

    def test_untracked_without_issue(self):
        self.assertEqual(self.state(issue=None), "UNTRACKED")

    def test_design_gate_blocks_first(self):
        self.assertEqual(self.state(), "DESIGN_GATE")

    def test_scoped_when_no_gate_required(self):
        self.assertEqual(self.state(marker=WorkMarker(risk="low")), "SCOPED")

    def test_ready_after_design_gate(self):
        self.assertEqual(self.state(records=[gate("design", "passed")]), "READY")

    def test_in_progress_after_work_starts(self):
        records = [gate("design", "passed")]
        low = WorkMarker(risk="low")
        self.assertEqual(self.state(marker=low, records=records, branch_linked=True, pr=9), "IN_PROGRESS")

    def test_validating_when_evidence_outstanding(self):
        self.assertEqual(
            self.state(records=[gate("design", "passed")], branch_linked=True, pr=9),
            "VALIDATING",
        )

    def test_evidence_gate_once_a_result_exists(self):
        records = [gate("design", "passed"), Record(kind="result", issue=1)]
        self.assertEqual(self.state(records=records, branch_linked=True, pr=9), "EVIDENCE_GATE")

    def test_knowledge_gate_after_evidence(self):
        records = [
            gate("design", "passed"),
            Record(kind="result", issue=1),
            gate("evidence", "passed"),
            checkpoint(phase="review"),
        ]
        self.assertEqual(self.state(records=records, branch_linked=True, pr=9), "KNOWLEDGE_GATE")

    def test_ready_to_merge_when_all_gates_pass(self):
        records = [
            gate("design", "passed"),
            Record(kind="result", issue=1),
            gate("evidence", "passed"),
            gate("knowledge", "passed"),
            checkpoint(phase="review"),
        ]
        self.assertEqual(self.state(records=records, branch_linked=True, pr=9), "READY_TO_MERGE")

    def test_blocked_from_checkpoint_section(self):
        records = [
            gate("design", "passed"),
            checkpoint(body="### Blocked By\nthe cluster queue is down"),
        ]
        derived = derive_state(
            config=self.config, issue=1, marker=self.marker, records=records, branch_linked=True, pr=9
        )
        self.assertEqual(derived.state, "BLOCKED")
        self.assertEqual(derived.blockers, ["the cluster queue is down"])

    def test_blocked_by_none_is_not_a_blocker(self):
        records = [gate("design", "passed"), checkpoint(body="### Blocked By\nnone")]
        derived = derive_state(
            config=self.config, issue=1, marker=self.marker, records=records, branch_linked=True, pr=9
        )
        self.assertEqual(derived.blockers, [])

    def test_deviation_gate_wins(self):
        records = [gate("design", "passed"), gate("deviation", "blocked", "2026-02-01T00:00:00Z")]
        self.assertEqual(self.state(records=records, branch_linked=True, pr=9), "DEVIATION_GATE")

    def test_done_when_merged_or_closed(self):
        self.assertEqual(self.state(pr_state="MERGED", branch_linked=True, pr=9), "DONE")
        self.assertEqual(self.state(issue_state="CLOSED"), "DONE")

    def test_lifecycle_markers(self):
        marker = WorkMarker(risk="high")
        marker.extra["status"] = "deferred"
        self.assertEqual(self.state(marker=marker), "DEFERRED")
        marker.extra["status"] = "abandoned"
        self.assertEqual(self.state(marker=marker), "ABANDONED")

    def test_phase_defaults_and_validation(self):
        self.assertEqual(checkpoint_phase(None), "implementing")
        record = Record(kind="checkpoint", issue=1)
        record.extra["phase"] = "nonsense"
        self.assertEqual(checkpoint_phase(record), "implementing")


class RecordOrderingTests(unittest.TestCase):
    """Regression: two records written in the same second must stay ordered."""

    def test_millisecond_timestamps_are_distinct(self):
        from research_harness.util import iso_timestamp

        stamps = [iso_timestamp() for _ in range(50)]
        self.assertTrue(all(len(s) == len("2026-01-01T00:00:00.000Z") for s in stamps))
        self.assertEqual(stamps, sorted(stamps))

    def test_same_timestamp_keeps_source_order(self):
        from research_harness.records import sort_records

        at = "2026-01-01T00:00:00.000Z"
        blocked = gate("deviation", "blocked", at)
        passed = gate("deviation", "passed", at)
        self.assertEqual([r.outcome for r in sort_records([blocked, passed])], ["blocked", "passed"])
        self.assertFalse(gate_satisfied([blocked], "deviation"))

    def test_deviation_resolution_wins_within_one_second(self):
        at = "2026-01-01T00:00:00.000Z"
        records = [gate("design", "passed", at), gate("deviation", "blocked", at), gate("deviation", "passed", at)]
        self.assertNotIn("deviation", pending_gates(records, Config(), WorkMarker(risk="medium")))


class ReadyTests(unittest.TestCase):
    def test_lists_every_missing_precondition(self):
        problems = ready_blockers(
            config=Config(),
            marker=WorkMarker(risk="high", evidence_required=True),
            records=[],
            pr=None,
            dirty=True,
        )
        joined = " | ".join(problems)
        self.assertIn("no Draft PR", joined)
        self.assertIn("design gate", joined)
        self.assertIn("Result Record", joined)
        self.assertIn("Checkpoint Record", joined)
        self.assertIn("uncommitted", joined)

    def test_clean_when_everything_present(self):
        records = [
            gate("design", "passed"),
            gate("evidence", "passed"),
            gate("knowledge", "passed"),
            Record(kind="result", issue=1),
            checkpoint(phase="review", body="### Blocked By\nnone"),
        ]
        problems = ready_blockers(
            config=Config(),
            marker=WorkMarker(risk="high", evidence_required=True),
            records=records,
            pr=9,
            dirty=False,
        )
        self.assertEqual(problems, [])


class BranchNamingTests(unittest.TestCase):
    def test_branch_name_and_recovery(self):
        name = branch_name(184, "Probe chirality emergence in layer 7")
        self.assertEqual(name, "rh/184-probe-chirality-emergence-in-layer-7")
        self.assertEqual(issue_from_branch(name), 184)

    def test_non_ascii_title_degrades_safely(self):
        name = branch_name(12, "キラリティ解析")
        self.assertEqual(name, "rh/12")
        self.assertEqual(issue_from_branch(name), 12)

    def test_unrelated_branch_has_no_issue(self):
        self.assertIsNone(issue_from_branch("feature/other"))
        self.assertIsNone(issue_from_branch(None))


if __name__ == "__main__":
    unittest.main()
