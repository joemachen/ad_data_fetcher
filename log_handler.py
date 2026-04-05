"""
GUI log handler for Ads Report Fetcher.
Enqueues log records to a queue so the main thread can drain them safely (avoids Tk deadlock).
"""

import logging
import queue


class GUILogHandler(logging.Handler):
    """Thread-safe log handler that enqueues formatted messages for the main thread to drain."""

    def __init__(self, log_queue: queue.Queue) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.log_queue.put_nowait(msg)
        except Exception:
            self.handleError(record)
