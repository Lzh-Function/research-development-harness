"""Small deterministic helpers shared across the runtime.

Nothing here reaches the network, spawns a process, or touches ``$HOME``.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import unicodedata
import uuid
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp(moment: datetime | None = None) -> str:
    """RFC3339 timestamp in UTC with second precision."""
    moment = moment or utc_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_uuid() -> str:
    return str(uuid.uuid4())


def slugify(text: str, *, max_length: int = 48) -> str:
    """ASCII slug used for branch names.

    Non-ASCII input (research titles are frequently Japanese) degrades to an
    empty slug rather than producing a branch name git would reject; callers
    fall back to a neutral stem in that case.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_text).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug


def parse_version(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(value.strip())
    if not match:
        raise ValueError(f"not a semantic version: {value!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def compare_versions(left: str, right: str) -> int:
    """Return -1/0/1 comparing two ``MAJOR.MINOR.PATCH`` strings."""
    a, b = parse_version(left), parse_version(right)
    return (a > b) - (a < b)


def version_at_least(candidate: str, minimum: str) -> bool:
    return compare_versions(candidate, minimum) >= 0


def dumps(payload: Any) -> str:
    """Canonical JSON used both for ``--json`` output and record markers."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dumps_pretty(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def atomic_write(path: Path, content: str, *, mode: int | None = None) -> None:
    """Write ``content`` to ``path`` via a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@contextlib.contextmanager
def body_file(content: str, *, prefix: str = "rh-body-", dir: Path | None = None) -> Iterator[Path]:
    """Materialize long text for ``gh --body-file`` (SPEC 40).

    The file lives in the harness' own temporary directory, never in ``$HOME``,
    and is removed when the context exits.
    """
    directory = Path(dir) if dir is not None else None
    if directory is not None:
        directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".md", dir=str(directory) if directory else None)
    path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        yield path
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def indent_block(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def first_line(text: str, *, limit: int = 120) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


def shortest_unique(values: Sequence[str]) -> list[str]:
    """De-duplicate while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
