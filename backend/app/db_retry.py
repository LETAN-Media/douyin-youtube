"""Bounded retry with exponential backoff for transient DB errors."""
import random
import time
from functools import wraps
from typing import Callable, TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

T = TypeVar("T")

# Connection errors that are safe to retry for idempotent reads
_RETRIABLE_MESSAGES = (
    "connection reset",
    "connection error",
    "http error",
    "timeout",
    "broken pipe",
)


def is_retriable_db_error(exc: Exception) -> bool:
    """Check if exception is a transient connection error safe to retry."""
    if not isinstance(exc, (DBAPIError, OperationalError, ValueError)):
        return False
    msg = str(exc).lower()
    return any(pattern in msg for pattern in _RETRIABLE_MESSAGES)


def with_retry(
    max_attempts: int = 3,
    base_delay_ms: float = 50.0,
    max_delay_ms: float = 2000.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry idempotent DB reads with exponential backoff + jitter.
    
    WARNING: Only use for idempotent SELECT queries. Never retry mutations
    (INSERT/UPDATE/DELETE) or operations that create jobs, publish videos,
    or modify external state.
    
    Args:
        max_attempts: Total attempts (1 initial + N retries)
        base_delay_ms: Initial retry delay
        max_delay_ms: Maximum retry delay cap
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= max_attempts or not is_retriable_db_error(exc):
                        raise
                    # Exponential backoff: base * 2^(attempt-1) + jitter
                    delay = min(
                        base_delay_ms * (2 ** (attempt - 1)),
                        max_delay_ms,
                    )
                    jitter = random.uniform(0, delay * 0.3)
                    time.sleep((delay + jitter) / 1000.0)
            raise last_exc  # type: ignore

        return wrapper

    return decorator
