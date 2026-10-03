"""
Quick date-range presets for the Main tab (pure functions, unit-tested).

"Last N days" ends yesterday, like the ad platforms' own presets, because today's data is still
coming in. "Month to date" includes today, matching the app's default range.
"""

from datetime import date, timedelta
from typing import Tuple

PRESETS = ("Month to date", "Last month", "Last 7 days", "Last 30 days")


def preset_range(name: str, today: date) -> Tuple[date, date]:
    """Return (start, end) for a preset name relative to `today`."""
    if name == "Month to date":
        return today.replace(day=1), today
    if name == "Last month":
        last_of_prev = today.replace(day=1) - timedelta(days=1)
        return last_of_prev.replace(day=1), last_of_prev
    if name.startswith("Last ") and name.endswith(" days"):
        days = int(name.split()[1])
        end = today - timedelta(days=1)
        return end - timedelta(days=days - 1), end
    raise ValueError(f"Unknown date preset: {name}")
