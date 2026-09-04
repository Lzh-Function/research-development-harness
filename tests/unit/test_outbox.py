"""Outbox queueing and idempotent replay."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.github import GitHubClient  # noqa: E402
from research_harness.outbox import Outbox  # noqa: E402
from research_harness.proc import FakeRunner, fail, ok  # noqa: E402
from research_harness.records import Record  # noqa: E402


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outbox = Outbox(Path(self.tmp.name))

    def client(self, runner):
        return GitHubClient(repo="octo/research", runner=runner, sleep=lambda _s: None)

    def test_enqueue_and_read_back(self):
        record = Record(kind="checkpoint", issue=4, body="## Research Harness Checkpoint\n\n### Next Action\ngo")
        path = self.outbox.enqueue(record, error="offline")
        self.assertTrue(path.exists())
        self.assertEqual(self.outbox.pending_count(), 1)
        entries = self.outbox.entries()
        self.assertEqual(entries[0].record.id, record.id)
        self.assertEqual(entries[0].record.issue, 4)
        self.assertEqual(entries[0].record.section("Next Action"), "go")
        self.assertEqual(entries[0].last_error, "offline")

    def test_record_without_issue_is_rejected(self):
        from research_harness.errors import RecordError

        with self.assertRaises(RecordError):
            self.outbox.enqueue(Record(kind="result"))

    def test_sync_posts_pending_records(self):
        record = Record(kind="result", issue=4, body="b")
        self.outbox.enqueue(record)
        runner = FakeRunner()
        runner.register(("gh", "api"), ok("[]"))
        runner.register(("gh", "issue", "comment"), ok("https://github.com/octo/research/issues/4#issuecomment-1"))
        report = self.outbox.sync(self.client(runner))
        self.assertEqual(len(report["posted"]), 1)
        self.assertEqual(self.outbox.pending_count(), 0)

    def test_sync_is_idempotent_for_already_present_records(self):
        record = Record(kind="result", issue=4, body="b")
        self.outbox.enqueue(record)
        comments = json.dumps([{"id": 1, "body": record.to_comment(), "html_url": "u", "user": {"login": "x"}}])
        runner = FakeRunner()
        runner.register(("gh", "api"), ok(comments))
        runner.register(("gh", "issue", "comment"), ok("MUST NOT HAPPEN"))
        report = self.outbox.sync(self.client(runner))
        self.assertEqual(len(report["duplicate"]), 1)
        self.assertEqual(len(report["posted"]), 0)
        self.assertEqual(self.outbox.pending_count(), 0)
        posted = [call for call, _ in runner.calls if call[:3] == ("gh", "issue", "comment")]
        self.assertEqual(posted, [])

    def test_repeated_sync_posts_exactly_once(self):
        record = Record(kind="checkpoint", issue=4, body="b")
        self.outbox.enqueue(record)
        state = {"comments": []}

        def responder(argv, stdin):
            if argv[1] == "api":
                return ok(json.dumps(state["comments"]))
            index = argv.index("--body-file")
            state["comments"].append({"id": len(state["comments"]) + 1, "body": Path(argv[index + 1]).read_text(encoding="utf-8")})
            return ok("https://github.com/octo/research/issues/4#issuecomment-1")

        runner = FakeRunner(default=responder)
        client = self.client(runner)
        self.outbox.sync(client)
        self.outbox.enqueue(record)  # a retry re-queues the same UUID
        self.outbox.sync(client)
        self.assertEqual(len(state["comments"]), 1)

    def test_failed_sync_keeps_the_record_and_counts_attempts(self):
        record = Record(kind="result", issue=4, body="b")
        self.outbox.enqueue(record)
        runner = FakeRunner(default=fail("dial tcp: i/o timeout"))
        report = self.outbox.sync(self.client(runner))
        self.assertEqual(len(report["failed"]), 1)
        self.assertEqual(self.outbox.pending_count(), 1)
        self.assertEqual(self.outbox.entries()[0].attempts, 1)

    def test_dry_run_changes_nothing(self):
        record = Record(kind="result", issue=4, body="b")
        self.outbox.enqueue(record)
        runner = FakeRunner()
        runner.register(("gh", "api"), ok("[]"))
        report = self.outbox.sync(self.client(runner), dry_run=True)
        self.assertEqual(len(report["posted"]), 1)
        self.assertEqual(self.outbox.pending_count(), 1)

    def test_corrupt_entries_are_skipped(self):
        self.outbox.dir.mkdir(parents=True, exist_ok=True)
        (self.outbox.dir / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(self.outbox.entries(), [])


if __name__ == "__main__":
    unittest.main()
