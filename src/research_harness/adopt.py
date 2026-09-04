"""Adoption — vendoring RDH into a research repository (SPEC 3, 48, 54).

Adoption is **overlay + cutover**, never reconstruction. It writes only:

    .research-harness/**
    .claude/skills/rh-*/**
    .agents/skills/rh-*/**
    AGENTS.md   — between the managed markers only
    CLAUDE.md   — between the managed markers only

Every planned write is checked against that allow-list before it happens, so
"adoption never touches research source files" is enforced rather than
promised.  Nothing is written under ``$HOME`` at any point.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import BUNDLE_VERSION, MIN_RUNTIME_VERSION, RUNTIME_VERSION
from .config import (
    CONFIG_NAME,
    HARNESS_DIRNAME,
    Config,
    Installation,
    Manifest,
    write_config,
    write_manifest,
)
from .errors import AdoptionError
from .managed import upsert_block
from .util import atomic_write, iso_timestamp

INVENTORY_NAME = "inventory.json"
BASELINE_NAME = "baseline.md"

CLAUDE_SKILLS_DIR = Path(".claude") / "skills"
CODEX_SKILLS_DIR = Path(".agents") / "skills"

#: Path prefixes adoption/upgrade may write. Anything else is a bug.
ALLOWED_PREFIXES: tuple[str, ...] = (
    f"{HARNESS_DIRNAME}/",
    ".claude/skills/rh-",
    ".agents/skills/rh-",
)
ALLOWED_FILES: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md")

#: Never overwritten once the researcher has them.
PRESERVED_RELPATHS: tuple[str, ...] = (
    f"{HARNESS_DIRNAME}/{CONFIG_NAME}",
    f"{HARNESS_DIRNAME}/{BASELINE_NAME}",
)

_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
_SKIP_SUFFIXES = (".pyc", ".pyo")


def is_allowed_relpath(relpath: str) -> bool:
    normalized = relpath.replace("\\", "/")
    if normalized in ALLOWED_FILES:
        return True
    return any(normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES)


def assert_allowed(relpath: str) -> None:
    if not is_allowed_relpath(relpath):
        raise AdoptionError(
            f"refusing to write outside the RDH-owned area: {relpath}",
            hint="Adoption only writes .research-harness/, rh-* skills, and managed blocks.",
        )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class FileAction:
    relpath: str
    action: str  # create | update | unchanged | skip-preserved | conflict
    reason: str = ""

    def to_dict(self) -> dict[str, str]:
        data = {"path": self.relpath, "action": self.action}
        if self.reason:
            data["reason"] = self.reason
        return data


@dataclass
class AdoptionReport:
    target: str
    mode: str  # adopt | upgrade
    dry_run: bool
    actions: list[FileAction] = field(default_factory=list)
    from_versions: dict[str, str] | None = None
    to_versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add(self, relpath: str, action: str, reason: str = "") -> None:
        self.actions.append(FileAction(relpath, action, reason))

    @property
    def conflicts(self) -> list[FileAction]:
        return [a for a in self.actions if a.action == "conflict"]

    def changed(self) -> list[FileAction]:
        return [a for a in self.actions if a.action in {"create", "update"}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "from": self.from_versions,
            "to": self.to_versions,
            "actions": [a.to_dict() for a in self.actions],
            "conflicts": [a.to_dict() for a in self.conflicts],
            "warnings": self.warnings,
        }

    def render(self) -> str:
        lines = [f"{'Would adopt' if self.dry_run else 'Adopted'} RDH into {self.target}" if self.mode == "adopt"
                 else f"{'Would upgrade' if self.dry_run else 'Upgraded'} RDH in {self.target}"]
        if self.from_versions:
            lines.append(
                f"  runtime {self.from_versions.get('runtime_version')} -> {self.to_versions.get('runtime_version')}"
                f", bundle {self.from_versions.get('bundle_version')} -> {self.to_versions.get('bundle_version')}"
            )
        else:
            lines.append(
                f"  runtime {self.to_versions.get('runtime_version')}, bundle {self.to_versions.get('bundle_version')}"
            )
        created = [a for a in self.actions if a.action == "create"]
        updated = [a for a in self.actions if a.action == "update"]
        unchanged = [a for a in self.actions if a.action == "unchanged"]
        preserved = [a for a in self.actions if a.action == "skip-preserved"]
        lines.append(f"  {len(created)} created, {len(updated)} updated, {len(unchanged)} unchanged, {len(preserved)} preserved")
        for action in created + updated:
            lines.append(f"    {action.action:<8} {action.relpath}")
        for action in preserved:
            lines.append(f"    preserved {action.relpath}")
        for action in self.conflicts:
            lines.append(f"    CONFLICT {action.relpath}: {action.reason}")
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        return "\n".join(lines)


class Distribution:
    """The harness distribution repository this runtime was launched from."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.bundle = self.root / "bundle"
        self.src = self.root / "src"
        self.bin = self.root / "bin" / "rh"

    @classmethod
    def locate(cls) -> "Distribution":
        """Find the distribution root relative to this module."""
        here = Path(__file__).resolve()
        # <root>/src/research_harness/adopt.py  or  <target>/.research-harness/runtime/...
        candidate = here.parent.parent.parent
        return cls(candidate)

    def validate(self) -> None:
        missing = [
            str(path)
            for path in (self.bundle, self.src / "research_harness" / "cli.py", self.bin)
            if not path.exists()
        ]
        if missing:
            raise AdoptionError(
                "this runtime is not running from a harness distribution repository: missing "
                + ", ".join(missing),
                hint="Run `./bin/rh adopt <target>` from a clone of research-development-harness.",
            )


def iter_files(root: Path) -> list[Path]:
    """All regular files under ``root``, skipping caches and byte-code."""
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.is_file() and not path.name.endswith(_SKIP_SUFFIXES):
            out.append(path)
    return out


class Adopter:
    """Plans and applies an adoption or an upgrade."""

    def __init__(
        self,
        distribution: Distribution,
        target: Path,
        *,
        dry_run: bool = False,
        force: bool = False,
        mode: str = "adopt",
    ) -> None:
        self.dist = distribution
        self.target = Path(target).resolve()
        self.dry_run = dry_run
        self.force = force
        self.mode = mode
        self.harness_dir = self.target / HARNESS_DIRNAME
        self.report = AdoptionReport(target=str(self.target), mode=mode, dry_run=dry_run)
        self.inventory: dict[str, str] = {}
        self._previous_inventory: dict[str, str] = self._load_inventory()

    # ----------------------------------------------------------------- helpers

    def _load_inventory(self) -> dict[str, str]:
        path = self.harness_dir / INVENTORY_NAME
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        files = data.get("files")
        return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}

    def _write(self, relpath: str, content: str, *, executable: bool = False) -> None:
        assert_allowed(relpath)
        destination = self.target / relpath
        digest = sha256_text(content)
        self.inventory[relpath] = digest
        existing = destination.read_text(encoding="utf-8") if destination.exists() else None
        if existing is not None and sha256_text(existing) == digest:
            self.report.add(relpath, "unchanged")
            if not self.dry_run and executable:
                destination.chmod(0o755)
            return
        if existing is not None and not self.force:
            previous = self._previous_inventory.get(relpath)
            if previous is not None and sha256_text(existing) != previous:
                self.report.add(relpath, "conflict", "locally modified since the last install")
                return
        action = "update" if existing is not None else "create"
        if not self.dry_run:
            atomic_write(destination, content, mode=0o755 if executable else None)
        self.report.add(relpath, action)

    def _copy_tree(self, source: Path, relative_destination: str, *, executable: bool = False) -> None:
        if not source.exists():
            return
        for path in iter_files(source):
            relpath = f"{relative_destination}/{path.relative_to(source).as_posix()}"
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self._copy_binary(path, relpath)
                continue
            self._write(relpath, content, executable=executable)

    def _copy_binary(self, source: Path, relpath: str) -> None:
        assert_allowed(relpath)
        destination = self.target / relpath
        digest = sha256_file(source)
        self.inventory[relpath] = digest
        if destination.exists() and sha256_file(destination) == digest:
            self.report.add(relpath, "unchanged")
            return
        action = "update" if destination.exists() else "create"
        if not self.dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.report.add(relpath, action)

    def _write_preserved(self, relpath: str, content: str) -> None:
        """Write only if absent; never clobber researcher-editable files."""
        assert_allowed(relpath)
        destination = self.target / relpath
        if destination.exists():
            self.report.add(relpath, "skip-preserved")
            return
        if not self.dry_run:
            atomic_write(destination, content)
        self.report.add(relpath, "create")

    # -------------------------------------------------------------------- plan

    def _validate_target(self) -> None:
        if not self.target.exists():
            raise AdoptionError(f"target does not exist: {self.target}")
        if not self.target.is_dir():
            raise AdoptionError(f"target is not a directory: {self.target}")
        if not (self.target / ".git").exists():
            raise AdoptionError(
                f"target is not a Git repository: {self.target}",
                hint="RDH keeps local state in .git/research-harness; run `git init` in the target first.",
            )
        if self.target == self.dist.root:
            raise AdoptionError(
                "refusing to adopt the harness distribution repository into itself",
                hint="Self-adoption is a later dogfooding step, not part of initial installation.",
            )
        if self.mode == "upgrade" and not (self.harness_dir / "manifest.toml").exists():
            raise AdoptionError(
                f"no existing RDH installation in {self.target}",
                hint="Use `rh adopt` for the first installation.",
            )
        if self.mode == "adopt" and (self.harness_dir / "manifest.toml").exists() and not self.force:
            existing = Installation.locate(self.target)
            self.report.warnings.append(
                f"already adopted (runtime {existing.manifest.runtime_version}); re-running adopt as an in-place refresh"
            )

    def _plan_runtime(self) -> None:
        self._copy_tree(self.dist.bundle / "policy", f"{HARNESS_DIRNAME}/policy")
        self._copy_tree(self.dist.bundle / "workflows", f"{HARNESS_DIRNAME}/workflows")
        self._copy_tree(self.dist.bundle / "templates", f"{HARNESS_DIRNAME}/templates")
        self._copy_tree(self.dist.src / "research_harness", f"{HARNESS_DIRNAME}/runtime/research_harness")
        self._write(f"{HARNESS_DIRNAME}/bin/rh", self.dist.bin.read_text(encoding="utf-8"), executable=True)

    def _plan_skills(self) -> None:
        for source, destination in (
            (self.dist.bundle / "claude-skills", CLAUDE_SKILLS_DIR),
            (self.dist.bundle / "codex-skills", CODEX_SKILLS_DIR),
        ):
            if not source.exists():
                continue
            for skill_dir in sorted(p for p in source.iterdir() if p.is_dir()):
                for path in iter_files(skill_dir):
                    relpath = (destination / skill_dir.name / path.relative_to(skill_dir)).as_posix()
                    self._write(relpath, path.read_text(encoding="utf-8"))

    def _plan_metadata(self, previous: Manifest | None) -> None:
        manifest = Manifest(
            bundle_version=BUNDLE_VERSION,
            runtime_version=RUNTIME_VERSION,
            min_runtime_version=MIN_RUNTIME_VERSION,
            adopted_at=previous.adopted_at if previous and previous.adopted_at else iso_timestamp(),
            upgraded_at=iso_timestamp() if self.mode == "upgrade" else (previous.upgraded_at if previous else None),
        )
        # The manifest is regenerated every run; it is never a conflict source.
        assert_allowed(f"{HARNESS_DIRNAME}/manifest.toml")
        if not self.dry_run:
            write_manifest(self.harness_dir, manifest)
        self.report.add(f"{HARNESS_DIRNAME}/manifest.toml", "update" if previous else "create")
        self.report.to_versions = {
            "runtime_version": RUNTIME_VERSION,
            "bundle_version": BUNDLE_VERSION,
        }
        if previous:
            self.report.from_versions = {
                "runtime_version": previous.runtime_version,
                "bundle_version": previous.bundle_version,
            }

        config = Config(project_name=self.target.name)
        self._write_preserved(f"{HARNESS_DIRNAME}/{CONFIG_NAME}", config.render())
        self._write_preserved(f"{HARNESS_DIRNAME}/{BASELINE_NAME}", baseline_stub(self.target.name))

    def _plan_managed_blocks(self) -> None:
        instructions_path = self.dist.bundle / "managed-instructions.md"
        if not instructions_path.exists():
            return
        content = instructions_path.read_text(encoding="utf-8").strip()
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = self.target / name
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            updated = upsert_block(existing, content)
            if updated == existing:
                self.report.add(name, "unchanged")
                continue
            if not self.dry_run:
                atomic_write(path, updated)
            self.report.add(name, "update" if existing.strip() else "create", "managed block only")

    def _write_inventory(self) -> None:
        if self.dry_run:
            return
        payload = {
            "generated_at": iso_timestamp(),
            "runtime_version": RUNTIME_VERSION,
            "bundle_version": BUNDLE_VERSION,
            "files": dict(sorted(self.inventory.items())),
        }
        atomic_write(
            self.harness_dir / INVENTORY_NAME,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )

    # -------------------------------------------------------------------- drive

    def run(self) -> AdoptionReport:
        self.dist.validate()
        self._validate_target()
        previous: Manifest | None = None
        manifest_path = self.harness_dir / "manifest.toml"
        if manifest_path.exists():
            try:
                previous = Manifest.load(manifest_path)
            except Exception:  # noqa: BLE001 - a broken manifest is replaced, not fatal
                self.report.warnings.append("existing manifest.toml could not be parsed; it will be regenerated")
        self._plan_runtime()
        self._plan_skills()
        self._plan_metadata(previous)
        self._plan_managed_blocks()
        if self.report.conflicts and not self.force:
            self.report.warnings.append(
                f"{len(self.report.conflicts)} locally modified harness file(s) were left untouched; re-run with --force to overwrite"
            )
        self._write_inventory()
        return self.report


def baseline_stub(project_name: str) -> str:
    """Cutover snapshot skeleton (SPEC 52).

    The *content* is reconstructed semantically by the agent together with the
    researcher; the CLI only creates the shape and the cutover date.
    """
    return f"""# Research Harness Baseline — {project_name}

Cutover date: {iso_timestamp()}

This file is a **snapshot taken when RDH was adopted**, not a living document.
It is normally never updated. Its purpose is not to reconstruct the past
perfectly, but to stop the project getting lost from today onward.

Fill it in with the researcher during adoption (see
`.research-harness/workflows/_common.md`). Everything below is an estimate
until the researcher corrects it — never mark existing work abandoned on an
agent's inference alone.

## Current Research Objectives

## Active Work

## Deferred Work

## Abandoned Work

## Important Historical Decisions

## Important Existing Evidence

## Repository Architecture

## Known Cognitive Debt

## Immediate Next Work
"""


def adopt(
    target: Path | str,
    *,
    distribution: Distribution | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> AdoptionReport:
    dist = distribution or Distribution.locate()
    return Adopter(dist, Path(target), dry_run=dry_run, force=force, mode="adopt").run()
