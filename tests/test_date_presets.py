"""Tests for date_presets.preset_range."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from date_presets import PRESETS, preset_range

TODAY = date(2026, 10, 3)


def test_month_to_date_includes_today():
    assert preset_range("Month to date", TODAY) == (date(2026, 10, 1), date(2026, 10, 3))


def test_month_to_date_on_first_of_month():
    assert preset_range("Month to date", date(2026, 10, 1)) == (date(2026, 10, 1), date(2026, 10, 1))


def test_last_month_full_calendar_month():
    assert preset_range("Last month", TODAY) == (date(2026, 9, 1), date(2026, 9, 30))


def test_last_month_across_year_boundary():
    assert preset_range("Last month", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))


def test_last_n_days_end_yesterday():
    assert preset_range("Last 7 days", TODAY) == (date(2026, 9, 26), date(2026, 10, 2))
    assert preset_range("Last 30 days", TODAY) == (date(2026, 9, 3), date(2026, 10, 2))


@pytest.mark.parametrize("name", PRESETS)
def test_every_preset_is_a_valid_range(name):
    start, end = preset_range(name, TODAY)
    assert start <= end <= TODAY


def test_unknown_preset_raises():
    with pytest.raises(ValueError):
        preset_range("Next quarter", TODAY)
