"""
Tests for processor.ReportProcessor: range parsing, month/year from filename, YoY column order.
"""
import sys
from pathlib import Path

import pytest

# Allow importing from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processor import RANGE_FILENAME_PATTERN, ReportProcessor, interleave_period_columns


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


class TestRangeFilenamePattern:
    """RANGE_FILENAME_PATTERN accepts YYYY-MM-DD_YYYY-MM-DD.csv only."""

    def test_range_filename_pattern_matches_valid(self):
        assert RANGE_FILENAME_PATTERN.match("2025-01-05_2025-01-20.csv") is not None
        assert RANGE_FILENAME_PATTERN.match("2024-12-01_2025-01-15.csv") is not None

    def test_range_filename_pattern_rejects_invalid(self):
        assert RANGE_FILENAME_PATTERN.match("jan_2025.csv") is None
        assert RANGE_FILENAME_PATTERN.match("2025-01-05.csv") is None


# ---------------------------------------------------------------------------
# TestInterleavePeriodColumns
# ---------------------------------------------------------------------------

KEY_COLS = ["Campaign", "Platform", "Channel", "Funnel Stage"]
METRICS = ["Impressions", "Clicks", "Cost", "Revenue", "Conversions"]


def _blocked(newer: str, older: str) -> list:
    """Old layout: all newer-period metrics, then all older-period metrics."""
    return KEY_COLS + [f"{m} ({newer})" for m in METRICS] + [f"{m} ({older})" for m in METRICS]


def _interleaved(*periods: str) -> list:
    return KEY_COLS + [f"{m} ({p})" for m in METRICS for p in periods]


class TestInterleavePeriodColumns:
    """interleave_period_columns() groups each metric's periods side-by-side."""

    def test_blocked_layout_becomes_interleaved(self):
        assert interleave_period_columns(_blocked("2026", "2025")) == [
            "Campaign", "Platform", "Channel", "Funnel Stage",
            "Impressions (2026)", "Impressions (2025)",
            "Clicks (2026)", "Clicks (2025)",
            "Cost (2026)", "Cost (2025)",
            "Revenue (2026)", "Revenue (2025)",
            "Conversions (2026)", "Conversions (2025)",
        ]

    def test_arbitrary_years_not_hardcoded(self):
        assert interleave_period_columns(_blocked("2031", "2030")) == _interleaved("2031", "2030")

    def test_explicit_period_order_overrides_appearance(self):
        cols = _blocked("2024", "2025")  # older period appears first
        assert interleave_period_columns(cols, periods=["2025", "2024"]) == _interleaved("2025", "2024")

    def test_three_periods(self):
        cols = KEY_COLS + [f"{m} ({p})" for p in ("2024", "2026", "2025") for m in METRICS]
        got = interleave_period_columns(cols, periods=["2026", "2025", "2024"])
        assert got == _interleaved("2026", "2025", "2024")

    def test_non_year_period_labels(self):
        a, b = "2025-01-05_2025-01-20", "2024-01-05_2024-01-20"
        assert interleave_period_columns(_blocked(a, b)) == _interleaved(a, b)

    def test_metric_name_with_parentheses(self):
        cols = ["Campaign", "Cost (USD) (2026)", "Cost (USD) (2025)"]
        assert interleave_period_columns(cols) == cols
        cols = ["Campaign", "Cost (USD) (2026)", "Clicks (2026)", "Cost (USD) (2025)", "Clicks (2025)"]
        assert interleave_period_columns(cols) == [
            "Campaign", "Cost (USD) (2026)", "Cost (USD) (2025)", "Clicks (2026)", "Clicks (2025)",
        ]

    def test_metadata_with_parentheses_left_alone_when_periods_given(self):
        cols = ["Campaign (ID)", "Platform", "Clicks (2026)", "Clicks (2025)"]
        got = interleave_period_columns(cols, periods=["2026", "2025"])
        assert got == ["Campaign (ID)", "Platform", "Clicks (2026)", "Clicks (2025)"]

    def test_metric_missing_in_one_period(self):
        cols = KEY_COLS + ["Clicks (2026)", "Revenue (2026)", "Clicks (2025)"]
        got = interleave_period_columns(cols, periods=["2026", "2025"])
        assert got == KEY_COLS + ["Clicks (2026)", "Clicks (2025)", "Revenue (2026)"]

    def test_result_is_permutation_of_input(self):
        cols = _blocked("2026", "2025") + ["Notes"]
        got = interleave_period_columns(cols)
        assert sorted(got) == sorted(cols)
        assert got[:4] == KEY_COLS and "Notes" in got[:5]

    def test_no_period_columns_is_identity(self):
        assert interleave_period_columns(KEY_COLS) == KEY_COLS


# ---------------------------------------------------------------------------
# Extended fixture: all four dirs under tmp_path; mappings writes redirected
# ---------------------------------------------------------------------------

@pytest.fixture
def full_processor(tmp_path):
    """ReportProcessor with all four dirs and mappings file redirected to tmp_path."""
    from processor import ReportProcessor
    proc = ReportProcessor(
        input_dir=str(tmp_path / "raw"),
        output_dir=str(tmp_path / "processed"),
        merged_dir=str(tmp_path / "merged"),
        ready_dir=str(tmp_path / "ready"),
        status_callback=None,
        user_input_callback=None,
    )
    # Redirect mappings file to tmp_path so tests never write to the real mappings.json
    proc.mappings_file = tmp_path / "mappings.json"
    proc.campaign_mappings = {}  # clear any real mappings loaded at init
    return proc


# ---------------------------------------------------------------------------
# TestProcessFile
# ---------------------------------------------------------------------------

class TestProcessFile:
    """Tests for process_file() with real temp CSVs."""

    def test_google_csv_produces_internal_schema_columns(self, full_processor, tmp_path):
        """A minimal Google Ads CSV is mapped to all INTERNAL_SCHEMA columns."""
        from processor import INTERNAL_SCHEMA
        platform_dir = tmp_path / "raw" / "google"
        platform_dir.mkdir(parents=True)
        csv_path = platform_dir / "2025-01-05_2025-01-20.csv"
        csv_path.write_text(
            "campaign_name,impressions,clicks,cost,all_conversions_value,conversions\n"
            "Test Campaign,1000,50,10.0,100.0,5\n"
        )
        import pandas as pd
        result = full_processor.process_file(csv_path)
        assert result is not None
        df = pd.read_csv(result)
        for col in INTERNAL_SCHEMA:
            assert col in df.columns, f"Missing column: {col}"

    def test_missing_revenue_column_filled_with_zero(self, full_processor, tmp_path):
        """Revenue absent in raw CSV is filled with 0 in processed output."""
        import pandas as pd
        platform_dir = tmp_path / "raw" / "google"
        platform_dir.mkdir(parents=True)
        csv_path = platform_dir / "2025-01-05_2025-01-20.csv"
        csv_path.write_text(
            "campaign_name,impressions,clicks,cost,conversions\n"
            "Test Campaign,1000,50,10.0,5\n"
        )
        result = full_processor.process_file(csv_path)
        assert result is not None
        df = pd.read_csv(result)
        assert "Revenue" in df.columns
        assert df["Revenue"].iloc[0] == 0

    def test_month_and_year_derived_from_filename(self, full_processor, tmp_path):
        """Month and Year columns are set from the filename start date."""
        import pandas as pd
        platform_dir = tmp_path / "raw" / "meta"
        platform_dir.mkdir(parents=True)
        csv_path = platform_dir / "2025-03-01_2025-03-31.csv"
        csv_path.write_text(
            "Campaign name,Impressions,Link clicks,Amount spent,Purchases conversion value,Results\n"
            "Spring Campaign,500,20,5.0,50.0,2\n"
        )
        result = full_processor.process_file(csv_path)
        assert result is not None
        df = pd.read_csv(result)
        assert df["Month"].iloc[0] == "March"
        assert str(df["Year"].iloc[0]) == "2025"

    def test_platform_column_set_correctly(self, full_processor, tmp_path):
        """Platform column matches the platform's display name."""
        import pandas as pd
        platform_dir = tmp_path / "raw" / "reddit"
        platform_dir.mkdir(parents=True)
        csv_path = platform_dir / "2025-01-05_2025-01-20.csv"
        csv_path.write_text(
            "campaign_name,amount_spent,impressions,clicks,"
            "conversion_purchase_clicks,conversion_purchase_views,"
            "conversion_purchase_total_value,conversions\n"
            "Reddit Campaign,10.0,500,25,2,1,30.0,3\n"
        )
        result = full_processor.process_file(csv_path)
        assert result is not None
        df = pd.read_csv(result)
        assert df["Platform"].iloc[0] == "Reddit Ads"


# ---------------------------------------------------------------------------
# TestDetermineFunnel
# ---------------------------------------------------------------------------

class TestDetermineFunnel:
    """Tests for determine_funnel() classification logic."""

    def test_brand_keyword_returns_bottom(self, full_processor):
        assert full_processor.determine_funnel("Brand Awareness Q1") == "Bottom"

    def test_branded_keyword_returns_bottom(self, full_processor):
        assert full_processor.determine_funnel("Branded Search Campaign") == "Bottom"

    def test_unknown_campaign_no_callback_returns_top(self, full_processor):
        assert full_processor.determine_funnel("Prospecting - New Users") == "Top"

    def test_empty_campaign_returns_top(self, full_processor):
        assert full_processor.determine_funnel("") == "Top"

    def test_none_campaign_returns_top(self, full_processor):
        assert full_processor.determine_funnel(None) == "Top"

    def test_mapping_lookup_is_case_insensitive(self, full_processor):
        full_processor.campaign_mappings["SPRING SALE"] = "Bottom"
        assert full_processor.determine_funnel("spring sale") == "Bottom"

    def test_delete_choice_via_callback_is_saved(self, full_processor):
        """Callback returning DELETE is saved to mappings."""
        full_processor.user_input_callback = lambda _: "DELETE"
        result = full_processor.determine_funnel("New Campaign")
        assert result == "DELETE"
        assert full_processor.campaign_mappings.get("New Campaign") == "DELETE"

    def test_skip_choice_is_not_persisted(self, full_processor):
        """Callback returning SKIP is not saved to mappings."""
        full_processor.user_input_callback = lambda _: "SKIP"
        full_processor.determine_funnel("Another Campaign")
        assert "Another Campaign" not in full_processor.campaign_mappings


# ---------------------------------------------------------------------------
# TestMergePlatformData
# ---------------------------------------------------------------------------

class TestMergePlatformData:
    """Tests for merge_platform_data()."""

    def _write_processed_csv(self, path: Path, platform: str) -> None:
        import pandas as pd

        from processor import INTERNAL_SCHEMA
        data = {col: ["Unknown"] for col in INTERNAL_SCHEMA}
        data["Platform"] = [platform]
        data["Campaign"] = ["Campaign A"]
        for num_col in ("Impressions", "Clicks", "Cost", "Revenue", "Conversions"):
            data[num_col] = [10]
        pd.DataFrame(data).to_csv(path, index=False)

    def test_merge_combines_two_platforms(self, full_processor, tmp_path):
        filename = "2025-01-05_2025-01-20.csv"
        for platform in ("google", "meta"):
            d = tmp_path / "processed" / platform
            d.mkdir(parents=True)
            self._write_processed_csv(d / filename, platform)
        full_processor.merge_platform_data()
        merged_file = tmp_path / "merged" / filename
        assert merged_file.exists()
        import pandas as pd
        df = pd.read_csv(merged_file)
        assert len(df) == 2
        assert set(df["Platform"]) == {"google", "meta"}

    def test_merge_creates_merged_dir_if_absent(self, full_processor, tmp_path):
        filename = "2025-02-01_2025-02-28.csv"
        d = tmp_path / "processed" / "microsoft"
        d.mkdir(parents=True)
        self._write_processed_csv(d / filename, "Microsoft Ads")
        full_processor.merge_platform_data()
        assert (tmp_path / "merged").exists()

    def test_merge_with_no_files_does_not_raise(self, full_processor):
        full_processor.merge_platform_data()  # should not raise


# ---------------------------------------------------------------------------
# TestBuildYoYReports
# ---------------------------------------------------------------------------

class TestBuildYoYReports:
    """Tests for build_yoy_reports() pairing consecutive years."""

    def _write_merged_csv(self, path: Path, platform: str = "Google Ads") -> None:
        import pandas as pd

        from processor import INTERNAL_SCHEMA
        data = {col: ["Unknown"] for col in INTERNAL_SCHEMA}
        data["Platform"] = [platform]
        data["Campaign"] = ["Test Campaign"]
        data["Funnel Stage"] = ["Top"]
        for num_col in ("Impressions", "Clicks", "Cost", "Revenue", "Conversions"):
            data[num_col] = [100]
        pd.DataFrame(data).to_csv(path, index=False)

    def test_consecutive_years_produce_ready_file(self, full_processor, tmp_path):
        merged_dir = tmp_path / "merged"
        merged_dir.mkdir()
        self._write_merged_csv(merged_dir / "2024-01-05_2024-01-20.csv")
        self._write_merged_csv(merged_dir / "2025-01-05_2025-01-20.csv")
        full_processor.build_yoy_reports()
        ready_files = list((tmp_path / "ready").glob("ready_*.csv"))
        assert len(ready_files) == 1
        assert "vs_2024" in ready_files[0].name

    def test_yoy_newer_year_columns_come_first(self, full_processor, tmp_path):
        """Columns for the newer year appear before the prior year's columns."""
        import pandas as pd
        merged_dir = tmp_path / "merged"
        merged_dir.mkdir()
        self._write_merged_csv(merged_dir / "2024-01-05_2024-01-20.csv")
        self._write_merged_csv(merged_dir / "2025-01-05_2025-01-20.csv")
        full_processor.build_yoy_reports()
        ready_file = list((tmp_path / "ready").glob("ready_*.csv"))[0]
        cols = list(pd.read_csv(ready_file).columns)
        assert cols.index("Impressions (2025)") < cols.index("Impressions (2024)")

    def test_non_consecutive_years_produce_no_output(self, full_processor, tmp_path):
        """Files 2 years apart (2023 and 2025) are not paired."""
        merged_dir = tmp_path / "merged"
        merged_dir.mkdir()
        self._write_merged_csv(merged_dir / "2023-01-05_2023-01-20.csv")
        self._write_merged_csv(merged_dir / "2025-01-05_2025-01-20.csv")
        full_processor.build_yoy_reports()
        ready_files = list((tmp_path / "ready").glob("ready_*.csv"))
        assert len(ready_files) == 0

    def test_yoy_columns_interleaved_by_metric(self, full_processor, tmp_path):
        """Ready report has key columns, then each metric's years side-by-side (newer first)."""
        import pandas as pd
        merged_dir = tmp_path / "merged"
        merged_dir.mkdir()
        self._write_merged_csv(merged_dir / "2024-01-05_2024-01-20.csv")
        self._write_merged_csv(merged_dir / "2025-01-05_2025-01-20.csv")
        full_processor.build_yoy_reports()
        ready_file = list((tmp_path / "ready").glob("ready_*.csv"))[0]
        assert list(pd.read_csv(ready_file).columns) == _interleaved("2025", "2024")
