"""Research Questions as first-class objects.

A Research Question is the long-lived thing a project is about; Work Issues
are attempts on it. `rh rq` gathers what has been recorded under one — and
deliberately stops short of deciding what the answer now is.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support  # noqa: E402
from support import SandboxTestCase  # noqa: E402


class RQTestCase(SandboxTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.sandbox.make_repo()
        self.sandbox.rh(["adopt", str(self.repo)], cwd=self.sandbox.base, check=True)

    def rh(self, args, *, check=False, env=None):
        return self.sandbox.rh_local(self.repo, args, check=check, env=env)

    def rh_json(self, args, *, env=None):
        return json.loads(self.rh([*args, "--json"], check=True, env=env).stdout)

    def make_rq(self, title):
        return self.rh_json(["rq", "create", "--title", title])["rq"]

    def start_work(self, issue, *, seed=None):
        """Branch, first commit, then the Draft PR — as GitHub requires."""
        payload = self.rh_json(["work", "start", str(issue)])
        if payload.get("pr") is None:
            name = seed or f"work_{issue}.py"
            (self.repo / name).write_text(f"# work on #{issue}\n", encoding="utf-8")
            self.sandbox.git(self.repo, ["add", "-A"])
            self.sandbox.git(self.repo, ["commit", "-q", "-m", f"begin work on #{issue}"])
            self.sandbox.git(self.repo, ["push", "-q", "origin", "HEAD"])
            payload = {**payload, **self.rh_json(["pr", "create"])}
        return payload

    def make_work(self, title, *, rq=None, records=(), evidence=True, risk="high", kind="experiment"):
        args = ["issue", "create", "--title", title, "--kind", kind, "--risk", risk,
                "--body", f"## Purpose\n\n{title}"]
        if evidence:
            args.append("--evidence-required")
        if rq is not None:
            args.extend(["--rq", str(rq)])
        number = self.rh_json(args)["issue"]
        for record_args, body in records:
            self.rh_json(["record", *record_args, "--issue", str(number), "--body", body])
        return number


class RQCreationTests(RQTestCase):
    def test_title_is_prefixed_and_marked(self):
        number = self.make_rq("When does chirality information emerge?")
        issue = self.sandbox.gh_data()["issues"][str(number)]
        self.assertTrue(issue["title"].startswith("[RQ] "))
        self.assertIn("<!-- rh:rq", issue["body"])
        self.assertNotIn("rh:work", issue["body"])

    def test_existing_prefix_is_not_doubled(self):
        number = self.make_rq("[RQ] Already prefixed")
        self.assertEqual(self.sandbox.gh_data()["issues"][str(number)]["title"], "[RQ] Already prefixed")

    def test_body_defaults_to_the_template(self):
        number = self.make_rq("Q")
        body = self.sandbox.gh_data()["issues"][str(number)]["body"]
        self.assertIn("## Question", body)
        self.assertIn("## What Would Change Our Mind", body)

    def test_custom_body_is_used(self):
        self.rh_json(["rq", "create", "--title", "Q", "--body", "## Question\n\n独自の本文"])
        self.assertIn("独自の本文", self.sandbox.gh_data()["issues"]["1"]["body"])

    def test_dry_run_creates_nothing(self):
        result = self.rh(["rq", "create", "--title", "Q", "--dry-run"], check=True)
        self.assertIn("[dry-run]", result.stdout)
        self.assertEqual(self.sandbox.gh_data()["issues"], {})

    def test_a_research_question_is_not_a_work_issue(self):
        """`rh log` and `rh work start` must not mistake one for the other."""
        rq = self.make_rq("Q")
        self.assertEqual(self.rh_json(["log"])["entries"], [])
        result = self.rh(["work", "start", str(rq)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rh:work marker", result.stderr)


class RQListTests(RQTestCase):
    def test_lists_questions_with_work_unit_counts(self):
        first = self.make_rq("Chirality emergence")
        second = self.make_rq("Batch effect correction")
        self.make_work("probe A", rq=first)
        self.make_work("probe B", rq=first)
        self.make_work("harmony vs scvi", rq=second)
        self.make_work("unrelated refactor", kind="refactor", risk="low", evidence=False)
        payload = self.rh_json(["rq", "list"])["research_questions"]
        counts = {item["rq"]: item["work_units"] for item in payload}
        self.assertEqual(counts, {first: 2, second: 1})

    def test_empty_repository_says_so(self):
        result = self.rh(["rq", "list"], check=True)
        self.assertIn("no Research Question issues found", result.stdout)
        self.assertIn("rh rq create", result.stdout)


class RQShowTests(RQTestCase):
    def setUp(self):
        super().setUp()
        self.rq = self.make_rq("When does chirality information emerge?")
        self.linear = self.make_work(
            "Linear probe across layers",
            rq=self.rq,
            records=[
                (["gate", "--gate", "design", "--outcome", "passed"], "### Outcome\npassed"),
                (["result"],
                 "### Observation\nlayer 5 で AUROC 0.52\n\n### Supports\n線形読み出し可能性は深層で低下する\n"
                 "\n### Does NOT Support\n情報が失われていること\n\n### Provenance\n- run ID: slurm-1"),
            ],
        )
        self.mlp = self.make_work(
            "MLP probe follow-up",
            rq=self.rq,
            records=[(["gate", "--gate", "design", "--outcome", "passed"], "### Outcome\npassed")],
        )
        self.unrelated = self.make_work("Unrelated audit", kind="analysis", risk="medium", evidence=False)

    def test_gathers_only_work_under_this_question(self):
        payload = self.rh_json(["rq", "show", str(self.rq)])
        self.assertEqual([u["issue"] for u in payload["work_units"]], [self.linear, self.mlp])
        self.assertNotIn(self.unrelated, [u["issue"] for u in payload["work_units"]])

    def test_reproduces_supports_and_limits_verbatim(self):
        payload = self.rh_json(["rq", "show", str(self.rq)])
        unit = next(u for u in payload["work_units"] if u["issue"] == self.linear)
        self.assertEqual(unit["results"][0]["supports"], "線形読み出し可能性は深層で低下する")
        self.assertEqual(unit["results"][0]["does_not_support"], "情報が失われていること")

    def test_reports_state_per_work_unit(self):
        payload = self.rh_json(["rq", "show", str(self.rq)])
        states = {u["issue"]: u["state"] for u in payload["work_units"]}
        self.assertEqual(states[self.mlp], "READY")
        self.assertEqual(payload["result_count"], 1)

    def test_human_output_refuses_to_synthesise_an_answer(self):
        """The aggregation must not read as a conclusion."""
        out = self.rh(["rq", "show", str(self.rq)], check=True).stdout
        self.assertIn("supports          線形読み出し可能性は深層で低下する", out)
        self.assertIn("does not support  情報が失われていること", out)
        self.assertIn("for the researcher to decide", out)
        self.assertIn("(no Result Record yet)", out)

    def test_question_without_work_units_guides_the_next_step(self):
        empty = self.make_rq("Untouched question")
        out = self.rh(["rq", "show", str(empty)], check=True).stdout
        self.assertIn("No work units reference this question yet", out)
        self.assertIn(f"--rq {empty}", out)

    def test_log_can_be_filtered_by_question(self):
        entries = self.rh_json(["log", "--rq", str(self.rq)])["entries"]
        self.assertEqual({e["issue"] for e in entries}, {self.linear, self.mlp})
        self.assertNotIn(self.unrelated, {e["issue"] for e in entries})

    def test_log_without_the_filter_still_sees_everything(self):
        entries = self.rh_json(["log"])["entries"]
        self.assertIn(self.unrelated, {e["issue"] for e in entries})


if __name__ == "__main__":
    unittest.main()


class RQStateSourceTests(RQTestCase):
    """Work-started is derived from the PR linkage line, not assumed."""

    def test_started_and_unstarted_units_are_distinguished(self):
        rq = self.make_rq("Q")
        started = self.make_work("Started work", rq=rq, records=[
            (["gate", "--gate", "design", "--outcome", "passed"], "### Outcome\npassed")])
        unstarted = self.make_work("Not started", rq=rq, records=[
            (["gate", "--gate", "design", "--outcome", "passed"], "### Outcome\npassed")])
        self.start_work(started)

        payload = self.rh_json(["rq", "show", str(rq)])
        states = {u["issue"]: u["state"] for u in payload["work_units"]}
        prs = {u["issue"]: u["pr"] for u in payload["work_units"]}
        self.assertEqual(states[unstarted], "READY", "work with no PR has not started")
        self.assertEqual(states[started], "VALIDATING", "work with a Draft PR is under way")
        self.assertIsNone(prs[unstarted])
        self.assertIsNotNone(prs[started])

    def test_pr_linkage_survives_a_fresh_clone(self):
        """A second clone has no link store, so the mapping must come from GitHub."""
        rq = self.make_rq("Q")
        issue = self.make_work("Started work", rq=rq, records=[
            (["gate", "--gate", "design", "--outcome", "passed"], "### Outcome\npassed")])
        self.start_work(issue)
        self.sandbox.git(self.repo, ["add", "-A"])
        self.sandbox.git(self.repo, ["commit", "-q", "-m", "adopt"], check=False)

        other = self.sandbox.base / "clone"
        self.sandbox.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        self.assertFalse((other / ".git" / "research-harness" / "links").exists())
        payload = json.loads(
            self.sandbox.run(
                [sys.executable, str(other / ".research-harness" / "bin" / "rh"), "rq", "show", str(rq), "--json"],
                cwd=other, check=True,
            ).stdout
        )
        unit = next(u for u in payload["work_units"] if u["issue"] == issue)
        self.assertIsNotNone(unit["pr"])
        self.assertEqual(unit["state"], "VALIDATING")
