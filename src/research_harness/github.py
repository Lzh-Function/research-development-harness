"""GitHub access through the ``gh`` CLI.

Everything GitHub-facing funnels through :class:`GitHubClient`, which:

* always executes argument vectors with ``shell=False`` (SPEC 40);
* passes long text via ``--body-file`` temporary files, never as an argument
  that a shell could re-interpret;
* classifies failures into *auth*, *unavailable* (offline/5xx/rate limit) and
  *other*, retrying only the transient class;
* is fully substitutable in tests by injecting a fake runner, so no automated
  test needs a real GitHub account (SPEC 63).

The client performs no scientific judgement: it moves structured text.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import GitHubAuthError, GitHubError, GitHubUnavailableError
from .proc import CommandResult, CommandRunner, SubprocessRunner
from .records import RECORD_TAG, Record, parse_marker, parse_record
from .util import body_file

_AUTH_HINTS = (
    "gh auth login",
    "authentication",
    "not logged into",
    "bad credentials",
    "http 401",
    "http 403",
    "requires authentication",
)
_NO_REPO_HINTS = (
    "no git remotes found",
    "none of the git remotes configured for this repository",
    "could not determine the current repository",
    "not a git repository",
)
_UNAVAILABLE_HINTS = (
    "could not resolve host",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "dial tcp",
    "tls handshake",
    "i/o timeout",
    "timed out",
    "timeout",
    "temporary failure in name resolution",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "server error",
    "rate limit",
    "try again",
)


def classify_failure(result: CommandResult) -> str:
    """Return ``"auth"``, ``"unavailable"``, ``"missing"`` or ``"other"``."""
    if result.returncode in (126, 127):
        return "missing"
    text = (result.stderr + "\n" + result.stdout).lower()
    if any(hint in text for hint in _NO_REPO_HINTS):
        return "norepo"
    if any(hint in text for hint in _AUTH_HINTS):
        return "auth"
    if any(hint in text for hint in _UNAVAILABLE_HINTS):
        return "unavailable"
    return "other"


def parse_json_stream(text: str) -> Any:
    """Parse ``gh api --paginate`` output.

    ``--paginate`` concatenates one JSON document per page; a single request
    returns exactly one.  Concatenated arrays are flattened into one list.
    """
    decoder = json.JSONDecoder()
    index = 0
    documents: list[Any] = []
    length = len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if index >= length:
            break
        value, index = decoder.raw_decode(text, index)
        documents.append(value)
    if not documents:
        return None
    if len(documents) == 1:
        return documents[0]
    if all(isinstance(doc, list) for doc in documents):
        flattened: list[Any] = []
        for doc in documents:
            flattened.extend(doc)
        return flattened
    return documents


@dataclass
class GitHubIssue:
    number: int
    title: str = ""
    body: str = ""
    state: str = "OPEN"
    url: str = ""
    labels: list[str] = field(default_factory=list)
    created_at: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "GitHubIssue":
        labels = data.get("labels") or []
        names = [lab.get("name", "") if isinstance(lab, dict) else str(lab) for lab in labels]
        return cls(
            number=int(data.get("number", 0)),
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            state=str(data.get("state", "OPEN")).upper(),
            url=str(data.get("url") or data.get("html_url") or ""),
            labels=[n for n in names if n],
            created_at=str(data.get("createdAt") or data.get("created_at") or ""),
        )


@dataclass
class GitHubPR:
    number: int
    title: str = ""
    body: str = ""
    state: str = "OPEN"
    url: str = ""
    draft: bool = True
    head: str = ""
    base: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "GitHubPR":
        head = data.get("headRefName") or (data.get("head") or {}).get("ref") or ""
        base = data.get("baseRefName") or (data.get("base") or {}).get("ref") or ""
        state = str(data.get("state", "OPEN")).upper()
        if data.get("merged") or data.get("mergedAt"):
            state = "MERGED"
        return cls(
            number=int(data.get("number", 0)),
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            state=state,
            url=str(data.get("url") or data.get("html_url") or ""),
            draft=bool(data.get("isDraft", data.get("draft", False))),
            head=str(head),
            base=str(base),
        )


class GitHubClient:
    """Thin, retrying, injection-friendly wrapper around ``gh``."""

    def __init__(
        self,
        *,
        repo: str | None = None,
        cwd: Path | None = None,
        runner: CommandRunner | None = None,
        tmp_dir: Path | None = None,
        gh_path: str = "gh",
        max_attempts: int = 3,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repo = repo
        self.cwd = Path(cwd) if cwd else None
        self.runner: CommandRunner = runner or SubprocessRunner()
        self.tmp_dir = Path(tmp_dir) if tmp_dir else None
        self.gh_path = gh_path
        self.max_attempts = max(1, max_attempts)
        self.backoff = backoff
        self._sleep = sleep

    # ----------------------------------------------------------------- plumbing

    #: `gh repo ...` takes the repository as a positional argument and rejects
    #: `--repo` outright ("unknown flag"). Adding it silently broke every
    #: `repo view` call, which then failed soft and returned None.
    _NO_REPO_FLAG: frozenset[str] = frozenset({"repo", "api", "auth", "version"})

    def _argv(self, args: Sequence[str], *, repo_scoped: bool = True) -> list[str]:
        argv = [self.gh_path, *args]
        if repo_scoped and self.repo and args and args[0].lstrip("-") not in self._NO_REPO_FLAG:
            argv.extend(["--repo", self.repo])
        return argv

    def run(self, args: Sequence[str], *, repo_scoped: bool = True, retry: bool = True) -> CommandResult:
        argv = self._argv(args, repo_scoped=repo_scoped)
        attempts = self.max_attempts if retry else 1
        result = self.runner.run(argv, cwd=self.cwd)
        for attempt in range(1, attempts):
            if result.ok or classify_failure(result) != "unavailable":
                break
            self._sleep(self.backoff * (2 ** (attempt - 1)))
            result = self.runner.run(argv, cwd=self.cwd)
        return result

    def check(self, args: Sequence[str], *, repo_scoped: bool = True, retry: bool = True) -> CommandResult:
        result = self.run(args, repo_scoped=repo_scoped, retry=retry)
        if result.ok:
            return result
        kind = classify_failure(result)
        message = result.combined() or f"gh exited with {result.returncode}"
        if kind == "missing":
            raise GitHubUnavailableError(
                "GitHub CLI (gh) is not installed or not on PATH",
                hint="Install gh from https://cli.github.com/ — RDH never installs it for you.",
            )
        if kind == "norepo":
            raise GitHubError(
                "no GitHub repository is configured for this checkout",
                hint="Add a remote (git remote add origin git@github.com:owner/name.git), "
                "or set github.repo in .research-harness/config.toml.",
            )
        if kind == "auth":
            raise GitHubAuthError(f"GitHub authentication failed: {message}", hint="Run: gh auth login")
        if kind == "unavailable":
            raise GitHubUnavailableError(
                f"GitHub is unreachable: {message}",
                hint="Records are queued in the outbox; run `rh sync` when back online.",
            )
        # Name the operation, not the whole argument vector: a --body-file path
        # in the error tells the researcher nothing and hides the real cause.
        raise GitHubError(f"gh {' '.join(args[:2])} failed: {message}")

    def json(self, args: Sequence[str], *, repo_scoped: bool = True) -> Any:
        result = self.check(args, repo_scoped=repo_scoped)
        try:
            return parse_json_stream(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"could not parse gh JSON output: {exc}") from None

    # ------------------------------------------------------------------- status

    def available(self) -> bool:
        return self.run(["--version"], repo_scoped=False, retry=False).ok

    def authenticated(self) -> tuple[bool, str]:
        result = self.run(["auth", "status"], repo_scoped=False, retry=False)
        return result.ok, result.combined()

    def resolve_repo(self) -> str | None:
        if self.repo:
            return self.repo
        # Retried: a transient failure here would otherwise cache a negative
        # result and turn every later call into "could not resolve repository".
        result = self.run(["repo", "view", "--json", "nameWithOwner"], repo_scoped=False)
        if not result.ok:
            return None
        try:
            data = parse_json_stream(result.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            name = data.get("nameWithOwner")
            if name:
                self.repo = str(name)
                return self.repo
        return None

    # ------------------------------------------------------------------- issues

    def issue_create(self, title: str, body: str, *, labels: Iterable[str] = ()) -> GitHubIssue:
        with body_file(body, dir=self.tmp_dir) as path:
            args = ["issue", "create", "--title", title, "--body-file", str(path)]
            for label in labels:
                if label:
                    args.extend(["--label", label])
            result = self.check(args)
        number = _number_from_url(result.out)
        if number is None:
            raise GitHubError(f"could not determine the created issue number from: {result.out!r}")
        return GitHubIssue(number=number, title=title, body=body, url=result.out.strip())

    def issue_view(self, number: int) -> GitHubIssue:
        data = self.json(
            ["issue", "view", str(number), "--json", "number,title,body,state,url,labels"]
        )
        if not isinstance(data, dict):
            raise GitHubError(f"unexpected issue payload for #{number}")
        return GitHubIssue.from_json(data)

    def issue_list(
        self,
        *,
        state: str = "open",
        limit: int = 50,
        label: str | None = None,
        with_body: bool = False,
    ) -> list[GitHubIssue]:
        fields = "number,title,state,url,labels,createdAt"
        if with_body:
            # Needed to tell Work Issues from ordinary ones: the rh:work marker
            # lives in the body.
            fields += ",body"
        args = ["issue", "list", "--state", state, "--limit", str(limit), "--json", fields]
        if label:
            args.extend(["--label", label])
        data = self.json(args)
        return [GitHubIssue.from_json(item) for item in data or [] if isinstance(item, dict)]

    def issue_comment(self, number: int, body: str) -> str:
        with body_file(body, dir=self.tmp_dir) as path:
            result = self.check(["issue", "comment", str(number), "--body-file", str(path)])
        return result.out.strip()

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        repo = self.repo or self.resolve_repo()
        if not repo:
            # Re-run the resolution through check() so the caller sees the real
            # cause — offline, unauthenticated, or genuinely not a GitHub repo —
            # instead of a generic "could not resolve" that hides all three.
            self.check(["repo", "view", "--json", "nameWithOwner"], repo_scoped=False)
            raise GitHubError(
                "could not resolve the GitHub repository (owner/name)",
                hint="Set github.repo in .research-harness/config.toml, or add a GitHub remote.",
            )
        data = self.json(
            ["api", "--paginate", f"repos/{repo}/issues/{number}/comments", "--header", "Accept: application/vnd.github+json"],
            repo_scoped=False,
        )
        if isinstance(data, dict):
            return [data]
        return [item for item in (data or []) if isinstance(item, dict)]

    # Deliberately absent: `issue edit --body` and `pr comment`.
    # Rewriting a Work Issue body would erase historical intent (SPEC 29), and
    # PR comments are not a record store (SPEC 25). Providing the wrappers
    # would only make those mistakes easy to reach.

    def issue_close(self, number: int, *, comment: str | None = None) -> None:
        """Close a Work Issue. Closing is reversible; deletion is never done."""
        args = ["issue", "close", str(number)]
        if comment:
            # `gh issue close` has no --body-file; the text is still passed as
            # a single argv element, never through a shell.
            args.extend(["--comment", comment])
        self.check(args)

    # ---------------------------------------------------------------- records

    def records(self, issue: int) -> list[Record]:
        """All durable records attached to a Work Issue, oldest first."""
        out: list[Record] = []
        for comment in self.issue_comments(issue):
            body = str(comment.get("body") or "")
            record = parse_record(
                body,
                comment_id=str(comment.get("id")) if comment.get("id") is not None else None,
                url=str(comment.get("html_url") or ""),
                author=str((comment.get("user") or {}).get("login") or ""),
            )
            if record is not None:
                if record.issue is None:
                    record.issue = issue
                out.append(record)
        return out

    def record_ids(self, issue: int) -> set[str]:
        """UUIDs of records already present remotely (idempotent sync)."""
        ids: set[str] = set()
        for comment in self.issue_comments(issue):
            payload = parse_marker(str(comment.get("body") or ""), RECORD_TAG)
            if payload and payload.get("id"):
                ids.add(str(payload["id"]))
        return ids

    def post_record(self, record: Record, *, known_ids: set[str] | None = None) -> tuple[str, bool]:
        """Post a record unless its UUID already exists remotely.

        Returns ``(url_or_empty, created)``.
        """
        issue = record.issue
        if issue is None:
            raise GitHubError("record has no issue number")
        existing = known_ids if known_ids is not None else self.record_ids(issue)
        if record.id in existing:
            return "", False
        url = self.issue_comment(issue, record.to_comment())
        return url, True

    # ----------------------------------------------------------------- pull requests

    def pr_create(self, *, title: str, body: str, head: str, base: str | None = None, draft: bool = True) -> GitHubPR:
        with body_file(body, dir=self.tmp_dir) as path:
            args = ["pr", "create", "--title", title, "--body-file", str(path), "--head", head]
            if base:
                args.extend(["--base", base])
            if draft:
                args.append("--draft")
            result = self.check(args)
        number = _number_from_url(result.out)
        if number is None:
            raise GitHubError(f"could not determine the created PR number from: {result.out!r}")
        return GitHubPR(number=number, title=title, body=body, url=result.out.strip(), draft=draft, head=head, base=base or "")

    def pr_view(self, ref: str | int) -> GitHubPR | None:
        data = self.json(
            ["pr", "view", str(ref), "--json", "number,title,body,state,url,isDraft,headRefName,baseRefName,mergedAt"]
        )
        if not isinstance(data, dict):
            return None
        return GitHubPR.from_json(data)

    def pr_for_branch(self, branch: str) -> GitHubPR | None:
        data = self.json(
            [
                "pr", "list", "--head", branch, "--state", "all", "--limit", "10",
                "--json", "number,title,body,state,url,isDraft,headRefName,baseRefName,mergedAt",
            ]
        )
        items = [item for item in (data or []) if isinstance(item, dict)]
        if not items:
            return None
        open_first = sorted(items, key=lambda d: 0 if str(d.get("state", "")).upper() == "OPEN" else 1)
        return GitHubPR.from_json(open_first[0])

    def pr_edit_body(self, number: int, body: str) -> None:
        with body_file(body, dir=self.tmp_dir) as path:
            self.check(["pr", "edit", str(number), "--body-file", str(path)])

    def default_branch(self) -> str | None:
        args = ["repo", "view"]
        if self.repo:
            args.append(self.repo)  # positional, never --repo
        args.extend(["--json", "defaultBranchRef"])
        result = self.run(args, repo_scoped=False, retry=False)
        if not result.ok:
            return None
        try:
            data = parse_json_stream(result.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            ref = data.get("defaultBranchRef") or {}
            name = ref.get("name") if isinstance(ref, dict) else None
            return str(name) if name else None
        return None


def _number_from_url(text: str) -> int | None:
    """``https://github.com/o/n/issues/184`` → ``184``."""
    candidate = (text or "").strip().rstrip("/")
    if not candidate:
        return None
    tail = candidate.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else None
