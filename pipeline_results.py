"""
Per-run pipeline outcome tracking (pure, unit-tested), shown on the platform cards and status row.

The fetchers return None both for "the API call failed" and "there was no data", so ErrorCapture
records ERROR log lines: if one was logged while a range was being fetched, that range failed.
The pipeline fetches one platform at a time, so attributing errors by time window is unambiguous.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

OK, WARNING, FAILED = "ok", "warning", "failed"
_RANK = {OK: 0, WARNING: 1, FAILED: 2}


def _short(text: str, limit: int = 90) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"


@dataclass
class RangeResult:
    label: str  # "current" or "prior year"
    start: date
    end: date
    status: str  # "saved" | "no_data" | "failed"
    detail: str = ""


@dataclass
class PlatformResult:
    platform: str
    ranges: List[RangeResult] = field(default_factory=list)
    error: str = ""  # whole-platform failure (exception, expired token, timeout)
    skipped_reason: str = ""
    token_expired: bool = False

    @property
    def status(self) -> str:
        if self.error or any(r.status == "failed" for r in self.ranges):
            return FAILED
        if self.skipped_reason or any(r.status == "no_data" for r in self.ranges) or not self.ranges:
            return WARNING
        return OK

    def card_text(self) -> str:
        """One short line for the platform card."""
        if self.token_expired:
            return "Token expired — click Re-authenticate"
        if self.error:
            return f"Failed: {_short(self.error, 70)}"
        failed = [r for r in self.ranges if r.status == "failed"]
        if failed:
            r = failed[0]
            return f"Failed ({r.label}): {_short(r.detail, 60)}" if r.detail else f"Failed ({r.label})"
        if self.skipped_reason:
            return f"Skipped: {self.skipped_reason}"
        saved = [r for r in self.ranges if r.status == "saved"]
        empty = [r for r in self.ranges if r.status == "no_data"]
        if empty and not saved:
            return "No data for the selected range" + ("s" if len(empty) > 1 else "")
        if empty:
            return "; ".join(f"No data for {r.label} ({r.start:%b %Y})" for r in empty)
        if not saved:
            return "No result recorded"
        return f"✓ Saved {len(saved)} range" + ("s" if len(saved) != 1 else "")

    def summary_note(self) -> str:
        """Short reason for the status-row summary."""
        if self.token_expired:
            return "token expired"
        if self.status == FAILED:
            return "failed"
        if self.skipped_reason:
            return "skipped"
        empty = [r.label for r in self.ranges if r.status == "no_data"]
        return f"no {' / '.join(empty)} data" if empty else ""


@dataclass
class PipelineReport:
    platforms: Dict[str, PlatformResult] = field(default_factory=dict)
    processing_error: str = ""
    ready_files: List[str] = field(default_factory=list)
    yoy_expected: bool = False

    def platform(self, name: str) -> PlatformResult:
        if name not in self.platforms:
            self.platforms[name] = PlatformResult(name)
        return self.platforms[name]

    @property
    def level(self) -> str:
        levels = [p.status for p in self.platforms.values()]
        if self.processing_error:
            levels.append(FAILED)
        if self.yoy_expected and not self.ready_files and not self.processing_error:
            levels.append(WARNING)
        return max(levels, key=_RANK.__getitem__, default=OK)

    def summary(self) -> Tuple[str, str]:
        """(level, text) for the status row."""
        failed = [p for p in self.platforms.values() if p.status == FAILED]
        warned = [p for p in self.platforms.values() if p.status == WARNING]
        reports = len(self.ready_files)
        report_text = f"{reports} YoY report" + ("s" if reports != 1 else "")
        if self.processing_error:
            return FAILED, f"Processing failed: {_short(self.processing_error, 80)}"
        if failed:
            names = ", ".join(p.platform for p in failed)
            n = len(failed)
            return FAILED, f"Completed with {n} failure{'s' if n > 1 else ''}: {names}"
        parts = [f"{p.platform} ({p.summary_note()})" for p in warned]
        if self.yoy_expected and not self.ready_files:
            parts.append("no YoY report built")
        if parts:
            return WARNING, "Completed with warnings: " + "; ".join(parts)
        n = len(self.platforms)
        text = f"Completed: {n} platform{'s' if n != 1 else ''}"
        return OK, text + (f", {report_text}" if reports else "")


class ErrorCapture(logging.Handler):
    """Collects ERROR-and-above log messages so callers can ask "did anything fail since mark()?"."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._lock_records = threading.Lock()
        self._messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        with self._lock_records:
            self._messages.append(msg)

    def mark(self) -> int:
        with self._lock_records:
            return len(self._messages)

    def errors_since(self, mark: int) -> List[str]:
        with self._lock_records:
            return list(self._messages[mark:])

    def first_error_since(self, mark: int) -> Optional[str]:
        errors = self.errors_since(mark)
        return _short(errors[0], 120) if errors else None
