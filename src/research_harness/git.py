"""Deterministic Git access.

Two responsibilities:

1. read repository state (root, HEAD, branch, dirtiness, remotes, worktrees);
2. perform the *small, additive* set of write operations RDH is allowed to do
   (create/switch a branch, push a branch upstream).

Every argument vector is screened by :func:`assert_safe_git` first, so the
"RDH never destroys user work" contract (SPEC 38/39) is enforced in code and
directly testable rather than merely documented.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import GitError, NotARepositoryError, UnsafeOperationError
from .proc import CommandResult, CommandRunner, SubprocessRunner

#: Subcommands RDH must never invoke, with the reason surfaced to the caller.
FORBIDDEN_SUBCOMMANDS: dict[str, str] = {
    "clean": "removes untracked user files",
    "stash": "hides uncommitted user work",
    "filter-branch": "rewrites history",
    "filter-repo": "rewrites history",
    "rebase": "rewrites history",
    "reflog": "can delete recovery information",
    "gc": "can prune unreachable user work",
    "prune": "can prune unreachable user work",
}

_FORCE_FLAGS = {"-f", "--force", "--force-with-lease", "--force-if-includes"}
_BRANCH_DELETE_FLAGS = {"-d", "-D", "--delete", "-delete"}


def assert_safe_git(argv: Sequence[str]) -> None:
    """Refuse destructive Git invocations before they reach a subprocess.

    Raises :class:`UnsafeOperationError` for anything that could destroy
    uncommitted work, delete refs, or rewrite history.
    """
    args = [a for a in argv]
    if args and args[0] == "git":
        args = args[1:]
    # Skip leading global options such as ``-C <path>`` / ``--no-pager``.
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
        else:
            index += 1
    if index >= len(args):
        return
    subcommand = args[index]
    rest = args[index + 1 :]

    reason = FORBIDDEN_SUBCOMMANDS.get(subcommand)
    if reason is not None:
        raise UnsafeOperationError(
            f"refusing to run 'git {subcommand}': {reason}",
            hint="RDH never destroys or rewrites researcher work; do this yourself if intended.",
        )

    if subcommand == "reset" and any(a in {"--hard", "--merge", "--keep"} for a in rest):
        raise UnsafeOperationError(
            "refusing to run 'git reset --hard' (or equivalent): discards uncommitted work"
        )
    if subcommand in {"checkout", "switch", "restore"}:
        if any(a in _FORCE_FLAGS or a == "--discard-changes" for a in rest):
            raise UnsafeOperationError(
                f"refusing to run a forced 'git {subcommand}': discards uncommitted work"
            )
        if subcommand == "restore" or (subcommand == "checkout" and "--" in rest):
            raise UnsafeOperationError(
                f"refusing to run 'git {subcommand}' on paths: overwrites researcher edits"
            )
    if subcommand == "branch" and any(a in _BRANCH_DELETE_FLAGS for a in rest):
        raise UnsafeOperationError("refusing to delete a branch")
    if subcommand == "worktree" and rest[:1] == ["remove"]:
        raise UnsafeOperationError("refusing to remove a worktree")
    if subcommand == "push":
        if any(a in _FORCE_FLAGS for a in rest):
            raise UnsafeOperationError("refusing to force-push")
        if "--delete" in rest or "-d" in rest:
            raise UnsafeOperationError("refusing to delete a remote ref")
        if any(a.startswith("+") and "refs/" in a or a.startswith(":") for a in rest):
            raise UnsafeOperationError("refusing to force-update or delete a remote ref")
    if subcommand == "commit" and "--amend" in rest:
        raise UnsafeOperationError("refusing to amend an existing commit")
    if subcommand == "update-ref" and ("-d" in rest or "--delete" in rest):
        raise UnsafeOperationError("refusing to delete a ref")
    if subcommand == "tag" and any(a in _BRANCH_DELETE_FLAGS for a in rest):
        raise UnsafeOperationError("refusing to delete a tag")


@dataclass(frozen=True)
class WorktreeInfo:
    path: str
    head: str | None
    branch: str | None
    detached: bool = False
    bare: bool = False


@dataclass(frozen=True)
class StatusEntry:
    code: str
    path: str

    @property
    def untracked(self) -> bool:
        return self.code == "??"


class GitRepo:
    """A checked-out Git repository RDH may inspect and additively modify."""

    def __init__(self, root: Path, runner: CommandRunner | None = None) -> None:
        self.root = Path(root).resolve()
        self.runner: CommandRunner = runner or SubprocessRunner()

    # ---------------------------------------------------------------- discovery

    @classmethod
    def discover(cls, start: Path | str | None = None, runner: CommandRunner | None = None) -> "GitRepo":
        """Locate the repository containing ``start`` (default: cwd)."""
        runner = runner or SubprocessRunner()
        begin = Path(start) if start is not None else Path.cwd()
        begin = begin.resolve()
        probe_dir = begin if begin.is_dir() else begin.parent
        result = runner.run(["git", "rev-parse", "--show-toplevel"], cwd=probe_dir)
        if result.returncode == 127:
            raise GitError("git executable not found on PATH", hint="Install Git 2.30+ and retry.")
        if not result.ok:
            raise NotARepositoryError(
                f"not inside a Git repository: {probe_dir}",
                hint="Run RDH from within the research repository, or pass --repo.",
            )
        return cls(Path(result.out), runner)

    # ------------------------------------------------------------------ plumbing

    def run(self, args: Sequence[str], *, stdin: str | None = None, check: bool = False) -> CommandResult:
        argv = ["git", *args]
        assert_safe_git(argv)
        result = self.runner.run(argv, cwd=self.root, stdin=stdin)
        if check and not result.ok:
            raise GitError(f"git {' '.join(args)} failed: {result.combined() or result.returncode}")
        return result

    def _lines(self, args: Sequence[str]) -> list[str]:
        result = self.run(args)
        if not result.ok:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    # ---------------------------------------------------------------------- read

    def head(self) -> str | None:
        result = self.run(["rev-parse", "HEAD"])
        return result.out if result.ok else None

    def short_head(self) -> str | None:
        head = self.head()
        return head[:10] if head else None

    def branch(self) -> str | None:
        """Current branch name, or ``None`` when HEAD is detached."""
        result = self.run(["symbolic-ref", "--quiet", "--short", "HEAD"])
        return result.out or None if result.ok else None

    def is_detached(self) -> bool:
        return self.branch() is None

    def status(self) -> list[StatusEntry]:
        result = self.run(["status", "--porcelain=v1", "--untracked-files=normal"])
        entries: list[StatusEntry] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2], line[3:]
            if " -> " in path:  # rename
                path = path.split(" -> ", 1)[1]
            entries.append(StatusEntry(code.strip() or code, path.strip('"')))
        return entries

    def is_dirty(self) -> bool:
        return bool(self.status())

    def changed_paths(self) -> list[str]:
        return [entry.path for entry in self.status()]

    def remotes(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self._lines(["remote", "-v"]):
            parts = line.split()
            if len(parts) >= 2 and parts[0] not in out:
                out[parts[0]] = parts[1]
        return out

    def default_remote(self) -> str | None:
        remotes = self.remotes()
        if not remotes:
            return None
        if "origin" in remotes:
            return "origin"
        return next(iter(remotes))

    def remote_url(self, name: str | None = None) -> str | None:
        remotes = self.remotes()
        key = name or self.default_remote()
        return remotes.get(key) if key else None

    def local_branches(self) -> list[str]:
        return self._lines(["for-each-ref", "--format=%(refname:short)", "refs/heads"])

    def remote_branches(self) -> list[str]:
        return self._lines(["for-each-ref", "--format=%(refname:short)", "refs/remotes"])

    def branch_exists(self, name: str) -> bool:
        return self.run(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"]).ok

    def upstream(self, branch: str | None = None) -> str | None:
        ref = f"{branch}@{{upstream}}" if branch else "@{upstream}"
        result = self.run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", ref])
        return result.out if result.ok and result.out else None

    def worktrees(self) -> list[WorktreeInfo]:
        result = self.run(["worktree", "list", "--porcelain"])
        if not result.ok:
            return []
        trees: list[WorktreeInfo] = []
        path: str | None = None
        head: str | None = None
        branch: str | None = None
        detached = False
        bare = False

        def flush() -> None:
            nonlocal path, head, branch, detached, bare
            if path is not None:
                trees.append(WorktreeInfo(path, head, branch, detached, bare))
            path, head, branch, detached, bare = None, None, None, False, False

        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                flush()
                path = line[len("worktree ") :]
            elif line.startswith("HEAD "):
                head = line[len("HEAD ") :]
            elif line.startswith("branch "):
                branch = line[len("branch ") :].removeprefix("refs/heads/")
            elif line.strip() == "detached":
                detached = True
            elif line.strip() == "bare":
                bare = True
        flush()
        return trees

    def recent_commits(self, count: int = 20) -> list[dict[str, str]]:
        fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s"
        lines = self._lines(["log", f"-{max(1, count)}", f"--pretty=format:{fmt}"])
        commits: list[dict[str, str]] = []
        for line in lines:
            parts = line.split("\x1f")
            if len(parts) == 5:
                commits.append(
                    {"sha": parts[0], "short": parts[1], "author": parts[2], "date": parts[3], "subject": parts[4]}
                )
        return commits

    def commits_since(self, sha: str, *, limit: int = 100) -> list[dict[str, str]]:
        if not sha:
            return []
        fmt = "%H%x1f%h%x1f%an%x1f%aI%x1f%s"
        lines = self._lines(["log", f"{sha}..HEAD", f"-{limit}", f"--pretty=format:{fmt}"])
        commits: list[dict[str, str]] = []
        for line in lines:
            parts = line.split("\x1f")
            if len(parts) == 5:
                commits.append(
                    {"sha": parts[0], "short": parts[1], "author": parts[2], "date": parts[3], "subject": parts[4]}
                )
        return commits

    def diff_names_since(self, sha: str) -> list[str]:
        """Committed + uncommitted paths that changed since ``sha``."""
        if not sha:
            return []
        names = set(self._lines(["diff", "--name-only", f"{sha}...HEAD"]))
        names.update(self.changed_paths())
        return sorted(names)

    def object_exists(self, sha: str) -> bool:
        if not sha:
            return False
        return self.run(["cat-file", "-e", f"{sha}^{{commit}}"]).ok

    def git_common_dir(self) -> Path:
        """Absolute path of the shared ``.git`` directory (worktree aware)."""
        result = self.run(["rev-parse", "--path-format=absolute", "--git-common-dir"])
        if result.ok and result.out:
            return Path(result.out)
        result = self.run(["rev-parse", "--git-common-dir"])
        if result.ok and result.out:
            candidate = Path(result.out)
            return candidate if candidate.is_absolute() else (self.root / candidate).resolve()
        return self.root / ".git"

    def state_dir(self) -> Path:
        """``.git/research-harness`` — local, never committed (SPEC 56)."""
        return self.git_common_dir() / "research-harness"

    def tracked_file_exists(self, relpath: str) -> bool:
        return self.run(["ls-files", "--error-unmatch", relpath]).ok

    # --------------------------------------------------------------------- write

    def create_branch(self, name: str, *, start_point: str | None = None) -> None:
        """Create and switch to ``name``. Never forced, never a rename."""
        if self.branch_exists(name):
            raise GitError(f"branch already exists: {name}", hint="Use --existing-branch to adopt it.")
        args = ["switch", "--create", name]
        if start_point:
            args.append(start_point)
        result = self.run(args)
        if not result.ok:
            raise GitError(f"could not create branch {name}: {result.combined()}")

    def switch_branch(self, name: str) -> None:
        """Switch to an existing branch without discarding local changes."""
        if not self.branch_exists(name):
            raise GitError(f"no such branch: {name}")
        result = self.run(["switch", name])
        if not result.ok:
            raise GitError(
                f"could not switch to {name}: {result.combined()}",
                hint="Commit or move your local changes yourself; RDH will not stash them.",
            )

    def push_branch(self, name: str, *, remote: str | None = None, set_upstream: bool = True) -> CommandResult:
        target = remote or self.default_remote()
        if not target:
            raise GitError("no git remote configured", hint="Add a GitHub remote: git remote add origin <url>")
        args = ["push"]
        if set_upstream:
            args.append("--set-upstream")
        args.extend([target, name])
        return self.run(args)


def parse_github_remote(url: str) -> tuple[str, str] | None:
    """Extract ``(owner, repo)`` from an https/ssh GitHub remote URL."""
    if not url:
        return None
    text = url.strip()
    text = text.removesuffix(".git")
    for prefix in ("git@github.com:", "ssh://git@github.com/", "https://github.com/", "http://github.com/", "github.com:"):
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            break
    else:
        return None
    parts = [p for p in rest.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def find_repo_root(start: Path | str | None = None) -> Path:
    """Filesystem-only repository discovery (used before git is guaranteed)."""
    begin = Path(start or os.getcwd()).resolve()
    for candidate in [begin, *begin.parents]:
        if (candidate / ".git").exists():
            return candidate
    raise NotARepositoryError(f"not inside a Git repository: {begin}")
