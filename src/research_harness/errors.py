"""Exception hierarchy for the RDH runtime.

Every error carries a stable ``exit_code`` so that the CLI contract in
SPEC section 34 (``0`` success, non-zero failure/unmet precondition) is
implemented in exactly one place.
"""

from __future__ import annotations


class HarnessError(Exception):
    """Base class for all deliberate harness failures."""

    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def render(self) -> str:
        if self.hint:
            return f"{self.message}\n  hint: {self.hint}"
        return self.message


class UsageError(HarnessError):
    """The caller invoked the CLI incorrectly."""

    exit_code = 2


class PreconditionError(HarnessError):
    """A deterministic precondition for the requested operation is unmet."""

    exit_code = 3


class NotARepositoryError(PreconditionError):
    """The working directory is not inside a Git repository."""


class NotAdoptedError(PreconditionError):
    """The repository has no ``.research-harness`` installation."""


class GitError(HarnessError):
    """A git invocation failed."""

    exit_code = 4


class UnsafeOperationError(HarnessError):
    """A destructive operation was requested and refused.

    RDH never performs history rewrites, force pushes, resets, stashes,
    branch/issue deletion or merges on the researcher's behalf (SPEC 38/39).
    """

    exit_code = 5


class GitHubError(HarnessError):
    """A ``gh`` invocation failed."""

    exit_code = 6


class GitHubAuthError(GitHubError):
    """``gh`` is present but not authenticated."""

    exit_code = 7


class GitHubUnavailableError(GitHubError):
    """``gh`` could not reach GitHub (network/offline/5xx).

    Callers that produce durable records translate this into an outbox write
    rather than a hard failure (SPEC 57).
    """

    exit_code = 8


class RecordError(HarnessError):
    """A durable record could not be parsed or serialized."""

    exit_code = 9


class AdoptionError(HarnessError):
    """Adoption or upgrade could not be completed safely."""

    exit_code = 10
