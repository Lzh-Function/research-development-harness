"""Branch↔work linkage and derived research state.

There is no state database (SPEC 32): state is *computed* from Git, GitHub
objects and durable records.  The one thing kept locally is the branch → work
linkage, stored under ``.git/research-harness/links`` so that ``rh`` still
knows what it is looking at while GitHub is unreachable.  That file is a
cache with a durable fallback: the branch naming convention and the Draft PR
head reference can both re-derive it.

Nothing in this module interprets research content.  Every transition below
is a function of explicit, agent-recorded facts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .records import Record, WorkMarker, extract_section, latest
from .util import atomic_write, iso_timestamp, slugify

# Derived states (SPEC 32), ordered from least to most advanced.
STATES: tuple[str, ...] = (
    "UNTRACKED",
    "SCOPED",
    "DESIGN_GATE",
    "READY",
    "IN_PROGRESS",
    "DEVIATION_GATE",
    "BLOCKED",
    "VALIDATING",
    "EVIDENCE_GATE",
    "KNOWLEDGE_GATE",
    "READY_TO_MERGE",
    "DONE",
    "DEFERRED",
    "ABANDONED",
)

#: Declared by the agent on a checkpoint; keeps state derivation deterministic
#: without asking the CLI to judge what the work is doing.
PHASES: tuple[str, ...] = ("implementing", "validating", "blocked", "review")

PASSING_GATE_OUTCOMES = frozenset({"passed", "repaired", "overridden"})


@dataclass
class WorkLink:
    """Local association between a branch and its Work Issue / Draft PR."""

    branch: str
    issue: int
    pr: int | None = None
    title: str = ""
    kind: str = "implementation"
    risk: str = "medium"
    evidence_required: bool = False
    created_at: str = field(default_factory=iso_timestamp)
    updated_at: str = field(default_factory=iso_timestamp)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkLink":
        return cls(
            branch=str(data.get("branch", "")),
            issue=int(data["issue"]),
            pr=int(data["pr"]) if data.get("pr") not in (None, "") else None,
            title=str(data.get("title", "")),
            kind=str(data.get("kind", "implementation")),
            risk=str(data.get("risk", "medium")),
            evidence_required=bool(data.get("evidence_required", False)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


class LinkStore:
    """Branch links under ``.git/research-harness/links`` (never committed)."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = Path(state_dir) / "links"

    @staticmethod
    def _key(branch: str) -> str:
        stem = slugify(branch, max_length=80) or "branch"
        # Slugs are lossy; a stable digest keeps distinct branches distinct
        # across processes (``hash()`` is randomized per interpreter).
        digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:12]
        return f"{stem}-{digest}.json"

    def path_for(self, branch: str) -> Path:
        return self.dir / self._key(branch)

    def get(self, branch: str) -> WorkLink | None:
        path = self.path_for(branch)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        try:
            return WorkLink.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, link: WorkLink) -> None:
        link.updated_at = iso_timestamp()
        atomic_write(self.path_for(link.branch), json.dumps(link.to_dict(), indent=2, sort_keys=True) + "\n")

    def all(self) -> list[WorkLink]:
        if not self.dir.exists():
            return []
        links: list[WorkLink] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                links.append(WorkLink.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError, KeyError, TypeError, ValueError):
                continue
        return links


def issue_from_branch(branch: str | None, prefix: str = "rh/") -> int | None:
    """Recover the Work Issue number from a conventional branch name."""
    if not branch or not branch.startswith(prefix):
        return None
    rest = branch[len(prefix) :]
    number = rest.split("-", 1)[0]
    return int(number) if number.isdigit() else None


def branch_name(issue: int, title: str, *, prefix: str = "rh/") -> str:
    slug = slugify(title)
    return f"{prefix}{issue}-{slug}" if slug else f"{prefix}{issue}"


# --------------------------------------------------------------------- gates


def gate_outcome(records: list[Record], gate: str) -> str | None:
    """Latest recorded outcome for ``gate`` (``None`` when never run)."""
    gates = [r for r in records if r.kind == "gate" and r.gate == gate]
    newest = latest(gates)
    return newest.outcome if newest else None


def gate_satisfied(records: list[Record], gate: str) -> bool:
    return gate_outcome(records, gate) in PASSING_GATE_OUTCOMES


def pending_gates(records: list[Record], config: Config, marker: WorkMarker | None) -> list[str]:
    """Required gates that have no passing record yet."""
    risk = marker.risk if marker else config.default_risk
    evidence_required = bool(marker.evidence_required) if marker else False
    required = config.required_gates(risk, evidence_required=evidence_required)
    pending = [gate for gate in required if not gate_satisfied(records, gate)]
    if gate_outcome(records, "deviation") == "blocked":
        pending.insert(0, "deviation")
    return pending


def latest_checkpoint(records: list[Record]) -> Record | None:
    return latest(records, "checkpoint")


def checkpoint_phase(record: Record | None) -> str:
    if record is None:
        return "implementing"
    phase = record.extra.get("phase")
    if isinstance(phase, str) and phase in PHASES:
        return phase
    return "implementing"


def blocked_reason(record: Record | None) -> str | None:
    if record is None:
        return None
    text = extract_section(record.body, "Blocked By")
    if not text:
        return None
    normalized = text.strip().lower().strip(".")
    if normalized in {"", "none", "n/a", "nothing", "-"}:
        return None
    return text.strip()


# ----------------------------------------------------------- state derivation


@dataclass
class DerivedState:
    state: str
    reason: str
    pending_gates: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "pending_gates": list(self.pending_gates),
            "blockers": list(self.blockers),
        }


def derive_state(
    *,
    config: Config,
    issue: int | None,
    issue_state: str | None = None,
    marker: WorkMarker | None = None,
    records: list[Record] | None = None,
    branch_linked: bool = False,
    pr: int | None = None,
    pr_state: str | None = None,
) -> DerivedState:
    """Compute the derived research state (SPEC 32).

    ``issue_state``/``pr_state`` are GitHub's own strings (``OPEN``/``CLOSED``/
    ``MERGED``); they may be ``None`` when offline, in which case derivation
    falls back to durable records alone.
    """
    records = records or []
    if issue is None:
        return DerivedState("UNTRACKED", "no Work Issue is linked to this branch")

    lifecycle = str((marker.extra.get("status") if marker else "") or "").lower()
    if lifecycle in {"deferred", "abandoned"}:
        return DerivedState(lifecycle.upper(), f"Work Issue marked {lifecycle}")

    if (pr_state or "").upper() == "MERGED" or (issue_state or "").upper() == "CLOSED":
        return DerivedState("DONE", "Work Issue closed or PR merged")

    pending = pending_gates(records, config, marker)
    checkpoint = latest_checkpoint(records)
    phase = checkpoint_phase(checkpoint)
    blockers: list[str] = []
    reason = blocked_reason(checkpoint)
    if reason:
        blockers.append(reason)

    if "deviation" in pending:
        return DerivedState(
            "DEVIATION_GATE",
            "a deviation gate is open and needs a researcher decision",
            pending,
            blockers,
        )

    if "design" in pending:
        return DerivedState("DESIGN_GATE", "the design gate has no passing Gate Record yet", pending, blockers)

    if not branch_linked and pr is None:
        if gate_satisfied(records, "design"):
            return DerivedState("READY", "design gate passed; work has not started", pending, blockers)
        return DerivedState("SCOPED", "Work Issue exists; work has not started", pending, blockers)

    if phase == "blocked" or blockers:
        return DerivedState("BLOCKED", blockers[0] if blockers else "latest checkpoint reports the work blocked", pending, blockers)

    has_result = any(r.kind == "result" for r in records)
    evidence_pending = "evidence" in pending

    if evidence_pending and has_result:
        return DerivedState("EVIDENCE_GATE", "Result Records exist but the evidence gate has not passed", pending, blockers)
    if evidence_pending or phase == "validating":
        return DerivedState("VALIDATING", "evidence is still being gathered", pending, blockers)

    if phase == "review":
        if "knowledge" in pending:
            return DerivedState("KNOWLEDGE_GATE", "implementation and evidence are complete; knowledge gate pending", pending, blockers)
        return DerivedState("READY_TO_MERGE", "all required gates passed; the researcher merges, not RDH", pending, blockers)

    if not pending:
        return DerivedState("READY_TO_MERGE", "all required gates passed; the researcher merges, not RDH", pending, blockers)

    return DerivedState("IN_PROGRESS", "implementation is under way", pending, blockers)


def ready_blockers(
    *,
    config: Config,
    marker: WorkMarker | None,
    records: list[Record],
    pr: int | None,
    dirty: bool,
) -> list[str]:
    """Deterministic preconditions for ``READY_TO_MERGE`` (``rh ready``)."""
    problems: list[str] = []
    if pr is None:
        problems.append("no Draft PR is linked to this branch")
    for gate in pending_gates(records, config, marker):
        problems.append(f"{gate} gate has no passing Gate Record")
    if marker and marker.evidence_required and not any(r.kind == "result" for r in records):
        problems.append("work declares evidence_required but has no Result Record")
    checkpoint = latest_checkpoint(records)
    if checkpoint is None:
        problems.append("no Checkpoint Record exists")
    else:
        reason = blocked_reason(checkpoint)
        if reason:
            problems.append(f"latest checkpoint reports a blocker: {reason}")
    if dirty:
        problems.append("worktree has uncommitted changes")
    return problems
