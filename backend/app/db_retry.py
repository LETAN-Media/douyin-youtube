"""Bounded retry with exponential backoff for transient DB errors."""
import logging
import random
import time
from functools import wraps
from typing import Callable, TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

T = TypeVar("T")

# Connection errors that are safe to retry for idempotent reads
_RETRIABLE_MESSAGES = (
    "connection reset",
    "connection error",
    "http error",
    "timeout",
    "broken pipe",
    "interactive transaction was rolled back",
    "stream was idle",
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
                    # Reset session transaction so next attempt gets clean connection
                    for a in args:
                        if isinstance(a, Session):
                            try:
                                a.invalidate()
                            except Exception:
                                pass
                    for v in kwargs.values():
                        if isinstance(v, Session):
                            try:
                                v.invalidate()
                            except Exception:
                                pass
                    # Exponential backoff: base * 2^(attempt-1) + jitter
                    delay = min(
                        base_delay_ms * (2 ** (attempt - 1)),
                        max_delay_ms,
                    )
                    jitter = random.uniform(0, delay * 0.3)
                    time.sleep(min(delay + jitter, max_delay_ms) / 1000.0)
            raise last_exc  # type: ignore

        return wrapper

    return decorator


def run_db(operation, *, session_factory=None, max_attempts=3, base_delay_ms=100,
           max_delay_ms=2000):
    """Retry a replay-safe DB-only unit in a NEW session/connection.

    Caller must use deterministic assignments/keys, never external side effects,
    increments, or random inserts. A commit acknowledgement can be lost.
    """
    if session_factory is None:
        from app.db import SessionLocal
        session_factory = SessionLocal
    for attempt in range(max_attempts):
        db = session_factory()
        try:
            result = operation(db)
            db.commit()
            return result
        except Exception as exc:
            transient = is_retriable_db_error(exc)
            try:
                if transient:
                    db.invalidate()  # discard the broken pooled connection
                else:
                    db.rollback()
            except Exception:
                pass
            if not transient or attempt + 1 >= max_attempts:
                raise
            logging.getLogger("douyin-youtube-db").warning(
                "DB-only retry attempt=%s/%s operation=%s exception_type=%s",
                attempt + 2, max_attempts, getattr(operation, "__name__", "unknown"),
                type(exc).__name__,
            )
            delay = min(base_delay_ms * 2 ** attempt, max_delay_ms)
            time.sleep(random.uniform(delay * 0.7, delay) / 1000)
        finally:
            try:
                db.close()
            except Exception:
                logging.getLogger("douyin-youtube-db").warning("Failed to close discarded DB session")
