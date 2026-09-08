"""GitHub adapter behaviour against a fake runner: no account, no network."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: F401,E402

from research_harness.errors import GitHubAuthError, GitHubError, GitHubUnavailableError  # noqa: E402
from research_harness.github import (  # noqa: E402
    GitHubClient,
    classify_failure,
    parse_json_stream,
)
from research_harness.proc import CommandResult, FakeRunner, fail, ok  # noqa: E402
from research_harness.records import Record  # noqa: E402


def client(runner, **kwargs):
    return GitHubClient(repo="octo/research", runner=runner, sleep=lambda _s: None, **kwargs)


class ClassificationTests(unittest.TestCase):
    def test_auth(self):
        self.assertEqual(classify_failure(fail("gh auth login required")), "auth")
        self.assertEqual(classify_failure(fail("HTTP 401: Bad credentials")), "auth")

    def test_unavailable(self):
        for text in ("dial tcp: i/o timeout", "could not resolve host", "HTTP 503", "API rate limit exceeded"):
            with self.subTest(text=text):
                self.assertEqual(classify_failure(fail(text)), "unavailable")

    def test_missing_executable(self):
        self.assertEqual(classify_failure(fail("not found", code=127)), "missing")

    def test_no_repository(self):
        for text in (
            "no git remotes found",
            "none of the git remotes configured for this repository were found on GitHub",
            "could not determine the current repository",
        ):
            with self.subTest(text=text):
                self.assertEqual(classify_failure(fail(text)), "norepo")

    def test_other(self):
        self.assertEqual(classify_failure(fail("GraphQL: unexpected")), "other")


class PaginationTests(unittest.TestCase):
    def test_single_document(self):
        self.assertEqual(parse_json_stream('{"a":1}'), {"a": 1})

    def test_concatenated_pages_are_flattened(self):
        text = '[{"id":1},{"id":2}]\n[{"id":3}]\n'
        self.assertEqual([item["id"] for item in parse_json_stream(text)], [1, 2, 3])

    def test_empty_input(self):
        self.assertIsNone(parse_json_stream("   \n"))

    def test_paginated_comments_are_read_whole(self):
        pages = '[{"id":1,"body":"a"},{"id":2,"body":"b"}]\n[{"id":3,"body":"c"}]\n'
        runner = FakeRunner()
        runner.register(("gh", "api"), ok(pages))
        comments = client(runner).issue_comments(5)
        self.assertEqual([c["id"] for c in comments], [1, 2, 3])
        self.assertIn("--paginate", runner.calls[0][0])


class ErrorTranslationTests(unittest.TestCase):
    def test_auth_failure_raises_auth_error(self):
        runner = FakeRunner(default=fail("gh auth login"))
        with self.assertRaises(GitHubAuthError):
            client(runner).issue_view(1)

    def test_network_failure_raises_unavailable(self):
        runner = FakeRunner(default=fail("dial tcp: i/o timeout"))
        with self.assertRaises(GitHubUnavailableError):
            client(runner).issue_view(1)

    def test_missing_gh_raises_unavailable_with_install_hint(self):
        runner = FakeRunner(default=fail("no such file", code=127))
        with self.assertRaises(GitHubUnavailableError) as caught:
            client(runner).issue_view(1)
        self.assertIn("cli.github.com", caught.exception.hint or "")

    def test_other_failure_raises_generic(self):
        runner = FakeRunner(default=fail("GraphQL: unexpected"))
        with self.assertRaises(GitHubError):
            client(runner).issue_view(1)

    def test_missing_repository_is_actionable(self):
        """The first error a new user hits must name the fix, not dump argv."""
        runner = FakeRunner(default=fail("no git remotes found"))
        with self.assertRaises(GitHubError) as caught:
            client(runner).issue_create("T", "body")
        rendered = caught.exception.render()
        self.assertIn("no GitHub repository is configured", rendered)
        self.assertIn("git remote add origin", rendered)
        self.assertIn("github.repo", rendered)

    def test_errors_do_not_leak_the_body_file_path(self):
        runner = FakeRunner(default=fail("GraphQL: something odd"))
        with self.assertRaises(GitHubError) as caught:
            client(runner).issue_create("T", "a long body that lives in a temp file")
        message = caught.exception.message
        self.assertNotIn("--body-file", message)
        self.assertNotIn("rh-body-", message)
        self.assertIn("gh issue create", message)


class RetryTests(unittest.TestCase):
    def test_transient_failures_are_retried_then_succeed(self):
        state = {"n": 0}

        def responder(argv, stdin):
            state["n"] += 1
            if state["n"] < 3:
                return fail("dial tcp: i/o timeout")
            return ok('{"number":1,"title":"t","body":"b","state":"OPEN","url":"u","labels":[]}')

        runner = FakeRunner(default=responder)
        issue = client(runner).issue_view(1)
        self.assertEqual(issue.number, 1)
        self.assertEqual(state["n"], 3)

    def test_auth_failures_are_not_retried(self):
        runner = FakeRunner(default=fail("HTTP 401: Bad credentials"))
        with self.assertRaises(GitHubAuthError):
            client(runner).issue_view(1)
        self.assertEqual(len(runner.calls), 1)

    def test_retries_are_bounded(self):
        runner = FakeRunner(default=fail("HTTP 503"))
        with self.assertRaises(GitHubUnavailableError):
            client(runner, max_attempts=2).issue_view(1)
        self.assertEqual(len(runner.calls), 2)


class BodyFileTests(unittest.TestCase):
    def test_issue_create_uses_a_body_file_not_an_argument(self):
        captured = {}

        def responder(argv, stdin):
            captured["argv"] = argv
            index = argv.index("--body-file")
            captured["body"] = Path(argv[index + 1]).read_text(encoding="utf-8")
            return ok("https://github.com/octo/research/issues/7")

        runner = FakeRunner(default=responder)
        body = "Backticks `rm -rf /` and $(whoami) must never reach a shell.\n"
        issue = client(runner).issue_create("Title", body, labels=["research"])
        self.assertEqual(issue.number, 7)
        self.assertEqual(captured["body"], body)
        self.assertNotIn(body, captured["argv"])
        self.assertIn("--label", captured["argv"])

    def test_github_text_is_never_shell_interpreted(self):
        """Every argv element is passed verbatim; no shell is involved."""
        runner = FakeRunner(default=ok("https://github.com/octo/research/issues/1#issuecomment-1"))
        client(runner).issue_comment(1, "$(touch /tmp/pwned) `id`")
        argv, _ = runner.calls[0]
        self.assertNotIn("sh", argv[0])
        self.assertIn("--body-file", argv)

    def test_pr_create_is_draft_by_default(self):
        runner = FakeRunner(default=ok("https://github.com/octo/research/pull/1000"))
        pr = client(runner).pr_create(title="T", body="B", head="rh/1-x", base="main")
        self.assertEqual(pr.number, 1000)
        self.assertIn("--draft", runner.calls[0][0])


class IdempotencyTests(unittest.TestCase):
    def test_existing_uuid_is_not_reposted(self):
        record = Record(kind="checkpoint", issue=4, body="body")
        comments = json.dumps([{"id": 1, "body": record.to_comment(), "html_url": "u", "user": {"login": "x"}}])
        runner = FakeRunner()
        runner.register(("gh", "api"), ok(comments))
        runner.register(("gh", "issue", "comment"), ok("should-not-be-called"))
        url, created = client(runner).post_record(record)
        self.assertFalse(created)
        self.assertEqual(url, "")
        self.assertNotIn("comment", [call[0][1] if len(call[0]) > 1 else "" for call in runner.calls])

    def test_new_uuid_is_posted(self):
        runner = FakeRunner()
        runner.register(("gh", "api"), ok("[]"))
        runner.register(("gh", "issue", "comment"), ok("https://github.com/octo/research/issues/4#issuecomment-9"))
        url, created = client(runner).post_record(Record(kind="result", issue=4, body="b"))
        self.assertTrue(created)
        self.assertIn("issuecomment", url)

    def test_records_parses_only_marked_comments(self):
        record = Record(kind="result", issue=4, body="## Result Record")
        comments = json.dumps(
            [
                {"id": 1, "body": "just a human comment", "html_url": "u1", "user": {"login": "a"}},
                {"id": 2, "body": record.to_comment(), "html_url": "u2", "user": {"login": "b"}},
            ]
        )
        runner = FakeRunner()
        runner.register(("gh", "api"), ok(comments))
        records = client(runner).records(4)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kind, "result")
        self.assertEqual(records[0].author, "b")
        self.assertEqual(records[0].comment_id, "2")


class RepoFlagTests(unittest.TestCase):
    """`gh repo ...` rejects --repo; adding it broke default_branch silently."""

    def test_repo_subcommand_never_gets_the_repo_flag(self):
        runner = FakeRunner(default=ok('{"defaultBranchRef":{"name":"main"}}'))
        instance = client(runner)
        self.assertEqual(instance.default_branch(), "main")
        argv = runner.calls[0][0]
        self.assertNotIn("--repo", argv)
        self.assertIn("octo/research", argv, "the repository must be passed positionally")

    def test_issue_and_pr_subcommands_still_get_the_flag(self):
        for args in (["issue", "view", "1"], ["pr", "view", "1"], ["issue", "list"]):
            with self.subTest(args=args):
                runner = FakeRunner(default=ok("{}"))
                client(runner).run(args)
                self.assertIn("--repo", runner.calls[0][0])

    def test_api_and_auth_never_get_the_flag(self):
        for args in (["api", "repos/x/y/issues"], ["auth", "status"], ["--version"]):
            with self.subTest(args=args):
                runner = FakeRunner(default=ok("{}"))
                client(runner).run(args)
                self.assertNotIn("--repo", runner.calls[0][0])

    def test_default_branch_without_a_known_repo(self):
        runner = FakeRunner(default=ok('{"defaultBranchRef":{"name":"trunk"}}'))
        instance = GitHubClient(runner=runner, sleep=lambda _s: None)
        self.assertEqual(instance.default_branch(), "trunk")
        self.assertEqual(list(runner.calls[0][0]), ["gh", "repo", "view", "--json", "defaultBranchRef"])


class RepoResolutionTests(unittest.TestCase):
    def test_resolve_repo_from_gh(self):
        runner = FakeRunner(default=ok('{"nameWithOwner":"octo/research"}'))
        instance = GitHubClient(runner=runner, sleep=lambda _s: None)
        self.assertEqual(instance.resolve_repo(), "octo/research")

    def test_resolve_repo_failure_is_soft(self):
        runner = FakeRunner(default=fail("not a repository"))
        instance = GitHubClient(runner=runner, sleep=lambda _s: None)
        self.assertIsNone(instance.resolve_repo())

    def test_repo_flag_is_passed(self):
        runner = FakeRunner(default=ok('{"number":1}'))
        client(runner).run(["issue", "view", "1"])
        self.assertIn("--repo", runner.calls[0][0])
        self.assertIn("octo/research", runner.calls[0][0])


if __name__ == "__main__":
    unittest.main()
