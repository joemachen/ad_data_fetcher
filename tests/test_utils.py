"""
Tests for the shared retry helpers in utils: backoff_delay, http_retry_after, retry_call.
"""
import sys
import threading
import time
import urllib.error
from email.message import Message
from email.utils import formatdate
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils import RETRY_AFTER_CAP_SECONDS, backoff_delay, http_retry_after, retry_call


class _Transient(Exception):
    pass


class _Permanent(Exception):
    pass


def _http_error(code: int, retry_after: str = "") -> urllib.error.HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test", code, "err", headers, None)


class TestBackoffDelay:
    def test_full_jitter_bounds(self):
        assert backoff_delay(0, base=2, rand=lambda: 0.0) == 0.0
        assert backoff_delay(0, base=2, rand=lambda: 0.999) < 2
        assert backoff_delay(2, base=2, rand=lambda: 0.5) == pytest.approx(4.0)  # 0.5 * 2*2**2

    def test_cap_limits_growth(self):
        assert backoff_delay(10, base=2, cap=60, rand=lambda: 1.0) == 60

    def test_retry_after_wins_and_is_capped(self):
        assert backoff_delay(0, retry_after=7, rand=lambda: 0.0) == 7
        assert backoff_delay(0, retry_after=10_000) == RETRY_AFTER_CAP_SECONDS


class TestHttpRetryAfter:
    def test_seconds(self):
        assert http_retry_after(_http_error(429, "7")) == 7.0

    def test_http_date(self):
        got = http_retry_after(_http_error(503, formatdate(time.time() + 30, usegmt=True)))
        assert got is not None and 25 <= got <= 31

    def test_missing_header(self):
        assert http_retry_after(_http_error(503)) is None

    def test_garbage_value(self):
        assert http_retry_after(_http_error(503, "soon-ish")) is None

    def test_non_http_exception(self):
        assert http_retry_after(ValueError("x")) is None


class TestRetryCall:
    def _run(self, outcomes, **kw):
        """Run retry_call over a scripted list of outcomes (exceptions raise, values return)."""
        calls, sleeps, retries = [], [], []

        def fn():
            outcome = outcomes[len(calls)]
            calls.append(outcome)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        kw.setdefault("is_retryable", lambda e: isinstance(e, _Transient))
        result = retry_call(
            fn,
            sleep=sleeps.append,
            on_retry=lambda attempt, delay, exc: retries.append((attempt, type(exc).__name__)),
            **kw,
        )
        return result, calls, sleeps, retries

    def test_success_first_try(self):
        result, calls, sleeps, _ = self._run(["ok"])
        assert result == "ok" and len(calls) == 1 and sleeps == []

    def test_success_after_transient_failures(self):
        result, calls, sleeps, retries = self._run([_Transient(), _Transient(), "ok"])
        assert result == "ok"
        assert len(calls) == 3 and len(sleeps) == 2
        assert retries == [(1, "_Transient"), (2, "_Transient")]

    def test_permanent_error_not_retried(self):
        with pytest.raises(_Permanent):
            self._run([_Permanent(), "never"])

    def test_exhausted_attempts_reraise_last_error(self):
        err = _Transient("third")
        with pytest.raises(_Transient) as info:
            self._run([_Transient(), _Transient(), err], max_attempts=3)
        assert info.value is err

    def test_retry_after_used_for_delay(self):
        _, _, sleeps, _ = self._run([_Transient(), "ok"], retry_after=lambda e: 9.0)
        assert sleeps == [9.0]

    def test_cancel_event_stops_retrying(self):
        cancel = threading.Event()
        cancel.set()
        attempts = []

        def fn():
            attempts.append(1)
            raise _Transient()

        with pytest.raises(_Transient):
            retry_call(fn, is_retryable=lambda e: True, cancel_event=cancel)
        assert len(attempts) == 1
