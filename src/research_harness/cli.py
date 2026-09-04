"""``rh`` command line interface.

The CLI is deterministic by construction: it gathers Git/GitHub state, moves
structured text, derives state from explicit records and checks preconditions.
It never decides whether something matters scientifically — that judgement
belongs to the agent and, at the gates, to the researcher (SPEC 10).

Read commands support ``--json``; mutating commands support ``--dry-run``
(SPEC 34).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import RUNTIME_VERSION
from .adopt import Distribution, adopt
from .config import HARNESS_DIRNAME
from .context import Session
from .doctor import ERROR, is_distribution_repo, run_doctor
from .errors import (
    GitHubError,
    GitHubUnavailableError,
    HarnessError,
    NotARepositoryError,
    PreconditionError,
    UsageError,
)
from .git import GitRepo
from .github import GitHubIssue
from .managed import has_block
from .records import (
    DECISION_STATUSES,
    GATE_NAMES,
    GATE_OUTCOMES,
    RISK_LEVELS,
    WORK_KINDS,
    Record,
    WorkMarker,
    extract_section,
)
from .state import (
    PHASES,
    WorkLink,
    branch_name,
    derive_state,
    gate_satisfied,
    latest_checkpoint,
    pending_gates,
    ready_blockers,
)
from .upgrade import upgrade
from .util import dumps_pretty, iso_timestamp

PROG = "rh"


# --------------------------------------------------------------------- output


def emit_json(payload: Any) -> None:
    sys.stdout.write(dumps_pretty(payload) + "\n")


def emit(text: str) -> None:
    sys.stdout.write(text.rstrip("\n") + "\n")


def read_body(args: argparse.Namespace, *, required: bool = True, what: str = "body") -> str:
    """Long text always arrives as a file or an explicit string, never a shell."""
    body_file = getattr(args, "body_file", None)
    body = getattr(args, "body", None)
    if body_file:
        path = Path(body_file)
        if not path.exists():
            raise UsageError(f"--body-file not found: {path}")
        return path.read_text(encoding="utf-8")
    if body:
        return body
    if required:
        raise UsageError(f"a {what} is required", hint="Pass --body-file <path> (preferred) or --body <text>.")
    return ""


# -------------------------------------------------------------------- session


def make_session(args: argparse.Namespace) -> Session:
    return Session(
        root=getattr(args, "repo", None),
        repo_override=getattr(args, "github_repo", None),
        offline=bool(getattr(args, "offline", False)),
    )


def require_link(session: Session, issue_override: int | None = None) -> WorkLink:
    if issue_override is not None:
        branch = session.git.branch() or ""
        link = session.links.get(branch) if branch else None
        if link is None or link.issue != issue_override:
            link = WorkLink(branch=branch, issue=issue_override, pr=link.pr if link else None)
        return link
    link = session.current_link()
    if link is None:
        raise PreconditionError(
            "the current branch is not linked to a Work Issue",
            hint="Run `rh work start <issue>` or `rh work link <issue>`, or pass --issue.",
        )
    return link


# -------------------------------------------------------------------- commands


def cmd_version(args: argparse.Namespace) -> int:
    payload = {"runtime_version": RUNTIME_VERSION, "python": sys.version.split()[0]}
    try:
        session = make_session(args)
    except HarnessError:
        session = None
    if session and session.installation:
        payload["bundle_version"] = session.installation.manifest.bundle_version
        payload["installed_runtime_version"] = session.installation.manifest.runtime_version
    if args.json:
        emit_json(payload)
    else:
        emit(f"{PROG} {RUNTIME_VERSION}")
        if "bundle_version" in payload:
            emit(f"bundle {payload['bundle_version']} (installed runtime {payload['installed_runtime_version']})")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        session: Session | None = make_session(args)
        root = session.git.root
    except NotARepositoryError:
        session, root = None, Path(getattr(args, "repo", None) or Path.cwd())
    doctor = run_doctor(session, root)
    if args.json:
        emit_json({"findings": [f.to_dict() for f in doctor.findings], "worst": doctor.worst()})
    else:
        for finding in doctor.findings:
            emit(finding.render())
        emit("")
        emit(f"worst severity: {doctor.worst()}")
    return 1 if doctor.worst() == ERROR else 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Read-only repository inventory (SPEC 49). No classification here."""
    session = make_session(args)
    git = session.git
    root = git.root
    payload: dict[str, Any] = {
        "repo_root": str(root),
        "repo": session.repo_slug,
        "branch": git.branch(),
        "head": git.head(),
        "detached": git.is_detached(),
        "dirty": git.is_dirty(),
        "changed_paths": git.changed_paths(),
        "branches": git.local_branches(),
        "remote_branches": git.remote_branches(),
        "remotes": git.remotes(),
        "worktrees": [
            {"path": w.path, "head": w.head, "branch": w.branch, "detached": w.detached} for w in git.worktrees()
        ],
        "recent_commits": git.recent_commits(20),
        "adopted": session.installation is not None,
        "agent_files": {},
        "agent_dirs": {},
        "test_infrastructure": [],
        "candidate_experiment_dirs": [],
        "candidate_result_dirs": [],
        "open_issues": [],
        "open_prs": [],
        "github_available": False,
    }
    for name in ("AGENTS.md", "CLAUDE.md", "README.md", "CONTRIBUTING.md"):
        path = root / name
        info: dict[str, Any] = {"exists": path.exists()}
        if path.exists() and name in {"AGENTS.md", "CLAUDE.md"}:
            try:
                info["managed_block"] = has_block(path.read_text(encoding="utf-8"))
            except HarnessError as exc:
                info["managed_block"] = None
                info["error"] = exc.message
        payload["agent_files"][name] = info
    for name in (".claude", ".agents", ".codex", ".github", HARNESS_DIRNAME):
        directory = root / name
        payload["agent_dirs"][name] = {
            "exists": directory.is_dir(),
            "entries": sorted(p.name for p in directory.iterdir())[:50] if directory.is_dir() else [],
        }
    for marker in ("tests", "test", "pytest.ini", "tox.ini", "noxfile.py", "pyproject.toml", "Makefile", "conftest.py"):
        if (root / marker).exists():
            payload["test_infrastructure"].append(marker)
    for name in ("experiments", "exp", "runs", "scripts", "notebooks", "configs", "sweeps"):
        if (root / name).is_dir():
            payload["candidate_experiment_dirs"].append(name)
    for name in ("results", "outputs", "artifacts", "logs", "figures", "checkpoints", "data"):
        if (root / name).is_dir():
            payload["candidate_result_dirs"].append(name)
    if not session.offline and session.github_available():
        payload["github_available"] = True
        try:
            payload["open_issues"] = [
                {"number": i.number, "title": i.title, "labels": i.labels} for i in session.github.issue_list(limit=50)
            ]
        except HarnessError as exc:
            payload["open_issues_error"] = exc.message
        try:
            data = session.github.json(
                ["pr", "list", "--state", "open", "--limit", "50", "--json", "number,title,headRefName,isDraft"]
            )
            payload["open_prs"] = [
                {
                    "number": item.get("number"),
                    "title": item.get("title"),
                    "head": item.get("headRefName"),
                    "draft": item.get("isDraft"),
                }
                for item in (data or [])
                if isinstance(item, dict)
            ]
        except HarnessError as exc:
            payload["open_prs_error"] = exc.message

    if args.json:
        emit_json(payload)
        return 0
    emit(f"repository   {payload['repo_root']}")
    emit(f"github       {payload['repo'] or '(none detected)'}")
    emit(f"branch       {payload['branch'] or '(detached)'}  head {payload['head'] or '-'}")
    emit(f"dirty        {payload['dirty']} ({len(payload['changed_paths'])} path(s))")
    emit(f"branches     {', '.join(payload['branches']) or '(none)'}")
    emit(f"worktrees    {len(payload['worktrees'])}")
    emit(f"adopted      {payload['adopted']}")
    for name, info in payload["agent_files"].items():
        if info["exists"]:
            extra = "" if "managed_block" not in info else f" (managed block: {info['managed_block']})"
            emit(f"file         {name}{extra}")
    for name, info in payload["agent_dirs"].items():
        if info["exists"]:
            emit(f"dir          {name}/ ({len(info['entries'])} entries)")
    if payload["test_infrastructure"]:
        emit(f"tests        {', '.join(payload['test_infrastructure'])}")
    if payload["candidate_experiment_dirs"]:
        emit(f"experiments? {', '.join(payload['candidate_experiment_dirs'])}")
    if payload["candidate_result_dirs"]:
        emit(f"results?     {', '.join(payload['candidate_result_dirs'])}")
    if payload["open_issues"]:
        emit(f"open issues  {len(payload['open_issues'])}")
    if payload["open_prs"]:
        emit(f"open PRs     {len(payload['open_prs'])}")
    emit("")
    emit("This inventory is deliberately unclassified; interpreting it is the agent's job.")
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    distribution = Distribution.locate()
    report = adopt(args.target, distribution=distribution, dry_run=args.dry_run, force=args.force)
    if args.json:
        emit_json(report.to_dict())
    else:
        emit(report.render())
    return 1 if report.conflicts and not args.force else 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    distribution = Distribution.locate()
    report = upgrade(args.target, distribution=distribution, dry_run=args.dry_run, force=args.force)
    if args.json:
        emit_json(report.to_dict())
    else:
        emit(report.render())
    return 1 if report.conflicts and not args.force else 0


def cmd_context(args: argparse.Namespace) -> int:
    session = make_session(args)
    payload = session.context()
    if args.json:
        emit_json(payload.to_dict())
        return 0
    data = payload.to_dict()
    for key in (
        "repo_root", "repo", "branch", "head", "dirty", "remote", "issue", "pr",
        "harness_version", "outbox_pending", "adopted", "github_available",
    ):
        emit(f"{key:<16} {data[key]}")
    if data["changed_paths"]:
        emit(f"{'changed_paths':<16} {len(data['changed_paths'])}")
    return 0


def _gather_work(session: Session, *, refresh: bool = True) -> dict[str, Any]:
    """Deterministic assembly shared by status/ready/resume."""
    link = session.current_link()
    context = session.context()
    result: dict[str, Any] = {
        "context": context.to_dict(),
        "issue": None,
        "pr": None,
        "records": [],
        "state": None,
        "pending_gates": [],
        "blockers": [],
        "risk": None,
        "kind": None,
        "evidence_required": None,
        "latest_checkpoint": None,
        "changes_since_checkpoint": [],
        "commits_since_checkpoint": [],
        "next_action": None,
        "records_source": "none",
    }
    if link is None:
        derived = derive_state(config=session.config, issue=None)
        result["state"] = derived.to_dict()
        return result

    issue_obj = session.issue(link.issue)
    records, from_github = session.records(link.issue, refresh=refresh)
    marker = session.work_marker(issue_obj, link)
    pr_number = link.pr or (session.resolve_pr(link) if refresh else None)
    pr_obj = session.pull_request(pr_number) if refresh else None
    if issue_obj is not None:
        session.cache_records(link.issue, records, issue_obj=issue_obj)

    derived = derive_state(
        config=session.config,
        issue=link.issue,
        issue_state=issue_obj.state if issue_obj else None,
        marker=marker,
        records=records,
        branch_linked=True,
        pr=pr_number,
        pr_state=pr_obj.state if pr_obj else None,
    )
    checkpoint = latest_checkpoint(records)
    result.update(
        {
            "issue": {
                "number": link.issue,
                "title": issue_obj.title if issue_obj else link.title,
                "state": issue_obj.state if issue_obj else None,
                "url": issue_obj.url if issue_obj else None,
            },
            "pr": {
                "number": pr_number,
                "state": pr_obj.state if pr_obj else None,
                "draft": pr_obj.draft if pr_obj else None,
                "url": pr_obj.url if pr_obj else None,
            }
            if pr_number
            else None,
            "records": [r.to_dict() for r in records],
            "records_source": "github" if from_github else ("cache" if records else "none"),
            "state": derived.to_dict(),
            "pending_gates": derived.pending_gates,
            "blockers": derived.blockers,
            "risk": marker.risk if marker else None,
            "kind": marker.kind if marker else None,
            "evidence_required": bool(marker.evidence_required) if marker else None,
            "link": link.to_dict(),
        }
    )
    if checkpoint is not None:
        result["latest_checkpoint"] = checkpoint.to_dict()
        result["next_action"] = extract_section(checkpoint.body, "Next Action")
        if checkpoint.head and session.git.object_exists(checkpoint.head):
            result["changes_since_checkpoint"] = session.git.diff_names_since(checkpoint.head)
            result["commits_since_checkpoint"] = session.git.commits_since(checkpoint.head)
        else:
            result["changes_since_checkpoint"] = session.git.changed_paths()
    else:
        result["changes_since_checkpoint"] = session.git.changed_paths()
    return result


def cmd_status(args: argparse.Namespace) -> int:
    session = make_session(args)
    work = _gather_work(session, refresh=not session.offline)
    if args.json:
        emit_json(work)
        return 0
    context = work["context"]
    state = work["state"]
    emit(f"Current Work        {('#' + str(work['issue']['number']) + ' ' + (work['issue']['title'] or '')).strip() if work['issue'] else '(none)'}")
    emit(f"Derived State       {state['state']}  — {state['reason']}")
    emit(f"Risk                {work['risk'] or '-'} ({work['kind'] or '-'}{', evidence required' if work['evidence_required'] else ''})")
    emit(f"Issue               {('#' + str(work['issue']['number'])) if work['issue'] else '-'}")
    emit(f"PR                  {('#' + str(work['pr']['number'])) if work['pr'] else '-'}")
    emit(f"Branch              {context['branch'] or '(detached)'}")
    emit(f"HEAD                {context['head'] or '-'}")
    checkpoint = work["latest_checkpoint"]
    emit(f"Latest Checkpoint   {checkpoint['created_at'] if checkpoint else '(none)'}")
    emit(f"Changes Since       {len(work['changes_since_checkpoint'])} path(s), {len(work['commits_since_checkpoint'])} commit(s)")
    emit(f"Pending Gates       {', '.join(work['pending_gates']) or '(none)'}")
    emit(f"Blockers            {'; '.join(work['blockers']) or '(none)'}")
    emit(f"Next Recorded Action{'  ' + (work['next_action'] or '(none)')}")
    if context["outbox_pending"]:
        emit(f"Outbox              {context['outbox_pending']} pending — run `rh sync`")
    if work["records_source"] == "cache":
        emit("Records             read from local cache (GitHub unavailable)")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Deterministic half of the resume workflow (SPEC 41).

    Gathers everything a fresh session needs; the briefing prose is written by
    the agent, not here.
    """
    session = make_session(args)
    work = _gather_work(session, refresh=not session.offline)
    link = session.current_link()
    payload: dict[str, Any] = dict(work)
    payload["read_order"] = [
        "context",
        "work_issue",
        "accepted_decisions",
        "results",
        "latest_checkpoint",
        "pull_request",
        "changes_since_checkpoint",
    ]
    if link is not None:
        issue_obj = session.issue(link.issue)
        payload["work_issue_body"] = issue_obj.body if issue_obj else None
        raw_records = work["records"]
        payload["accepted_decisions"] = [
            r for r in raw_records if r.get("kind") == "decision" and r.get("status") == "accepted"
        ]
        payload["results"] = [r for r in raw_records if r.get("kind") == "result"]
        payload["gates"] = [r for r in raw_records if r.get("kind") == "gate"]
    workflow = None
    if session.installation:
        candidate = session.installation.workflows_dir / "resume.md"
        if candidate.exists():
            workflow = str(candidate)
    payload["workflow"] = workflow
    if args.json:
        emit_json(payload)
        return 0
    emit(f"state               {payload['state']['state']}")
    emit(f"issue               {('#' + str(payload['issue']['number'])) if payload['issue'] else '(none)'}")
    emit(f"pr                  {('#' + str(payload['pr']['number'])) if payload['pr'] else '(none)'}")
    emit(f"records             {len(payload['records'])}")
    emit(f"accepted decisions  {len(payload.get('accepted_decisions', []))}")
    emit(f"results             {len(payload.get('results', []))}")
    emit(f"latest checkpoint   {payload['latest_checkpoint']['created_at'] if payload['latest_checkpoint'] else '(none)'}")
    emit(f"changes since       {len(payload['changes_since_checkpoint'])} path(s)")
    emit(f"next action         {payload['next_action'] or '(none)'}")
    if workflow:
        emit("")
        emit(f"Follow {workflow} to produce the briefing.")
    return 0


def cmd_issue_create(args: argparse.Namespace) -> int:
    session = make_session(args)
    marker = WorkMarker(
        kind=args.kind,
        risk=args.risk,
        evidence_required=bool(args.evidence_required),
        rq=args.rq,
    )
    marker.validate()
    body = read_body(args, what="Work Issue body")
    full_body = f"{marker.render()}\n\n{body.strip()}\n"
    labels = list(args.label or [])
    if session.config.work_label and session.config.work_label not in labels:
        labels.append(session.config.work_label)
    if args.dry_run:
        payload = {"dry_run": True, "title": args.title, "labels": labels, "body": full_body}
        emit_json(payload) if args.json else emit(f"[dry-run] would create Work Issue: {args.title}\n\n{full_body}")
        return 0
    issue = session.github.issue_create(args.title, full_body, labels=labels)
    if args.json:
        emit_json({"issue": issue.number, "url": issue.url, "title": issue.title, "labels": labels})
    else:
        emit(f"created Work Issue #{issue.number}: {issue.url}")
        emit("Next: take the Design Gate if required, then `rh work start %d`." % issue.number)
    return 0


def cmd_work_start(args: argparse.Namespace) -> int:
    session = make_session(args)
    issue_number = args.issue
    issue_obj: GitHubIssue | None = session.issue(issue_number)
    if issue_obj is None:
        raise PreconditionError(
            f"could not read Work Issue #{issue_number}",
            hint="Check the issue number and that gh is authenticated.",
        )
    marker = WorkMarker.parse(issue_obj.body)
    if marker is None:
        raise PreconditionError(
            f"issue #{issue_number} has no rh:work marker and is not a Work Issue",
            hint="Create work with `rh issue create`, or add the marker to the issue body.",
        )
    records, _ = session.records(issue_number, refresh=not session.offline)
    required = pending_gates(records, session.config, marker)
    if "design" in required and not args.skip_gate_check:
        raise PreconditionError(
            f"issue #{issue_number} requires a design gate before work starts",
            hint="Run the Design Gate, then `rh record gate --gate design --outcome passed|overridden`.",
        )

    target_branch = args.existing_branch or branch_name(issue_number, issue_obj.title, prefix=session.config.branch_prefix)
    current_branch = session.git.branch()
    plan: dict[str, Any] = {
        "issue": issue_number,
        "branch": target_branch,
        "existing_branch": bool(args.existing_branch),
        "create_branch": not session.git.branch_exists(target_branch),
        "push": not args.no_push,
        "create_pr": not args.no_pr,
        "dirty": session.git.is_dirty(),
    }
    if args.dry_run:
        emit_json({"dry_run": True, **plan}) if args.json else emit(
            "[dry-run] " + "; ".join(f"{k}={v}" for k, v in plan.items())
        )
        return 0

    if session.git.branch_exists(target_branch):
        if current_branch != target_branch:
            session.git.switch_branch(target_branch)  # never forced, never stashes
    else:
        if args.existing_branch:
            raise PreconditionError(f"no such branch: {target_branch}")
        session.git.create_branch(target_branch, start_point=args.base or None)

    link = WorkLink(
        branch=target_branch,
        issue=issue_number,
        title=issue_obj.title,
        kind=marker.kind,
        risk=marker.risk,
        evidence_required=bool(marker.evidence_required),
    )
    session.save_link(link)

    pushed = False
    push_error = None
    if not args.no_push:
        result = session.git.push_branch(target_branch)
        pushed = result.ok
        if not result.ok:
            push_error = result.combined()

    pr_number = None
    pr_url = None
    pr_error = None
    if not args.no_pr:
        try:
            existing = session.github.pr_for_branch(target_branch)
            if existing is not None:
                pr_number, pr_url = existing.number, existing.url
            elif pushed:
                body = _initial_pr_body(session, issue_number, marker)
                base = args.base or session.github.default_branch() or session.context().default_branch
                pr = session.github.pr_create(
                    title=issue_obj.title or f"Work #{issue_number}",
                    body=body,
                    head=target_branch,
                    base=base,
                    draft=True,
                )
                pr_number, pr_url = pr.number, pr.url
            else:
                pr_error = "branch was not pushed, so no Draft PR was created"
        except HarnessError as exc:
            pr_error = exc.message
    if pr_number:
        link.pr = pr_number
        session.save_link(link)

    payload = {
        "issue": issue_number,
        "branch": target_branch,
        "pushed": pushed,
        "push_error": push_error,
        "pr": pr_number,
        "pr_url": pr_url,
        "pr_error": pr_error,
    }
    if args.json:
        emit_json(payload)
    else:
        emit(f"branch    {target_branch}")
        emit(f"issue     #{issue_number}")
        emit(f"pushed    {pushed}" + (f" ({push_error})" if push_error else ""))
        emit(f"draft PR  {('#' + str(pr_number) + ' ' + (pr_url or '')) if pr_number else '(none)'}" + (f" — {pr_error}" if pr_error else ""))
        if plan["dirty"]:
            emit("note      uncommitted changes were preserved untouched")
    return 0


def _initial_pr_body(session: Session, issue: int, marker: WorkMarker) -> str:
    template = None
    if session.installation:
        candidate = session.installation.templates_dir / "pull-request.md"
        if candidate.exists():
            template = candidate.read_text(encoding="utf-8")
    linkage = "Closes" if marker.kind in {"implementation", "bug", "refactor", "infrastructure", "migration"} else "Refs"
    header = f"{linkage} #{issue}\n\n"
    if template:
        return header + template
    return header + "## Purpose\n\n<!-- filled in by `rh-finish` -->\n"


def cmd_work_link(args: argparse.Namespace) -> int:
    session = make_session(args)
    branch = session.git.branch()
    if not branch:
        raise PreconditionError("HEAD is detached; switch to a branch before linking work")
    issue_obj = session.issue(args.issue)
    marker = WorkMarker.parse(issue_obj.body) if issue_obj else None
    link = WorkLink(
        branch=branch,
        issue=args.issue,
        pr=args.pr,
        title=issue_obj.title if issue_obj else "",
        kind=marker.kind if marker else "implementation",
        risk=marker.risk if marker else session.config.default_risk,
        evidence_required=bool(marker.evidence_required) if marker else False,
    )
    if args.dry_run:
        emit_json({"dry_run": True, **link.to_dict()}) if args.json else emit(f"[dry-run] would link {branch} -> #{args.issue}")
        return 0
    session.save_link(link)
    if args.json:
        emit_json(link.to_dict())
    else:
        emit(f"linked branch {branch} to issue #{args.issue}" + (f" and PR #{args.pr}" if args.pr else ""))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    session = make_session(args)
    link = require_link(session, args.issue)
    body = read_body(args, what=f"{args.record_kind} record body")
    record = Record(
        kind=args.record_kind,
        body=body,
        issue=link.issue,
        head=session.git.head(),
        branch=session.git.branch(),
        status=getattr(args, "status", None),
        gate=getattr(args, "gate", None),
        outcome=getattr(args, "outcome", None),
    )
    if args.record_kind == "checkpoint":
        record.extra["phase"] = args.phase
    if args.record_kind == "decision" and not record.status:
        raise UsageError("--status is required for decision records", hint=f"one of {', '.join(DECISION_STATUSES)}")
    if args.record_kind == "gate":
        if not record.gate or not record.outcome:
            raise UsageError("--gate and --outcome are required for gate records")

    if args.dry_run:
        payload = {"dry_run": True, **record.to_dict(), "comment": record.to_comment()}
        emit_json(payload) if args.json else emit(f"[dry-run] would post to #{link.issue}:\n\n{record.to_comment()}")
        return 0

    queued = False
    url = ""
    queue_reason = ""
    try:
        url, created = session.github.post_record(record)
        if not created:
            url = ""
    except (GitHubUnavailableError, GitHubError) as exc:
        # A record is never lost because GitHub misbehaved: queue it and say
        # why, so a misconfiguration is visible rather than silently retried.
        queue_reason = getattr(exc, "message", str(exc))
        session.outbox.enqueue(record, error=queue_reason)
        queued = True

    payload = {
        "id": record.id,
        "kind": record.kind,
        "issue": link.issue,
        "url": url,
        "queued": queued,
        "queue_reason": queue_reason,
        "head": record.head,
    }
    if args.json:
        emit_json(payload)
    else:
        if queued:
            emit(f"could not reach GitHub — {record.kind} record {record.id} queued in the outbox")
            emit(f"  reason: {queue_reason}")
            emit("Run `rh sync` when GitHub is reachable; replay is idempotent.")
        else:
            emit(f"recorded {record.kind} on issue #{link.issue}" + (f": {url}" if url else " (already present; not duplicated)"))
    return 0


def cmd_ready(args: argparse.Namespace) -> int:
    session = make_session(args)
    link = require_link(session, args.issue)
    issue_obj = session.issue(link.issue)
    records, _ = session.records(link.issue, refresh=not session.offline)
    marker = session.work_marker(issue_obj, link)
    pr_number = link.pr or session.resolve_pr(link)
    problems = ready_blockers(
        config=session.config,
        marker=marker,
        records=records,
        pr=pr_number,
        dirty=session.git.is_dirty(),
    )
    payload = {
        "issue": link.issue,
        "pr": pr_number,
        "ready": not problems,
        "state": "READY_TO_MERGE" if not problems else "NOT_READY",
        "blockers": problems,
    }
    if args.json:
        emit_json(payload)
    else:
        if problems:
            emit("NOT READY_TO_MERGE:")
            for problem in problems:
                emit(f"  - {problem}")
        else:
            emit("READY_TO_MERGE")
            emit("The researcher merges. RDH never runs `gh pr merge`.")
    return 0 if not problems else 3


def cmd_sync(args: argparse.Namespace) -> int:
    session = make_session(args)
    report = session.outbox.sync(session.github, dry_run=args.dry_run)
    if args.json:
        emit_json(report)
    else:
        emit(f"pending    {report['pending']}")
        emit(f"posted     {len(report['posted'])}")
        emit(f"duplicate  {len(report['duplicate'])} (already on GitHub; not reposted)")
        emit(f"failed     {len(report['failed'])}")
        for failure in report["failed"]:
            emit(f"  - {failure['id']}: {failure['error']}")
    return 0 if not report["failed"] else 8


def cmd_pr_update(args: argparse.Namespace) -> int:
    session = make_session(args)
    link = require_link(session, args.issue)
    pr_number = args.pr or link.pr or session.resolve_pr(link)
    if pr_number is None:
        raise PreconditionError("no Draft PR is linked to this branch", hint="Run `rh work start <issue>` first.")
    body = read_body(args, what="PR body")
    if args.dry_run:
        emit_json({"dry_run": True, "pr": pr_number, "body": body}) if args.json else emit(
            f"[dry-run] would update PR #{pr_number}"
        )
        return 0
    session.github.pr_edit_body(pr_number, body)
    if args.json:
        emit_json({"pr": pr_number, "updated": True})
    else:
        emit(f"updated PR #{pr_number} body")
    return 0


# --------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Research Development Harness — repository-local research workflow runtime.",
    )
    parser.add_argument("--repo", help="repository root to operate on (default: discover from cwd)")
    parser.add_argument("--github-repo", help="override the GitHub repository (owner/name)")
    parser.add_argument("--offline", action="store_true", help="never contact GitHub; use local cache and outbox")
    parser.add_argument("--version", action="version", version=f"{PROG} {RUNTIME_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: Any, help_text: str, *, json_flag: bool = True, dry_run: bool = False) -> argparse.ArgumentParser:
        sub = subparsers.add_parser(name, help=help_text, description=help_text)
        if json_flag:
            sub.add_argument("--json", action="store_true", help="machine-readable output")
        if dry_run:
            sub.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
        sub.set_defaults(func=handler)
        return sub

    add("version", cmd_version, "print harness versions")
    add("doctor", cmd_doctor, "diagnose the environment and installation (read-only)")
    add("audit", cmd_audit, "read-only inventory of the repository (SPEC 49)")
    add("context", cmd_context, "current repository/work context")
    add("status", cmd_status, "derived state of the current work unit")
    add("resume", cmd_resume, "durable state needed to resume work in a fresh session")

    adopt_parser = add("adopt", cmd_adopt, "vendor RDH into a target research repository", dry_run=True)
    adopt_parser.add_argument("target", help="path to the target research repository")
    adopt_parser.add_argument("--force", action="store_true", help="overwrite locally modified harness files")

    upgrade_parser = add("upgrade", cmd_upgrade, "re-vendor a newer RDH into an adopted repository", dry_run=True)
    upgrade_parser.add_argument("target", help="path to the adopted research repository")
    upgrade_parser.add_argument("--force", action="store_true", help="overwrite locally modified harness files / allow downgrade")

    issue_parser = subparsers.add_parser("issue", help="Work Issue operations")
    issue_sub = issue_parser.add_subparsers(dest="issue_command", required=True)
    issue_create = issue_sub.add_parser("create", help="create a Work Issue with an rh:work marker")
    issue_create.add_argument("--title", required=True)
    issue_create.add_argument("--body-file", dest="body_file")
    issue_create.add_argument("--body")
    issue_create.add_argument("--kind", choices=WORK_KINDS, default="implementation")
    issue_create.add_argument("--risk", choices=RISK_LEVELS, default="medium")
    issue_create.add_argument("--evidence-required", action="store_true")
    issue_create.add_argument("--rq", type=int, help="linked Research Question issue number")
    issue_create.add_argument("--label", action="append", help="repeatable")
    issue_create.add_argument("--json", action="store_true")
    issue_create.add_argument("--dry-run", action="store_true")
    issue_create.set_defaults(func=cmd_issue_create)

    work_parser = subparsers.add_parser("work", help="work unit lifecycle")
    work_sub = work_parser.add_subparsers(dest="work_command", required=True)
    work_start = work_sub.add_parser("start", help="create/adopt the branch and open a Draft PR")
    work_start.add_argument("issue", type=int)
    work_start.add_argument("--existing-branch", help="adopt this branch instead of creating rh/<n>-<slug>")
    work_start.add_argument("--base", help="base branch for the Draft PR")
    work_start.add_argument("--no-pr", action="store_true", help="do not create a Draft PR")
    work_start.add_argument("--no-push", action="store_true", help="do not push the branch")
    work_start.add_argument("--skip-gate-check", action="store_true", help="bypass the design-gate precondition")
    work_start.add_argument("--json", action="store_true")
    work_start.add_argument("--dry-run", action="store_true")
    work_start.set_defaults(func=cmd_work_start)

    work_link = work_sub.add_parser("link", help="link the current branch to an existing Work Issue")
    work_link.add_argument("issue", type=int)
    work_link.add_argument("--pr", type=int)
    work_link.add_argument("--json", action="store_true")
    work_link.add_argument("--dry-run", action="store_true")
    work_link.set_defaults(func=cmd_work_link)

    record_parser = subparsers.add_parser("record", help="write a durable record to the Work Issue")
    record_sub = record_parser.add_subparsers(dest="record_kind", required=True)
    for kind in ("checkpoint", "decision", "result", "gate"):
        sub = record_sub.add_parser(kind, help=f"record a {kind}")
        sub.add_argument("--body-file", dest="body_file")
        sub.add_argument("--body")
        sub.add_argument("--issue", type=int, help="override the linked Work Issue")
        sub.add_argument("--json", action="store_true")
        sub.add_argument("--dry-run", action="store_true")
        if kind == "checkpoint":
            sub.add_argument("--phase", choices=PHASES, default="implementing")
        if kind == "decision":
            sub.add_argument("--status", choices=DECISION_STATUSES, required=True)
        if kind == "gate":
            sub.add_argument("--gate", choices=GATE_NAMES, required=True)
            sub.add_argument("--outcome", choices=GATE_OUTCOMES, required=True)
        sub.set_defaults(func=cmd_record, record_kind=kind)

    ready_parser = add("ready", cmd_ready, "check the deterministic READY_TO_MERGE preconditions")
    ready_parser.add_argument("--issue", type=int)

    add("sync", cmd_sync, "replay queued records to GitHub (idempotent)", dry_run=True)

    pr_parser = subparsers.add_parser("pr", help="pull request operations")
    pr_sub = pr_parser.add_subparsers(dest="pr_command", required=True)
    pr_update = pr_sub.add_parser("update", help="replace the Draft PR body")
    pr_update.add_argument("--body-file", dest="body_file")
    pr_update.add_argument("--body")
    pr_update.add_argument("--pr", type=int)
    pr_update.add_argument("--issue", type=int)
    pr_update.add_argument("--json", action="store_true")
    pr_update.add_argument("--dry-run", action="store_true")
    pr_update.set_defaults(func=cmd_pr_update)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not hasattr(args, "json"):
        args.json = False
    try:
        return int(args.func(args) or 0)
    except HarnessError as exc:
        sys.stderr.write(f"{PROG}: {exc.render()}\n")
        return exc.exit_code
    except BrokenPipeError:  # pragma: no cover
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write(f"{PROG}: interrupted\n")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
