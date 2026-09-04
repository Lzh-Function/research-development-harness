"""Command runner abstraction.

Every external process RDH spawns goes through a :class:`CommandRunner`.
Two properties are non-negotiable (SPEC 40):

* commands are always argument vectors executed with ``shell=False``;
* text originating from GitHub is never interpreted by a shell.

The indirection also lets integration tests substitute a fake runner or a
fake executable so that no test requires a real GitHub account (SPEC 63).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_TIMEOUT = 120.0


@dataclass(frozen=True)
class CommandResult:
    """Outcome of a single external command invocation."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def out(self) -> str:
        """``stdout`` with trailing newlines removed."""
        return self.stdout.rstrip("\n")

    def combined(self) -> str:
        parts = [p for p in (self.stdout.strip(), self.stderr.strip()) if p]
        return "\n".join(parts)


class CommandRunner(Protocol):
    """Anything able to execute an argument vector."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult: ...


def _normalize(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a sequence of strings, not a single string")
    out: list[str] = []
    for item in argv:
        if not isinstance(item, str):
            raise TypeError(f"argv elements must be str, got {type(item).__name__}")
        out.append(item)
    if not out:
        raise ValueError("argv must not be empty")
    return tuple(out)


@dataclass
class SubprocessRunner:
    """Real runner backed by :mod:`subprocess`, always ``shell=False``."""

    default_timeout: float = DEFAULT_TIMEOUT
    #: Extra environment entries merged into every invocation.
    env_overlay: Mapping[str, str] = field(default_factory=dict)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        vector = _normalize(argv)
        effective_env: dict[str, str] | None = None
        if env is not None or self.env_overlay:
            effective_env = dict(os.environ)
            effective_env.update(self.env_overlay)
            if env:
                effective_env.update(env)
        try:
            completed = subprocess.run(  # noqa: S603 - argv vector, shell=False
                list(vector),
                cwd=os.fspath(cwd) if cwd is not None else None,
                env=effective_env,
                input=stdin,
                capture_output=True,
                text=True,
                shell=False,
                timeout=timeout if timeout is not None else self.default_timeout,
            )
        except FileNotFoundError:
            return CommandResult(vector, 127, "", f"executable not found: {vector[0]}")
        except PermissionError:
            return CommandResult(vector, 126, "", f"executable not runnable: {vector[0]}")
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return CommandResult(vector, 124, stdout, stderr + "\ntimed out")
        return CommandResult(vector, completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def which(program: str) -> str | None:
        return shutil.which(program)


@dataclass
class RecordingRunner:
    """Wraps another runner and records every argument vector.

    Tests use this to assert the absence of destructive Git operations.
    """

    inner: CommandRunner
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        vector = _normalize(argv)
        self.calls.append(vector)
        return self.inner.run(vector, cwd=cwd, env=env, stdin=stdin, timeout=timeout)

    def argv_strings(self) -> list[str]:
        return [" ".join(call) for call in self.calls]


Responder = Callable[[tuple[str, ...], str | None], CommandResult]


@dataclass
class FakeRunner:
    """Scripted runner for unit tests.

    ``handlers`` maps an argv *prefix* (as a tuple) to either a
    :class:`CommandResult` or a callable receiving ``(argv, stdin)``.  The
    longest matching prefix wins so that specific commands can override
    generic ones.
    """

    handlers: dict[tuple[str, ...], CommandResult | Responder] = field(default_factory=dict)
    default: CommandResult | Responder | None = None
    calls: list[tuple[tuple[str, ...], str | None]] = field(default_factory=list)

    def register(self, prefix: Iterable[str], response: CommandResult | Responder) -> None:
        self.handlers[tuple(prefix)] = response

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        vector = _normalize(argv)
        self.calls.append((vector, stdin))
        best: tuple[str, ...] | None = None
        for prefix in self.handlers:
            if len(prefix) <= len(vector) and vector[: len(prefix)] == prefix:
                if best is None or len(prefix) > len(best):
                    best = prefix
        response = self.handlers[best] if best is not None else self.default
        if response is None:
            return CommandResult(vector, 127, "", f"no fake handler for: {' '.join(vector)}")
        if callable(response):
            return response(vector, stdin)
        return CommandResult(vector, response.returncode, response.stdout, response.stderr)

    def argv_strings(self) -> list[str]:
        return [" ".join(call) for call, _ in self.calls]


def ok(stdout: str = "", *, argv: Sequence[str] = ("fake",)) -> CommandResult:
    """Convenience constructor for a successful fake result."""
    return CommandResult(_normalize(argv), 0, stdout, "")


def fail(stderr: str = "", *, code: int = 1, argv: Sequence[str] = ("fake",)) -> CommandResult:
    """Convenience constructor for a failing fake result."""
    return CommandResult(_normalize(argv), code, "", stderr)
