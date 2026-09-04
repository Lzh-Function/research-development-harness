"""Upgrade — re-vendoring a newer harness into an already-adopted repository.

Upgrade is adoption with three extra promises (SPEC 60/61):

* ``config.toml`` and ``baseline.md`` are never overwritten;
* AGENTS.md / CLAUDE.md change only inside the managed block;
* historical GitHub records are never rewritten to migrate schemas — readers
  tolerate old schemas instead.

Locally modified harness files are reported as conflicts and left alone unless
``--force`` is given.
"""

from __future__ import annotations

from pathlib import Path

from . import RUNTIME_VERSION
from .adopt import Adopter, AdoptionReport, Distribution
from .config import Installation
from .errors import AdoptionError
from .util import compare_versions


def upgrade(
    target: Path | str,
    *,
    distribution: Distribution | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> AdoptionReport:
    dist = distribution or Distribution.locate()
    path = Path(target)
    installation = Installation.locate(path)  # raises NotAdoptedError when absent
    current = installation.manifest.runtime_version
    if compare_versions(RUNTIME_VERSION, current) < 0 and not force:
        raise AdoptionError(
            f"refusing to downgrade {path}: installed runtime {current} is newer than this distribution's {RUNTIME_VERSION}",
            hint="Pass --force if the downgrade is intentional.",
        )
    return Adopter(dist, path, dry_run=dry_run, force=force, mode="upgrade").run()
