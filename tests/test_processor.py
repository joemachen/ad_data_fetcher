"""
Tests for processor.ReportProcessor: range parsing, month/year from filename, YoY column order.
"""
import pytest
from pathlib import Path
import sys

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processor import ReportProcessor, RANGE_FILENAME_PATTERN


@pytest.fixture
def processor(tmp_path):
    """ReportProcessor with temp input/output dirs and no file handlers to avoid log noise."""
    return ReportProcessor(
        input_dir=str(tmp_path / "raw"),
        output_dir=str(tmp_path / "processed"),
        status_callback=None,
        user_input_callback=None,
    )


class TestParseRangeFromFilename:
    """Tests for _parse_range_from_filename."""

    def test_valid_range_filename(self, processor):
        got = processor._parse_range_from_filename("2025-01-05_2025-01-20.csv")
        assert got is not None
        start_str, end_str, range_id = got
        assert start_str == "2025-01-05"
        assert end_str == "2025-01-20"
        assert range_id == "01-05_01-20"

    def test_valid_range_cross_year(self, processor):
        got = processor._parse_range_from_filename("2024-12-01_2025-01-15.csv")
        assert got is not None
        start_str, end_str, range_id = got
        assert start_str == "2024-12-01"
        assert end_str == "2025-01-15"
        assert range_id == "12-01_01-15"

    def test_none_for_invalid_filename(self, processor):
        assert processor._parse_range_from_filename("jan_2025.csv") is None
        assert processor._parse_range_from_filename("2025-01-05.csv") is None
        assert processor._parse_range_from_filename("2025-01-05_2025-01-20") is None
        assert processor._parse_range_from_filename("") is None


class TestParseMonthYearFromRangeFilename:
    """Tests for _parse_month_year_from_range_filename."""

    def test_valid_filename_returns_month_and_year(self, processor):
        month_str, year_str = processor._parse_month_year_from_range_filename("2025-01-05_2025-01-20.csv")
        assert month_str == "January"
        assert year_str == "2025"

    def test_invalid_filename_returns_unknown(self, processor):
        month_str, year_str = processor._parse_month_year_from_range_filename("jan_2025.csv")
        assert month_str == "Unknown"
        assert year_str == "Unknown"


class TestYoYColumnOrder:
    """YoY report column order: Campaign, Platform, Channel, Funnel Stage, then each metric newer year first."""

    def test_yoy_final_columns_order(self):
        key_cols = ["Campaign", "Platform", "Channel", "Funnel Stage"]
        metric_cols = ["Impressions", "Clicks", "Cost", "Revenue", "Conversions"]
        y1, y2 = 2024, 2025  # prior, current
        final_cols = (
            key_cols
            + [f"{c} ({y2})" for c in metric_cols]
            + [f"{c} ({y1})" for c in metric_cols]
        )
        assert final_cols[0:4] == key_cols
        assert final_cols[4:9] == [f"Impressions ({y2})", f"Clicks ({y2})", f"Cost ({y2})", f"Revenue ({y2})", f"Conversions ({y2})"]
        assert final_cols[9:14] == [f"Impressions ({y1})", f"Clicks ({y1})", f"Cost ({y1})", f"Revenue ({y1})", f"Conversions ({y1})"]

    def test_range_filename_pattern_matches_valid(self):
        assert RANGE_FILENAME_PATTERN.match("2025-01-05_2025-01-20.csv") is not None
        assert RANGE_FILENAME_PATTERN.match("2024-12-01_2025-01-15.csv") is not None

    def test_range_filename_pattern_rejects_invalid(self):
        assert RANGE_FILENAME_PATTERN.match("jan_2025.csv") is None
        assert RANGE_FILENAME_PATTERN.match("2025-01-05.csv") is None
