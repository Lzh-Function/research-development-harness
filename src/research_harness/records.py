"""Durable record markers, parsing and serialization.

Work Issue comments are the canonical durable record store (SPEC 25).  Each
record carries an HTML-comment machine marker followed by a human-readable
Markdown body (SPEC 26)::

    <!-- rh:record {"schema":1,"kind":"checkpoint","id":"...", ...} -->

The parser is intentionally forgiving about *unknown* fields and unknown
future schema versions: readers support old schemas, and RDH never rewrites
historical GitHub records to migrate them (SPEC 61).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from . import RECORD_SCHEMA_VERSION
from .errors import RecordError
from .util import iso_timestamp, new_uuid

RECORD_TAG = "rh:record"
WORK_TAG = "rh:work"
RQ_TAG = "rh:rq"
PR_TAG = "rh:pr"

RecordKind = Literal["checkpoint", "decision", "result", "gate"]
RECORD_KINDS: tuple[str, ...] = ("checkpoint", "decision", "result", "gate")

WORK_KINDS: tuple[str, ...] = (
    "experiment",
    "analysis",
    "implementation",
    "bug",
    "refactor",
    "infrastructure",
    "migration",
)
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high")
DECISION_STATUSES: tuple[str, ...] = ("accepted", "rejected", "deferred")
GATE_NAMES: tuple[str, ...] = ("design", "deviation", "evidence", "knowledge")
GATE_OUTCOMES: tuple[str, ...] = ("passed", "repaired", "overridden", "blocked")

_MARKER_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _marker_re(tag: str) -> re.Pattern[str]:
    pattern = _MARKER_RE_CACHE.get(tag)
    if pattern is None:
        pattern = re.compile(r"<!--\s*" + re.escape(tag) + r"\s+(\{.*?\})\s*-->", re.DOTALL)
        _MARKER_RE_CACHE[tag] = pattern
    return pattern


def render_marker(tag: str, payload: dict[str, Any]) -> str:
    """Serialize a machine marker line.

    ``--`` cannot appear inside an HTML comment, so any occurrence in the
    payload is escaped; the parser reverses it.
    """
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = text.replace("--", "\\u002d\\u002d")
    return f"<!-- {tag} {text} -->"


def parse_marker(text: str, tag: str) -> dict[str, Any] | None:
    """Return the first ``tag`` marker payload in ``text``, or ``None``."""
    if not text:
        return None
    match = _marker_re(tag).search(text)
    if not match:
        return None
    raw = match.group(1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def strip_markers(text: str) -> str:
    """Remove every RDH marker, leaving the human-readable body."""
    out = text
    for tag in (RECORD_TAG, WORK_TAG, RQ_TAG, PR_TAG):
        out = _marker_re(tag).sub("", out)
    return out.strip("\n")


@dataclass
class Record:
    """A durable record stored as a Work Issue comment."""

    kind: str
    body: str = ""
    id: str = field(default_factory=new_uuid)
    issue: int | None = None
    head: str | None = None
    branch: str | None = None
    created_at: str = field(default_factory=iso_timestamp)
    schema: int = RECORD_SCHEMA_VERSION
    #: decision-only
    status: str | None = None
    #: gate-only
    gate: str | None = None
    outcome: str | None = None
    #: transport metadata, populated when read back from GitHub
    comment_id: str | None = None
    url: str | None = None
    author: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in RECORD_KINDS:
            raise RecordError(f"unknown record kind: {self.kind!r}", hint=f"expected one of {', '.join(RECORD_KINDS)}")
        if self.kind == "decision" and self.status is not None and self.status not in DECISION_STATUSES:
            raise RecordError(f"unknown decision status: {self.status!r}")
        if self.kind == "gate":
            if self.gate is not None and self.gate not in GATE_NAMES:
                raise RecordError(f"unknown gate: {self.gate!r}")
            if self.outcome is not None and self.outcome not in GATE_OUTCOMES:
                raise RecordError(f"unknown gate outcome: {self.outcome!r}")

    # ------------------------------------------------------------------ marker

    def marker_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "kind": self.kind,
            "id": self.id,
            "created_at": self.created_at,
        }
        if self.issue is not None:
            payload["issue"] = self.issue
        if self.head:
            payload["head"] = self.head
        if self.branch:
            payload["branch"] = self.branch
        if self.status:
            payload["status"] = self.status
        if self.gate:
            payload["gate"] = self.gate
        if self.outcome:
            payload["outcome"] = self.outcome
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def to_comment(self) -> str:
        """Full GitHub comment text: marker line + Markdown body."""
        marker = render_marker(RECORD_TAG, self.marker_payload())
        body = self.body.strip("\n")
        return f"{marker}\n\n{body}\n" if body else f"{marker}\n"

    def to_dict(self) -> dict[str, Any]:
        payload = self.marker_payload()
        payload["body"] = self.body
        if self.comment_id:
            payload["comment_id"] = self.comment_id
        if self.url:
            payload["url"] = self.url
        if self.author:
            payload["author"] = self.author
        return payload

    # ------------------------------------------------------------------ helpers

    def summary(self) -> str:
        label = self.kind
        if self.kind == "gate":
            label = f"gate:{self.gate or '?'}={self.outcome or '?'}"
        elif self.kind == "decision":
            label = f"decision:{self.status or 'proposed'}"
        head = f" @{self.head[:10]}" if self.head else ""
        return f"{label} {self.created_at}{head}"

    def section(self, name: str) -> str | None:
        return extract_section(self.body, name)


def parse_record(comment_body: str, *, comment_id: str | None = None, url: str | None = None, author: str | None = None) -> Record | None:
    """Parse a GitHub comment into a :class:`Record`, or ``None``.

    Unknown ``kind`` values and future schema versions yield ``None`` rather
    than raising, so a newer harness' records never break an older reader.
    """
    payload = parse_marker(comment_body, RECORD_TAG)
    if payload is None:
        return None
    kind = payload.get("kind")
    if kind not in RECORD_KINDS:
        return None
    known = {"schema", "kind", "id", "created_at", "issue", "head", "branch", "status", "gate", "outcome"}
    extra = {k: v for k, v in payload.items() if k not in known}
    issue = payload.get("issue")
    try:
        issue_number = int(issue) if issue is not None else None
    except (TypeError, ValueError):
        issue_number = None
    record = Record.__new__(Record)  # bypass validation for tolerant reads
    record.kind = kind
    record.body = strip_markers(comment_body)
    record.id = str(payload.get("id") or new_uuid())
    record.issue = issue_number
    record.head = payload.get("head")
    record.branch = payload.get("branch")
    record.created_at = str(payload.get("created_at") or iso_timestamp())
    try:
        record.schema = int(payload.get("schema", RECORD_SCHEMA_VERSION))
    except (TypeError, ValueError):
        record.schema = RECORD_SCHEMA_VERSION
    record.status = payload.get("status")
    record.gate = payload.get("gate")
    record.outcome = payload.get("outcome")
    record.comment_id = comment_id
    record.url = url
    record.author = author
    record.extra = extra
    return record


@dataclass
class WorkMarker:
    """Machine marker embedded at the top of a Work Issue body (SPEC 21)."""

    kind: str = "implementation"
    risk: str = "medium"
    evidence_required: bool = False
    rq: int | None = None
    schema: int = RECORD_SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.kind not in WORK_KINDS:
            raise RecordError(f"unknown work kind: {self.kind!r}", hint=f"expected one of {', '.join(WORK_KINDS)}")
        if self.risk not in RISK_LEVELS:
            raise RecordError(f"unknown risk level: {self.risk!r}", hint=f"expected one of {', '.join(RISK_LEVELS)}")

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": self.schema,
            "kind": self.kind,
            "risk": self.risk,
            "evidence_required": bool(self.evidence_required),
        }
        if self.rq is not None:
            payload["rq"] = self.rq
        payload.update(self.extra)
        return payload

    def render(self) -> str:
        return render_marker(WORK_TAG, self.payload())

    @classmethod
    def parse(cls, issue_body: str) -> "WorkMarker | None":
        payload = parse_marker(issue_body, WORK_TAG)
        if payload is None:
            return None
        known = {"schema", "kind", "risk", "evidence_required", "rq"}
        rq = payload.get("rq")
        try:
            rq_number = int(rq) if rq is not None else None
        except (TypeError, ValueError):
            rq_number = None
        return cls(
            kind=str(payload.get("kind", "implementation")),
            risk=str(payload.get("risk", "medium")),
            evidence_required=bool(payload.get("evidence_required", False)),
            rq=rq_number,
            schema=int(payload.get("schema", RECORD_SCHEMA_VERSION)) if str(payload.get("schema", "")).isdigit() else RECORD_SCHEMA_VERSION,
            extra={k: v for k, v in payload.items() if k not in known},
        )


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def extract_section(markdown: str, name: str) -> str | None:
    """Return the text under the first heading matching ``name`` (case-insensitive)."""
    if not markdown:
        return None
    target = name.strip().lower()
    lines = markdown.splitlines()
    start: int | None = None
    level = 0
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match and match.group(2).strip().lower() == target:
            start = index + 1
            level = len(match.group(1))
            break
    if start is None:
        return None
    collected: list[str] = []
    for line in lines[start:]:
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) <= level:
            break
        collected.append(line)
    return "\n".join(collected).strip() or None


def sections(markdown: str) -> dict[str, str]:
    """Map every heading in ``markdown`` to its body text."""
    out: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in (markdown or "").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if current is not None:
                out[current] = "\n".join(buffer).strip()
            current = match.group(2).strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        out[current] = "\n".join(buffer).strip()
    return out


def latest(records: list[Record], kind: str | None = None) -> Record | None:
    """Most recent record (by ``created_at``, ties broken by list order)."""
    pool = [r for r in records if kind is None or r.kind == kind]
    if not pool:
        return None
    return max(enumerate(pool), key=lambda pair: (pair[1].created_at, pair[0]))[1]


def sort_records(records: list[Record]) -> list[Record]:
    return sorted(records, key=lambda r: (r.created_at, r.id))
