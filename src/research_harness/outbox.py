"""Durable-record outbox for offline / GitHub-failure operation.

When a record cannot reach GitHub it is written to
``.git/research-harness/outbox/<uuid>.json`` (SPEC 57) and replayed by
``rh sync``.  Replay is idempotent: a record whose UUID already appears in
the issue's comments is dropped rather than posted twice, so retrying yields
exactly-once semantics from the researcher's point of view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import GitHubUnavailableError, RecordError
from .github import GitHubClient
from .records import Record, parse_record
from .util import atomic_write, iso_timestamp


@dataclass
class OutboxEntry:
    record: Record
    path: Path
    queued_at: str = ""
    attempts: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "queued_at": self.queued_at,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "issue": self.record.issue,
            "id": self.record.id,
            "kind": self.record.kind,
            "comment": self.record.to_comment(),
        }


class Outbox:
    """A directory of pending record posts."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = Path(state_dir) / "outbox"

    # ------------------------------------------------------------------- write

    def enqueue(self, record: Record, *, error: str = "") -> Path:
        if record.issue is None:
            raise RecordError("cannot queue a record without an issue number")
        path = self.dir / f"{record.id}.json"
        entry = OutboxEntry(record=record, path=path, queued_at=iso_timestamp(), last_error=error)
        atomic_write(path, json.dumps(entry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return path

    def discard(self, entry: OutboxEntry) -> None:
        try:
            entry.path.unlink()
        except FileNotFoundError:
            pass

    def mark_failure(self, entry: OutboxEntry, error: str) -> None:
        entry.attempts += 1
        entry.last_error = error
        atomic_write(entry.path, json.dumps(entry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    # -------------------------------------------------------------------- read

    def entries(self) -> list[OutboxEntry]:
        if not self.dir.exists():
            return []
        out: list[OutboxEntry] = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            record = parse_record(str(data.get("comment") or ""))
            if record is None:
                continue
            if record.issue is None and data.get("issue") is not None:
                try:
                    record.issue = int(data["issue"])
                except (TypeError, ValueError):
                    continue
            out.append(
                OutboxEntry(
                    record=record,
                    path=path,
                    queued_at=str(data.get("queued_at", "")),
                    attempts=int(data.get("attempts", 0) or 0),
                    last_error=str(data.get("last_error", "")),
                )
            )
        return out

    def pending_count(self) -> int:
        if not self.dir.exists():
            return 0
        return sum(1 for _ in self.dir.glob("*.json"))

    def contains(self, record_id: str) -> bool:
        return (self.dir / f"{record_id}.json").exists()

    # ------------------------------------------------------------------- flush

    def sync(self, client: GitHubClient, *, dry_run: bool = False) -> dict[str, Any]:
        """Replay queued records. Never posts a UUID that already exists."""
        entries = self.entries()
        report: dict[str, Any] = {"pending": len(entries), "posted": [], "duplicate": [], "failed": []}
        if not entries:
            return report
        known: dict[int, set[str]] = {}
        for entry in entries:
            issue = entry.record.issue
            if issue is None:
                report["failed"].append({"id": entry.record.id, "error": "no issue number"})
                continue
            try:
                if issue not in known:
                    known[issue] = client.record_ids(issue)
            except GitHubUnavailableError as exc:
                report["failed"].append({"id": entry.record.id, "error": exc.message})
                if not dry_run:
                    self.mark_failure(entry, exc.message)
                continue
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                report["failed"].append({"id": entry.record.id, "error": str(exc)})
                if not dry_run:
                    self.mark_failure(entry, str(exc))
                continue

            if entry.record.id in known[issue]:
                report["duplicate"].append({"id": entry.record.id, "issue": issue})
                if not dry_run:
                    self.discard(entry)
                continue
            if dry_run:
                report["posted"].append({"id": entry.record.id, "issue": issue, "url": "", "dry_run": True})
                continue
            try:
                url = client.issue_comment(issue, entry.record.to_comment())
            except Exception as exc:  # noqa: BLE001 - queued records stay queued
                message = getattr(exc, "message", str(exc))
                report["failed"].append({"id": entry.record.id, "error": message})
                self.mark_failure(entry, message)
                continue
            known[issue].add(entry.record.id)
            report["posted"].append({"id": entry.record.id, "issue": issue, "url": url})
            self.discard(entry)
        return report
