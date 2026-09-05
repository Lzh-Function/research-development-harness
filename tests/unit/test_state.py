"""Derived state, gate policy and READY_TO_MERGE preconditions."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.config import Config  # noqa: E402
from research_harness.records import Record, WorkMarker  # noqa: E402
from research_harness.state import (  # noqa: E402
    STATES,
    branch_name,
    checkpoint_phase,
    derive_state,
    gate_satisfied,
    issue_from_branch,
    next_command,
    next_command_note,
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


GOOD_PR_BODY = """## Purpose

x

## Does NOT Establish

情報が失われていること。probe 容量が固定のため区別できない。
"""

EMPTY_PR_BODY = """## Purpose

x

## Does NOT Establish

<!-- filled in by rh-finish -->
"""

PROVENANCE = """### Observation

AUROC 0.52

### Provenance

- commit: abc1234
- configuration: configs/probe_v2.yaml
- seed: 0-4
"""

EMPTY_PROVENANCE = """### Observation

AUROC 0.52

### Provenance

- commit:
- configuration:
- seed:
"""


class ReadyTests(unittest.TestCase):
    def test_lists_every_missing_precondition(self):
        problems, _ = ready_blockers(
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
            Record(kind="result", issue=1, body=PROVENANCE),
            checkpoint(phase="review", body="### Blocked By\nnone"),
        ]
        problems, warnings = ready_blockers(
            config=Config(),
            marker=WorkMarker(risk="high", evidence_required=True),
            records=records,
            pr=9,
            dirty=False,
            pr_body=GOOD_PR_BODY,
        )
        self.assertEqual(problems, [])
        self.assertEqual(warnings, [])


class StructuralReadyChecks(unittest.TestCase):
    """Evidence-required work must state its limits and its provenance."""

    def complete_records(self, result_body=PROVENANCE):
        return [
            gate("design", "passed"),
            gate("evidence", "passed"),
            gate("knowledge", "passed"),
            Record(kind="result", issue=1, body=result_body),
            checkpoint(phase="review", body="### Blocked By\nnone"),
        ]

    def check(self, *, config=None, evidence=True, result_body=PROVENANCE, pr_body=GOOD_PR_BODY, available=True):
        return ready_blockers(
            config=config or Config(),
            marker=WorkMarker(risk="high", evidence_required=evidence),
            records=self.complete_records(result_body),
            pr=9,
            dirty=False,
            pr_body=pr_body,
            pr_body_available=available,
        )

    def test_missing_does_not_establish_blocks(self):
        problems, _ = self.check(pr_body="## Purpose\n\nx\n")
        self.assertTrue(any("Does NOT Establish" in p for p in problems))

    def test_placeholder_does_not_establish_blocks(self):
        problems, _ = self.check(pr_body=EMPTY_PR_BODY)
        self.assertTrue(any("still empty" in p for p in problems))

    def test_filled_does_not_establish_passes(self):
        self.assertEqual(self.check()[0], [])

    def test_empty_provenance_blocks(self):
        problems, _ = self.check(result_body=EMPTY_PROVENANCE)
        self.assertTrue(any("Provenance" in p for p in problems))

    def test_missing_provenance_section_blocks(self):
        problems, _ = self.check(result_body="### Observation\n\nAUROC 0.52")
        self.assertTrue(any("Provenance" in p for p in problems))

    def test_partially_filled_provenance_passes(self):
        """One real field beats six empty ones; RDH does not police thoroughness."""
        body = "### Provenance\n\n- commit:\n- run ID: slurm-88213\n- seed:"
        self.assertEqual(self.check(result_body=body)[0], [])

    def test_low_risk_work_is_untouched(self):
        """The checks exist for evidence, not for every change."""
        problems, _ = self.check(evidence=False, pr_body="## Purpose\n\nx", result_body="no provenance")
        self.assertEqual(problems, [])

    def test_config_can_disable_each_check(self):
        relaxed = Config(require_does_not_establish=False, require_provenance=False)
        problems, _ = self.check(config=relaxed, pr_body=EMPTY_PR_BODY, result_body=EMPTY_PROVENANCE)
        self.assertEqual(problems, [])

    def test_unavailable_pr_body_warns_instead_of_blocking(self):
        """Being offline must never block work the researcher has finished."""
        problems, warnings = self.check(pr_body=None, available=False)
        self.assertEqual(problems, [])
        self.assertTrue(any("not checked" in w for w in warnings))


class NextCommandTests(unittest.TestCase):
    """The mechanical next step — never a decision on the researcher's behalf."""

    def test_every_state_is_covered(self):
        for state in STATES:
            with self.subTest(state=state):
                command = next_command(state, issue=7)
                note = next_command_note(state)
                self.assertTrue(command or note, f"{state} offers neither a command nor a reason")

    def test_terminal_states_offer_no_command(self):
        for state in ("READY_TO_MERGE", "DONE", "DEFERRED", "ABANDONED", "BLOCKED"):
            with self.subTest(state=state):
                self.assertIsNone(next_command(state, issue=7))
                self.assertTrue(next_command_note(state))

    def test_ready_to_merge_says_the_researcher_merges(self):
        self.assertIn("researcher merges", next_command_note("READY_TO_MERGE"))

    def test_gate_outcomes_are_offered_as_choices_not_chosen(self):
        """A CLI that pre-selected `passed` would hollow out the gate."""
        for state in ("DESIGN_GATE", "EVIDENCE_GATE", "KNOWLEDGE_GATE"):
            with self.subTest(state=state):
                command = next_command(state, issue=7)
                self.assertIn("|", command, "the outcome must remain a choice")
                self.assertIn("passed", command)

    def test_issue_number_is_substituted(self):
        self.assertIn("start 7", next_command("READY", issue=7))
        self.assertIn("<issue>", next_command("READY"))

    def test_unknown_state_is_not_an_error(self):
        self.assertIsNone(next_command("NONSENSE"))
        self.assertIsNone(next_command_note("NONSENSE"))


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
