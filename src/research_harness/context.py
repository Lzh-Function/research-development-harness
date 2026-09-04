"""Session assembly and ``rh context`` payload.

A :class:`Session` binds together the repository, its harness installation,
the local link/outbox/cache state and (lazily) the GitHub client.  Every CLI
command starts from one.

Context gathering is deliberately degradable: with ``gh`` missing, offline, or
unauthenticated, the session still reports repository facts and falls back to
locally cached records, so ``rh status`` and ``rh context`` remain useful on a
plane.  Nothing here interprets research content.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import RUNTIME_VERSION
from .config import Config, Installation
from .errors import GitHubError, HarnessError
from .git import GitRepo, parse_github_remote
from .github import GitHubClient, GitHubIssue, GitHubPR
from .outbox import Outbox
from .proc import CommandRunner, SubprocessRunner
from .records import Record, WorkMarker
from .state import LinkStore, WorkLink, issue_from_branch
from .util import atomic_write, iso_timestamp


@dataclass
class ContextPayload:
    """Shape documented in SPEC 35 (plus a few explicitly additive fields)."""

    repo_root: str
    repo: str | None
    branch: str | None
    head: str | None
    dirty: bool
    changed_paths: list[str]
    remote: str | None
    pr: int | None
    issue: int | None
    harness_version: str
    outbox_pending: int
    adopted: bool = False
    bundle_version: str | None = None
    detached: bool = False
    default_branch: str | None = None
    github_available: bool = False
    generated_at: str = field(default_factory=iso_timestamp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "repo": self.repo,
            "branch": self.branch,
            "head": self.head,
            "dirty": self.dirty,
            "changed_paths": self.changed_paths,
            "remote": self.remote,
            "pr": self.pr,
            "issue": self.issue,
            "harness_version": self.harness_version,
            "outbox_pending": self.outbox_pending,
            "adopted": self.adopted,
            "bundle_version": self.bundle_version,
            "detached": self.detached,
            "default_branch": self.default_branch,
            "github_available": self.github_available,
            "generated_at": self.generated_at,
        }


class Session:
    """Everything a deterministic command needs, assembled once."""

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        runner: CommandRunner | None = None,
        gh_runner: CommandRunner | None = None,
        repo_override: str | None = None,
        offline: bool = False,
    ) -> None:
        self.runner: CommandRunner = runner or SubprocessRunner()
        self.git = GitRepo.discover(root, self.runner)
        self.offline = offline
        self._gh_runner = gh_runner or self.runner
        self._repo_override = repo_override
        self._github: GitHubClient | None = None
        self._resolved_slug: str | None = None
        self._records_cache: dict[int, list[Record]] = {}
        self.installation: Installation | None = Installation.locate_optional(self.git.root)
        self.config: Config = self.installation.config if self.installation else Config()
        self.state_dir: Path = self.git.state_dir()
        self.links = LinkStore(self.state_dir)
        self.outbox = Outbox(self.state_dir)

    # ------------------------------------------------------------------ github

    def _static_repo_slug(self) -> str | None:
        """Repository slug derivable without contacting GitHub."""
        if self._repo_override:
            return self._repo_override
        if self.config.github_repo:
            return self.config.github_repo
        url = self.git.remote_url(self.config.remote)
        parsed = parse_github_remote(url or "")
        return f"{parsed[0]}/{parsed[1]}" if parsed else None

    @property
    def repo_slug(self) -> str | None:
        """Slug from config/remote, falling back to ``gh``'s own resolution.

        The fallback matters for remotes gh understands but a URL parser does
        not: ssh aliases, insteadOf rewrites, enterprise hosts.
        """
        static = self._static_repo_slug()
        if static:
            return static
        if self._resolved_slug is not None or self.offline:
            return self._resolved_slug or None
        try:
            self._resolved_slug = self.github.resolve_repo() or ""
        except HarnessError:
            self._resolved_slug = ""
        return self._resolved_slug or None

    @property
    def github(self) -> GitHubClient:
        if self._github is None:
            self._github = GitHubClient(
                repo=self._static_repo_slug(),
                cwd=self.git.root,
                runner=self._gh_runner,
                tmp_dir=self.state_dir / "tmp",
            )
        return self._github

    def github_available(self) -> bool:
        if self.offline:
            return False
        try:
            return self.github.available()
        except HarnessError:
            return False

    # -------------------------------------------------------------------- work

    def current_link(self) -> WorkLink | None:
        """Branch → work linkage, from the local store or the branch name."""
        branch = self.git.branch()
        if not branch:
            return None
        link = self.links.get(branch)
        if link is not None:
            return link
        issue = issue_from_branch(branch, self.config.branch_prefix)
        if issue is None:
            return None
        return WorkLink(branch=branch, issue=issue)

    def save_link(self, link: WorkLink) -> None:
        self.links.put(link)

    def resolve_pr(self, link: WorkLink | None) -> int | None:
        if link and link.pr:
            return link.pr
        if link is None or self.offline:
            return None
        try:
            pr = self.github.pr_for_branch(link.branch)
        except HarnessError:
            return None
        if pr is None:
            return None
        link.pr = pr.number
        self.save_link(link)
        return pr.number

    # ----------------------------------------------------------------- records

    def cache_path(self, issue: int) -> Path:
        return self.state_dir / "cache" / f"issue-{issue}.json"

    def cache_records(self, issue: int, records: list[Record], *, issue_obj: GitHubIssue | None = None) -> None:
        payload = {
            "issue": issue,
            "fetched_at": iso_timestamp(),
            "records": [r.to_dict() for r in records],
        }
        if issue_obj is not None:
            payload["issue_title"] = issue_obj.title
            payload["issue_body"] = issue_obj.body
            payload["issue_state"] = issue_obj.state
        atomic_write(self.cache_path(issue), json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    def cached_payload(self, issue: int) -> dict[str, Any] | None:
        path = self.cache_path(issue)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def records(self, issue: int, *, allow_cache: bool = True, refresh: bool = True) -> tuple[list[Record], bool]:
        """Return ``(records, from_github)`` for a Work Issue.

        Locally queued (outbox) records are merged in so that state derivation
        reflects what the researcher recorded even before it reaches GitHub.
        """
        remote_records: list[Record] | None = None
        if refresh and not self.offline:
            try:
                remote_records = self.github.records(issue)
            except HarnessError:
                remote_records = None
        from_github = remote_records is not None
        if remote_records is None and allow_cache:
            payload = self.cached_payload(issue)
            if payload:
                remote_records = [_record_from_dict(item) for item in payload.get("records", [])]
                remote_records = [r for r in remote_records if r is not None]
        records = list(remote_records or [])
        seen = {r.id for r in records}
        for entry in self.outbox.entries():
            if entry.record.issue == issue and entry.record.id not in seen:
                records.append(entry.record)
        # Stable sort: comments arrive in chronological order from GitHub, so
        # records sharing a timestamp keep the order they were written in.
        records.sort(key=lambda r: r.created_at)
        if from_github:
            self._records_cache[issue] = records
        return records, from_github

    def issue(self, number: int) -> GitHubIssue | None:
        if self.offline:
            return self._cached_issue(number)
        try:
            return self.github.issue_view(number)
        except HarnessError:
            return self._cached_issue(number)

    def _cached_issue(self, number: int) -> GitHubIssue | None:
        payload = self.cached_payload(number)
        if not payload or "issue_body" not in payload:
            return None
        return GitHubIssue(
            number=number,
            title=str(payload.get("issue_title", "")),
            body=str(payload.get("issue_body", "")),
            state=str(payload.get("issue_state", "OPEN")),
        )

    def work_marker(self, issue_obj: GitHubIssue | None, link: WorkLink | None) -> WorkMarker | None:
        if issue_obj is not None:
            marker = WorkMarker.parse(issue_obj.body)
            if marker is not None:
                return marker
        if link is not None:
            return WorkMarker(kind=link.kind, risk=link.risk, evidence_required=link.evidence_required)
        return None

    def pull_request(self, number: int | None) -> GitHubPR | None:
        if number is None or self.offline:
            return None
        try:
            return self.github.pr_view(number)
        except (HarnessError, GitHubError):
            return None

    # ----------------------------------------------------------------- context

    def context(self, *, include_github: bool = True) -> ContextPayload:
        branch = self.git.branch()
        link = self.current_link()
        pr = link.pr if link else None
        if pr is None and include_github and not self.offline:
            pr = self.resolve_pr(link)
        manifest = self.installation.manifest if self.installation else None
        return ContextPayload(
            repo_root=str(self.git.root),
            repo=self.repo_slug,
            branch=branch,
            head=self.git.head(),
            dirty=self.git.is_dirty(),
            changed_paths=self.git.changed_paths(),
            remote=self.git.default_remote(),
            pr=pr,
            issue=link.issue if link else None,
            harness_version=manifest.runtime_version if manifest else RUNTIME_VERSION,
            outbox_pending=self.outbox.pending_count(),
            adopted=self.installation is not None,
            bundle_version=manifest.bundle_version if manifest else None,
            detached=branch is None,
            default_branch=self._default_branch(),
            github_available=self.github_available() if include_github else False,
        )

    def _default_branch(self) -> str | None:
        for candidate in ("main", "master"):
            if self.git.branch_exists(candidate):
                return candidate
        remote = self.git.default_remote()
        if remote:
            result = self.git.run(["symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD"])
            if result.ok and result.out:
                return result.out.rsplit("/", 1)[-1]
        branches = self.git.local_branches()
        return branches[0] if branches else None


def _record_from_dict(data: dict[str, Any]) -> Record | None:
    from .records import parse_record, render_marker, RECORD_TAG

    body = str(data.get("body") or "")
    marker_payload = {k: v for k, v in data.items() if k not in {"body", "comment_id", "url", "author"}}
    text = render_marker(RECORD_TAG, marker_payload) + "\n\n" + body
    return parse_record(
        text,
        comment_id=data.get("comment_id"),
        url=data.get("url"),
        author=data.get("author"),
    )


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
