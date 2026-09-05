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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import RUNTIME_VERSION
from .config import HARNESS_DIRNAME, MANIFEST_NAME, Config, Installation
from .errors import GitHubError, HarnessError
from .git import GitRepo, parse_github_remote
from .github import GitHubClient, GitHubIssue, GitHubPR
from .outbox import Outbox
from .proc import CommandRunner, SubprocessRunner
from .records import RQMarker, Record, WorkMarker, extract_section, headline, strip_markers
from .state import LinkStore, WorkLink, derive_state, issue_from_branch
from .util import atomic_write, iso_timestamp


@dataclass
class TimelineEntry:
    """One dated event in the cross-issue research history."""

    at: str
    issue: int
    issue_title: str
    kind: str
    label: str = ""
    headline: str = ""
    url: str | None = None
    record_id: str | None = None
    outcome: str | None = None
    status: str | None = None
    gate: str | None = None
    head: str | None = None
    body: str = ""
    issue_state: str = ""

    @property
    def date(self) -> str:
        return self.at[:10]

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "issue": self.issue,
            "issue_title": self.issue_title,
            "issue_state": self.issue_state,
            "kind": self.kind,
            "label": self.label,
            "headline": self.headline,
            "outcome": self.outcome,
            "status": self.status,
            "gate": self.gate,
            "head": self.head,
            "record_id": self.record_id,
            "url": self.url,
        }


#: The linkage line RDH writes at the top of every PR body it opens.
_ISSUE_REF_RE = re.compile(r"\b(Closes|Fixes|Resolves|Refs)\s+#(\d+)", re.IGNORECASE)


def _work_headline(body: str, *, limit: int = 96) -> str:
    """Opening line for a Work Issue: its stated purpose, not its first heading."""
    for name in ("Purpose", "Research Question"):
        text = extract_section(body, name)
        if text:
            for line in text.splitlines():
                stripped = line.strip().lstrip("-*• ").strip()
                if stripped and not stripped.startswith(("<!--", "|", "#")):
                    return stripped if len(stripped) <= limit else stripped[: limit - 1] + "…"
    for line in strip_markers(body or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "<!--", "|")):
            return stripped if len(stripped) <= limit else stripped[: limit - 1] + "…"
    return "work unit opened"


def _record_label(record: Record) -> str:
    if record.kind == "gate":
        return f"{record.gate or '?'} → {record.outcome or '?'}"
    if record.kind == "decision":
        return record.status or "proposed"
    if record.kind == "checkpoint":
        phase = record.extra.get("phase")
        return str(phase) if isinstance(phase, str) else "implementing"
    return ""


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
        self.git = GitRepo.discover(root if root is not None else vendored_repo_root(), self.runner)
        self.offline = offline
        self._gh_runner = gh_runner or self.runner
        self._repo_override = repo_override
        self._github: GitHubClient | None = None
        self._resolved_slug: str | None = None
        self._records_cache: dict[int, list[Record]] = {}
        self._prs_by_issue: dict[int, dict[str, Any]] | None = None
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

    def remember_record(self, record: Record) -> None:
        """Add a just-written record to the local cache.

        Without this, going offline right after recording a gate makes
        ``rh status`` fall back to a cache that predates it and report a state
        *worse* than reality — a pending gate that has in fact passed.
        """
        if record.issue is None:
            return
        payload = self.cached_payload(record.issue) or {"issue": record.issue, "records": []}
        records = list(payload.get("records") or [])
        if not any(isinstance(item, dict) and item.get("id") == record.id for item in records):
            records.append(record.to_dict())
        payload["records"] = records
        payload["fetched_at"] = iso_timestamp()
        atomic_write(
            self.cache_path(record.issue),
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

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

    # ------------------------------------------------------- cross-issue view

    def work_issues(self, *, state: str = "all", limit: int = 100) -> list[tuple[GitHubIssue, WorkMarker]]:
        """Every Work Issue in the repository, newest first.

        A Work Issue is one carrying an ``rh:work`` marker; ordinary issues in
        the same repository are ignored rather than guessed at. Offline, this
        falls back to whatever the local cache and branch links know about.
        """
        found: dict[int, tuple[GitHubIssue, WorkMarker]] = {}
        if not self.offline:
            try:
                for issue in self.github.issue_list(state=state, limit=limit, with_body=True):
                    marker = WorkMarker.parse(issue.body)
                    if marker is not None:
                        found[issue.number] = (issue, marker)
            except HarnessError:
                pass
        if not found:
            for number in self.cached_issue_numbers():
                issue = self._cached_issue(number)
                if issue is None:
                    continue
                marker = WorkMarker.parse(issue.body) or WorkMarker()
                found[number] = (issue, marker)
            for link in self.links.all():
                if link.issue not in found:
                    found[link.issue] = (
                        GitHubIssue(number=link.issue, title=link.title),
                        WorkMarker(kind=link.kind, risk=link.risk, evidence_required=link.evidence_required),
                    )
        return sorted(found.values(), key=lambda pair: pair[0].number, reverse=True)

    def prs_by_issue(self, *, limit: int = 100) -> dict[int, dict[str, Any]]:
        """Map Work Issue number to its pull request.

        Derived from the ``Closes #n`` / ``Refs #n`` line RDH writes into every
        PR body it opens, so it travels with the repository instead of relying
        on the local link store (which a fresh clone does not have). One API
        call serves a whole cross-issue survey.
        """
        if self._prs_by_issue is not None:
            return self._prs_by_issue
        mapping: dict[int, dict[str, Any]] = {}
        for link in self.links.all():
            if link.pr:
                mapping[link.issue] = {"number": link.pr, "state": None, "head": link.branch}
        if not self.offline:
            try:
                data = self.github.json(
                    ["pr", "list", "--state", "all", "--limit", str(limit),
                     "--json", "number,state,body,headRefName,mergedAt"]
                )
            except HarnessError:
                data = None
            for item in data or []:
                if not isinstance(item, dict):
                    continue
                match = _ISSUE_REF_RE.search(str(item.get("body") or ""))
                if not match:
                    continue
                pr = GitHubPR.from_json(item)
                mapping[int(match.group(2))] = {"number": pr.number, "state": pr.state, "head": pr.head}
        self._prs_by_issue = mapping
        return mapping

    def research_questions(self, *, state: str = "all", limit: int = 100) -> list[GitHubIssue]:
        """Issues carrying an ``rh:rq`` marker, newest first."""
        found: list[GitHubIssue] = []
        if not self.offline:
            try:
                for issue in self.github.issue_list(state=state, limit=limit, with_body=True):
                    if RQMarker.parse(issue.body) is not None:
                        found.append(issue)
            except HarnessError:
                pass
        if not found:
            for number in self.cached_issue_numbers():
                issue = self._cached_issue(number)
                if issue is not None and RQMarker.parse(issue.body) is not None:
                    found.append(issue)
        return sorted(found, key=lambda issue: issue.number, reverse=True)

    def rq_summary(self, number: int, *, state: str = "all", limit: int = 100) -> dict[str, Any]:
        """Everything recorded under one Research Question.

        Deliberately an aggregation, not a synthesis: the ``Supports`` and
        ``Does NOT Support`` lines are reproduced as written. Deciding what the
        question's answer now is belongs to the researcher, with the agent's
        help — never to this function.
        """
        rq_issue = self.issue(number)
        units: list[dict[str, Any]] = []
        for issue_obj, marker in self.work_issues(state=state, limit=limit):
            if marker.rq != number:
                continue
            records, from_github = self.records(issue_obj.number, refresh=not self.offline)
            if from_github:
                self.cache_records(issue_obj.number, records, issue_obj=issue_obj)
            pr_info = self.prs_by_issue().get(issue_obj.number)
            derived = derive_state(
                config=self.config,
                issue=issue_obj.number,
                issue_state=issue_obj.state,
                marker=marker,
                records=records,
                branch_linked=pr_info is not None,
                pr=pr_info["number"] if pr_info else None,
                pr_state=pr_info.get("state") if pr_info else None,
            )
            results = [r for r in records if r.kind == "result"]
            units.append(
                {
                    "issue": issue_obj.number,
                    "title": issue_obj.title,
                    "issue_state": issue_obj.state,
                    "pr": pr_info["number"] if pr_info else None,
                    "state": derived.state,
                    "risk": marker.risk,
                    "kind": marker.kind,
                    "pending_gates": derived.pending_gates,
                    "results": [
                        {
                            "id": record.id,
                            "at": record.created_at,
                            "supports": extract_section(record.body, "Supports"),
                            "does_not_support": extract_section(record.body, "Does NOT Support"),
                            "observation": extract_section(record.body, "Observation"),
                        }
                        for record in results
                    ],
                }
            )
        units.sort(key=lambda unit: unit["issue"])
        by_state: dict[str, int] = {}
        for unit in units:
            by_state[unit["state"]] = by_state.get(unit["state"], 0) + 1
        return {
            "rq": number,
            "title": rq_issue.title if rq_issue else "",
            "url": rq_issue.url if rq_issue else None,
            "issue_state": rq_issue.state if rq_issue else None,
            "is_research_question": bool(rq_issue and RQMarker.parse(rq_issue.body) is not None),
            "work_units": units,
            "counts": by_state,
            "result_count": sum(len(unit["results"]) for unit in units),
        }

    def cached_issue_numbers(self) -> list[int]:
        directory = self.state_dir / "cache"
        if not directory.exists():
            return []
        numbers: list[int] = []
        for path in directory.glob("issue-*.json"):
            stem = path.stem.removeprefix("issue-")
            if stem.isdigit():
                numbers.append(int(stem))
        return sorted(numbers)

    def timeline(
        self,
        *,
        issues: list[int] | None = None,
        state: str = "all",
        limit_issues: int = 100,
        include_work: bool = True,
        rq: int | None = None,
    ) -> list["TimelineEntry"]:
        """Every durable record across Work Issues, newest first."""
        entries: list[TimelineEntry] = []
        pairs = self.work_issues(state=state, limit=limit_issues)
        if issues:
            wanted = set(issues)
            pairs = [pair for pair in pairs if pair[0].number in wanted]
            for number in wanted - {pair[0].number for pair in pairs}:
                issue_obj = self.issue(number)
                if issue_obj is not None:
                    pairs.append((issue_obj, WorkMarker.parse(issue_obj.body) or WorkMarker()))
        if rq is not None:
            pairs = [pair for pair in pairs if pair[1].rq == rq]
        for issue_obj, marker in pairs:
            records, from_github = self.records(issue_obj.number, refresh=not self.offline)
            if from_github:
                self.cache_records(issue_obj.number, records, issue_obj=issue_obj)
            if include_work and issue_obj.created_at:
                entries.append(
                    TimelineEntry(
                        at=issue_obj.created_at,
                        issue=issue_obj.number,
                        issue_title=issue_obj.title,
                        kind="work",
                        label=f"{marker.kind}/{marker.risk}",
                        headline=_work_headline(issue_obj.body),
                        url=issue_obj.url,
                        issue_state=issue_obj.state,
                    )
                )
            for record in records:
                entries.append(
                    TimelineEntry(
                        at=record.created_at,
                        issue=issue_obj.number,
                        issue_title=issue_obj.title,
                        kind=record.kind,
                        label=_record_label(record),
                        headline=headline(record),
                        url=record.url,
                        record_id=record.id,
                        outcome=record.outcome,
                        status=record.status,
                        gate=record.gate,
                        head=record.head,
                        body=record.body,
                        issue_state=issue_obj.state,
                    )
                )
        entries.sort(key=lambda entry: entry.at, reverse=True)
        return entries

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


def vendored_repo_root() -> Path | None:
    """The repository this runtime was vendored into, if any.

    A target's `.research-harness/bin/rh` belongs to that repository. Without
    this, invoking it from another directory would silently report on whatever
    repository happened to contain the working directory — the wrong branch,
    the wrong HEAD, the wrong work. An explicit ``--repo`` still wins.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == HARNESS_DIRNAME and (parent / MANIFEST_NAME).exists():
            return parent.parent
    return None


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
