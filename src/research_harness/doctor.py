"""``rh doctor`` — deterministic environment and installation diagnosis.

Reports ERROR / WARNING / INFO findings (SPEC 62).  Doctor is read-only: it
never repairs, installs, or touches ``$HOME``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import MIN_RUNTIME_VERSION, RUNTIME_VERSION
from .config import HARNESS_DIRNAME, Installation
from .context import Session
from .errors import HarnessError
from .managed import has_block
from .util import version_at_least

ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"

_SEVERITY_ORDER = {INFO: 0, WARNING: 1, ERROR: 2}

CLAUDE_SKILLS = (
    "rh-scope",
    "rh-start",
    "rh-checkpoint",
    "rh-resume",
    "rh-status",
    "rh-decision",
    "rh-result",
    "rh-finish",
)


@dataclass
class Finding:
    severity: str
    check: str
    message: str
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {"severity": self.severity, "check": self.check, "message": self.message}
        if self.hint:
            data["hint"] = self.hint
        return data

    def render(self) -> str:
        line = f"{self.severity:<7} {self.check}: {self.message}"
        if self.hint:
            line += f"\n        hint: {self.hint}"
        return line


class Doctor:
    def __init__(self, session: Session | None, *, root: Path, distribution: bool = False) -> None:
        self.session = session
        self.root = root
        self.distribution = distribution
        self.findings: list[Finding] = []

    def add(self, severity: str, check: str, message: str, hint: str | None = None) -> None:
        self.findings.append(Finding(severity, check, message, hint))

    # ------------------------------------------------------------------ checks

    def check_python(self) -> None:
        version = ".".join(str(p) for p in sys.version_info[:3])
        if sys.version_info < (3, 11):
            self.add(ERROR, "python", f"Python 3.11+ required, found {version}")
        else:
            self.add(INFO, "python", f"Python {version}")

    def check_git(self) -> None:
        if self.session is None:
            self.add(ERROR, "git", "not inside a Git repository")
            return
        result = self.session.runner.run(["git", "--version"])
        if not result.ok:
            self.add(ERROR, "git", "git executable not found on PATH")
            return
        self.add(INFO, "git", result.out or "git available")
        self.add(INFO, "repository", f"root {self.session.git.root}")
        if self.session.git.is_detached():
            self.add(WARNING, "branch", "HEAD is detached", "Switch to a branch before recording work.")
        else:
            self.add(INFO, "branch", str(self.session.git.branch()))
        if self.session.git.is_dirty():
            self.add(
                INFO,
                "worktree",
                f"{len(self.session.git.changed_paths())} uncommitted change(s) — preserved, never touched by RDH",
            )

    def check_remote(self) -> None:
        if self.session is None:
            return
        slug = self.session.repo_slug
        if slug:
            self.add(INFO, "github-remote", slug)
        else:
            self.add(
                WARNING,
                "github-remote",
                "no GitHub remote detected",
                "Add one (git remote add origin ...) or set github.repo in .research-harness/config.toml.",
            )

    def check_gh(self) -> None:
        if self.session is None:
            return
        if not self.session.github.available():
            self.add(
                ERROR if not self.distribution else WARNING,
                "gh",
                "GitHub CLI (gh) not available",
                "Install https://cli.github.com/ — RDH never installs it for you.",
            )
            return
        self.add(INFO, "gh", "GitHub CLI available")
        authenticated, detail = self.session.github.authenticated()
        if authenticated:
            self.add(INFO, "gh-auth", "authenticated")
        else:
            self.add(WARNING, "gh-auth", "gh is not authenticated", "Run: gh auth login")

    def check_installation(self) -> None:
        installation = self.session.installation if self.session else None
        if installation is None:
            severity = INFO if self.distribution else ERROR
            message = (
                "harness distribution repository (no local installation expected)"
                if self.distribution
                else f"no {HARNESS_DIRNAME}/manifest.toml found"
            )
            self.add(severity, "installation", message, None if self.distribution else "Run `rh adopt <path>` from the harness repository.")
            return
        manifest = installation.manifest
        self.add(
            INFO,
            "installation",
            f"runtime {manifest.runtime_version}, bundle {manifest.bundle_version}, adopted {manifest.adopted_at or 'unknown'}",
        )
        if not version_at_least(RUNTIME_VERSION, manifest.min_runtime_version):
            self.add(
                ERROR,
                "compatibility",
                f"installed runtime {RUNTIME_VERSION} is older than the required minimum {manifest.min_runtime_version}",
                "Re-run `rh upgrade <path>` from a newer harness distribution repository.",
            )
        elif not version_at_least(manifest.runtime_version, MIN_RUNTIME_VERSION):
            self.add(WARNING, "compatibility", f"vendored runtime {manifest.runtime_version} predates {MIN_RUNTIME_VERSION}")
        if not installation.bin_path.exists():
            self.add(ERROR, "runtime", f"missing {installation.bin_path}")
        if not (installation.runtime_dir / "research_harness" / "cli.py").exists():
            self.add(ERROR, "runtime", f"missing vendored runtime under {installation.runtime_dir}")

    def check_adapters(self) -> None:
        if self.distribution:
            return
        for label, base in (("claude", self.root / ".claude" / "skills"), ("codex", self.root / ".agents" / "skills")):
            missing = [name for name in CLAUDE_SKILLS if not (base / name / "SKILL.md").exists()]
            if not base.exists():
                self.add(ERROR, f"{label}-skills", f"no skills directory at {base}")
            elif missing:
                self.add(WARNING, f"{label}-skills", f"missing skills: {', '.join(missing)}")
            else:
                self.add(INFO, f"{label}-skills", f"{len(CLAUDE_SKILLS)} skills installed")

    def check_managed_blocks(self) -> None:
        if self.distribution:
            return
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = self.root / name
            if not path.exists():
                self.add(WARNING, "managed-block", f"{name} not present")
                continue
            try:
                if has_block(path.read_text(encoding="utf-8")):
                    self.add(INFO, "managed-block", f"{name} contains the RDH managed block")
                else:
                    self.add(WARNING, "managed-block", f"{name} has no RDH managed block", "Run `rh upgrade` from the harness repository.")
            except HarnessError as exc:
                self.add(ERROR, "managed-block", f"{name}: {exc.message}")

    def check_records(self) -> None:
        if self.session is None:
            return
        link = self.session.current_link()
        if link is None:
            self.add(INFO, "tracked-work", "current branch is not linked to a Work Issue")
            return
        self.add(INFO, "tracked-work", f"issue #{link.issue}" + (f", PR #{link.pr}" if link.pr else ""))
        records, from_github = self.session.records(link.issue, refresh=not self.session.offline)
        source = "GitHub" if from_github else "local cache/outbox"
        self.add(INFO, "records", f"{len(records)} durable record(s) parsed from {source}")

    def check_outbox(self) -> None:
        if self.session is None:
            return
        pending = self.session.outbox.pending_count()
        if pending:
            self.add(WARNING, "outbox", f"{pending} record(s) pending", "Run `rh sync` when GitHub is reachable.")
        else:
            self.add(INFO, "outbox", "empty")

    def check_home_hygiene(self) -> None:
        """RDH must own nothing under $HOME (SPEC 1.1 / 55)."""
        home = Path.home()
        offenders = [
            home / ".claude" / "skills" / "rh-scope",
            home / ".agents" / "skills" / "rh-scope",
            home / ".research-harness",
            home / "bin" / "rh",
            home / ".local" / "bin" / "rh",
        ]
        found = [str(path) for path in offenders if path.exists()]
        if found:
            self.add(
                WARNING,
                "home-hygiene",
                "RDH-looking files exist under $HOME: " + ", ".join(found),
                "RDH is repository-local; remove these leftovers, nothing in RDH creates them.",
            )
        else:
            self.add(INFO, "home-hygiene", "no RDH files under $HOME")

    # ------------------------------------------------------------------- drive

    def run(self) -> list[Finding]:
        self.check_python()
        self.check_git()
        self.check_remote()
        self.check_gh()
        self.check_installation()
        self.check_adapters()
        self.check_managed_blocks()
        self.check_records()
        self.check_outbox()
        self.check_home_hygiene()
        return self.findings

    def worst(self) -> str:
        return max((f.severity for f in self.findings), key=lambda s: _SEVERITY_ORDER[s], default=INFO)


def is_distribution_repo(root: Path) -> bool:
    """True for the harness' own repository, which is never self-adopted."""
    return (root / "src" / "research_harness" / "cli.py").exists() and (root / "bundle").is_dir()


def run_doctor(session: Session | None, root: Path) -> Doctor:
    doctor = Doctor(session, root=root, distribution=is_distribution_repo(root))
    doctor.run()
    return doctor
