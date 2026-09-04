"""Managed marker blocks inside AGENTS.md / CLAUDE.md.

RDH owns exactly the region between its markers and nothing else (SPEC 46).
Content outside the block is preserved byte-for-byte, including trailing
whitespace conventions, so adopting or upgrading an existing repository never
rewrites a researcher's instructions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import AdoptionError
from .util import atomic_write

BEGIN_MARKER = "<!-- BEGIN RESEARCH-HARNESS -->"
END_MARKER = "<!-- END RESEARCH-HARNESS -->"


@dataclass(frozen=True)
class BlockLocation:
    begin: int
    end: int  # index just past END_MARKER


def find_block(text: str) -> BlockLocation | None:
    """Locate the managed block, validating that markers are well formed."""
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count == 0 and end_count == 0:
        return None
    if begin_count != 1 or end_count != 1:
        raise AdoptionError(
            "malformed RDH managed block: expected exactly one BEGIN and one END marker",
            hint="Fix the markers by hand; RDH will not guess which region it owns.",
        )
    begin = text.index(BEGIN_MARKER)
    end = text.index(END_MARKER)
    if end < begin:
        raise AdoptionError("malformed RDH managed block: END marker precedes BEGIN marker")
    return BlockLocation(begin, end + len(END_MARKER))


def has_block(text: str) -> bool:
    return find_block(text) is not None


def extract_block(text: str) -> str | None:
    """Return the managed content (markers excluded), or ``None``."""
    location = find_block(text)
    if location is None:
        return None
    inner = text[location.begin + len(BEGIN_MARKER) : location.end - len(END_MARKER)]
    return inner.strip("\n")


def render_block(content: str) -> str:
    return f"{BEGIN_MARKER}\n{content.strip()}\n{END_MARKER}"


def upsert_block(text: str, content: str) -> str:
    """Insert or replace the managed block, preserving all other content."""
    block = render_block(content)
    location = find_block(text)
    if location is None:
        if not text.strip():
            return block + "\n"
        prefix = text if text.endswith("\n") else text + "\n"
        return f"{prefix}\n{block}\n"
    return text[: location.begin] + block + text[location.end :]


def remove_block(text: str) -> str:
    """Remove the managed block and the blank line that introduced it."""
    location = find_block(text)
    if location is None:
        return text
    before = text[: location.begin]
    after = text[location.end :]
    if before.endswith("\n\n"):
        before = before[:-1]
    return before + after.lstrip("\n")


def apply_to_file(path: Path, content: str, *, dry_run: bool = False) -> tuple[str, str | None]:
    """Upsert the managed block in ``path``.

    Returns ``(action, new_text)`` where ``action`` is one of ``created``,
    ``updated`` or ``unchanged``; ``new_text`` is ``None`` when unchanged.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = upsert_block(existing, content)
    if updated == existing:
        return "unchanged", None
    if not dry_run:
        atomic_write(path, updated)
    return ("created" if not existing.strip() else "updated"), updated
