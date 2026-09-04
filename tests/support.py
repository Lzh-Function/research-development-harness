"""Shared test support: isolated environments, temp repos and HOME snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
FAKE_GH = REPO_ROOT / "tests" / "fixtures" / "fake_gh.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def snapshot_tree(root: Path) -> dict[str, str]:
    """Content digest of every file under ``root`` (symlinks recorded by target)."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            out[rel] = "symlink:" + os.readlink(path)
        elif path.is_dir():
            out[rel] = "dir"
        elif path.is_file():
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
            except OSError:
                out[rel] = "unreadable"
                continue
            out[rel] = digest.hexdigest()
    return out


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
    return {"added": added, "removed": removed, "changed": changed}


@dataclass
class Sandbox:
    """A temp directory tree with an isolated HOME and a fake ``gh``."""

    base: Path
    home: Path
    bin_dir: Path
    config_dir: Path
    gh_state: Path
    gh_log: Path
    env: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, prefix: str = "rdh-test-") -> "Sandbox":
        base = Path(tempfile.mkdtemp(prefix=prefix))
        home = base / "home"
        bin_dir = base / "bin"
        config_dir = base / "xdg"
        for directory in (home, bin_dir, config_dir):
            directory.mkdir(parents=True, exist_ok=True)
        gh_state = base / "gh-state.json"
        gh_log = base / "gh-calls.log"
        sandbox = cls(base=base, home=home, bin_dir=bin_dir, config_dir=config_dir, gh_state=gh_state, gh_log=gh_log)
        sandbox.install_fake_gh()
        sandbox.env = sandbox.build_env()
        return sandbox

    # ---------------------------------------------------------------- fake gh

    def install_fake_gh(self) -> None:
        target = self.bin_dir / "gh"
        target.write_text(
            "#!/bin/sh\nexec %s %s \"$@\"\n" % (json.dumps(sys.executable).strip('"'), FAKE_GH),
            encoding="utf-8",
        )
        target.chmod(0o755)

    def set_gh_repo(self, slug: str = "octo/research", default_branch: str = "main") -> None:
        self.gh_state.write_text(
            json.dumps(
                {"repo": slug, "default_branch": default_branch, "issues": {}, "prs": {}, "next_issue": 1, "next_pr": 1000, "calls": 0},
                indent=2,
            ),
            encoding="utf-8",
        )

    def gh_data(self) -> dict:
        if not self.gh_state.exists():
            return {}
        return json.loads(self.gh_state.read_text(encoding="utf-8"))

    def gh_calls(self) -> list[list[str]]:
        if not self.gh_log.exists():
            return []
        return [json.loads(line) for line in self.gh_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    # ------------------------------------------------------------------- env

    def build_env(self, **overrides: str) -> dict[str, str]:
        """An environment where nothing legitimately writes to HOME.

        Git is pointed at config files outside HOME and given identity through
        environment variables, so any change inside HOME after a command must
        have come from RDH itself.
        """
        env = {
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config_dir),
            "XDG_CACHE_HOME": str(self.config_dir / "cache"),
            "XDG_DATA_HOME": str(self.config_dir / "data"),
            "XDG_STATE_HOME": str(self.config_dir / "state"),
            "TMPDIR": str(self.base / "tmp"),
            "GIT_CONFIG_GLOBAL": str(self.config_dir / "gitconfig"),
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Test Researcher",
            "GIT_AUTHOR_EMAIL": "researcher@example.invalid",
            "GIT_COMMITTER_NAME": "Test Researcher",
            "GIT_COMMITTER_EMAIL": "researcher@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RH_FAKE_GH_STATE": str(self.gh_state),
            "RH_FAKE_GH_LOG": str(self.gh_log),
        }
        (self.base / "tmp").mkdir(parents=True, exist_ok=True)
        env.update(overrides)
        return env

    # ----------------------------------------------------------------- helper

    def run(self, argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = False):
        merged = dict(self.env)
        if env:
            merged.update(env)
        result = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else str(self.base),
            env=merged,
            capture_output=True,
            text=True,
            shell=False,
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"command failed ({result.returncode}): {' '.join(argv)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def rh(self, args: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = False):
        return self.run([sys.executable, str(REPO_ROOT / "bin" / "rh"), *args], cwd=cwd, env=env, check=check)

    def rh_local(self, repo: Path, args: list[str], *, env: dict[str, str] | None = None, check: bool = False):
        """Run the *vendored* rh inside an adopted repository."""
        return self.run(
            [sys.executable, str(repo / ".research-harness" / "bin" / "rh"), *args],
            cwd=repo,
            env=env,
            check=check,
        )

    def git(self, repo: Path, args: list[str], *, check: bool = True):
        return self.run(["git", *args], cwd=repo, check=check)

    def make_repo(self, name: str = "research", *, commit: bool = True) -> Path:
        """A repo with a *pushable* local origin.

        The GitHub slug is resolved through the fake `gh` (as it would be for
        an ssh alias or an enterprise host), so pushes succeed locally while
        the GitHub side stays entirely faked.
        """
        repo = self.base / name
        origin = self.base / f"{name}-origin.git"
        repo.mkdir(parents=True, exist_ok=True)
        self.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.git(repo, ["init", "-q", "-b", "main"])
        self.git(repo, ["remote", "add", "origin", str(origin)])
        (repo / "README.md").write_text("# research\n", encoding="utf-8")
        if commit:
            self.git(repo, ["add", "-A"])
            self.git(repo, ["commit", "-q", "-m", "initial"])
        return repo

    def cleanup(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


class SandboxTestCase(unittest.TestCase):
    """Base class providing a sandbox and HOME zero-touch assertions."""

    def setUp(self) -> None:
        self.sandbox = Sandbox.create()
        self.sandbox.set_gh_repo()
        self.addCleanup(self.sandbox.cleanup)

    def home_snapshot(self) -> dict[str, str]:
        return snapshot_tree(self.sandbox.home)

    def assertHomeUnchanged(self, before: dict[str, str], msg: str = "") -> None:
        after = self.home_snapshot()
        difference = diff_snapshots(before, after)
        if difference["added"] or difference["removed"] or difference["changed"]:
            self.fail(
                f"RDH modified $HOME{(': ' + msg) if msg else ''}\n"
                f"  added:   {difference['added']}\n"
                f"  removed: {difference['removed']}\n"
                f"  changed: {difference['changed']}"
            )

    def assertNoDestructiveGit(self) -> None:
        """No destructive `git`/`gh` invocation may appear in the gh call log."""
        for call in self.sandbox.gh_calls():
            self.assertNotIn("merge", call[:2], f"RDH must never merge: {call}")
