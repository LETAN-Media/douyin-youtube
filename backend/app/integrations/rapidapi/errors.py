"""Typed failures for the RapidAPI provider pool.

The pool only needs a small, stable classification: which provider failed, why,
and whether another provider may succeed. Messages are truncated and never
contain credentials.
"""

from __future__ import annotations


class RapidApiFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        kind: str = "provider",
        provider_id: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message[:2000])
        self.kind = kind
        self.provider_id = provider_id
        self.retryable = retryable


class RapidApiPoolError(RuntimeError):
    """Raised when every eligible RapidAPI provider failed."""

    def __init__(self, failures: list[RapidApiFailure]) -> None:
        self.failures = list(failures)
        super().__init__(self.summary())

    @property
    def quota_exhausted(self) -> bool:
        return bool(self.failures) and all(
            f.kind == "quota" for f in self.failures
        )

    @property
    def auth_failed(self) -> bool:
        return bool(self.failures) and all(f.kind == "auth" for f in self.failures)

    def summary(self) -> str:
        if not self.failures:
            return "RAPIDAPI_POOL_EMPTY: không có provider RapidAPI khả dụng"
        parts = []
        for failure in self.failures:
            label = failure.provider_id or "provider"
            message = str(failure).strip()
            parts.append(f"{label}: {failure.kind}: {message}" if message else f"{label}: {failure.kind}")
        return "RAPIDAPI_POOL_EXHAUSTED: " + " | ".join(parts)[:2000]


__all__ = ["RapidApiFailure", "RapidApiPoolError"]
