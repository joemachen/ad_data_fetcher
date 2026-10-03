"""
Shared utility functions for Ads Report Fetcher.
"""

import random
import threading
import time
from email.utils import parsedate_to_datetime
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

# --- Retry / backoff (shared by all fetchers) ---
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 2.0
RETRY_CAP_SECONDS = 60.0
RETRY_AFTER_CAP_SECONDS = 120.0  # never wait longer than this, even if the server asks


class TokenExpiredError(Exception):
    """Raised by a fetcher when auth fails because the OAuth token is expired/invalid.

    Carries the platform name so the GUI can surface a per-platform "Re-authenticate"
    action. Detecting this typed exception is more reliable than matching error strings.
    """

    def __init__(self, message: str = "", platform: str = ""):
        super().__init__(message)
        self.platform = platform


def _parse_id_from_favorite_display(display: str) -> str:
    """Extract ID from combobox display string 'Name (ID)' or return as-is if no parens."""
    if not display or not isinstance(display, str):
        return (display or "").strip()
    s = display.strip()
    if " (" in s and s.endswith(")"):
        return s[s.rindex(" (") + 2:-1].strip()
    return s


def _mask_id_for_log(id_str: str, tail: int = 4) -> str:
    """Return a safe string for logging (e.g. ...1234). Never log full IDs or tokens."""
    if not id_str or not isinstance(id_str, str):
        return "***"
    s = id_str.strip()
    if len(s) <= tail:
        return "***"
    return "..." + s[-tail:]


def backoff_delay(
    attempt: int,
    base: float = RETRY_BASE_SECONDS,
    cap: float = RETRY_CAP_SECONDS,
    retry_after: Optional[float] = None,
    rand: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait before retry number `attempt` (0-based).

    Honours a server-provided Retry-After (capped); otherwise "full jitter":
    a random delay in [0, min(cap, base * 2**attempt)) so parallel clients don't retry in lockstep.
    """
    if retry_after is not None and retry_after >= 0:
        return min(retry_after, RETRY_AFTER_CAP_SECONDS)
    return float(rand() * min(cap, base * (2**attempt)))


def http_retry_after(exc: BaseException) -> Optional[float]:
    """Parse a Retry-After header (seconds or HTTP-date) from an HTTP error; None if absent/invalid."""
    headers = getattr(exc, "headers", None)
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    value = str(value).strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


def retry_call(
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[BaseException], bool],
    max_attempts: int = RETRY_MAX_ATTEMPTS,
    base: float = RETRY_BASE_SECONDS,
    cap: float = RETRY_CAP_SECONDS,
    retry_after: Optional[Callable[[BaseException], Optional[float]]] = None,
    on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn`, retrying transient failures with jittered exponential backoff.

    Re-raises the original exception when it isn't retryable, when attempts run out,
    or when `cancel_event` is set, so callers' existing except-handlers keep working.
    `on_retry(attempt_number, delay_seconds, exc)` is called before each wait (1-based attempt).
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            last_attempt = attempt >= max_attempts - 1
            cancelled = cancel_event is not None and cancel_event.is_set()
            if last_attempt or cancelled or not is_retryable(exc):
                raise
            delay = backoff_delay(attempt, base, cap, retry_after(exc) if retry_after else None)
            if on_retry:
                on_retry(attempt + 1, delay, exc)
            if cancel_event is not None:
                if cancel_event.wait(delay):
                    raise
            else:
                sleep(delay)
    raise RuntimeError("retry_call: max_attempts must be >= 1")
