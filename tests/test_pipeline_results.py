"""Tests for pipeline_results: per-platform status, card/summary text, ErrorCapture."""
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline_results import FAILED, OK, WARNING, ErrorCapture, PipelineReport, PlatformResult, RangeResult

CUR = ("current", date(2026, 9, 1), date(2026, 9, 30))
PRIOR = ("prior year", date(2025, 9, 1), date(2025, 9, 30))


def _platform(name, *ranges, **kw):
    p = PlatformResult(name, **kw)
    for (label, start, end), status, *detail in ranges:
        p.ranges.append(RangeResult(label, start, end, status, detail[0] if detail else ""))
    return p


class TestPlatformResult:
    def test_all_saved_is_ok(self):
        p = _platform("Meta Ads", (CUR, "saved"), (PRIOR, "saved"))
        assert p.status == OK
        assert p.card_text() == "✓ Saved 2 ranges"

    def test_prior_year_no_data_is_warning(self):
        p = _platform("Reddit Ads", (CUR, "saved"), (PRIOR, "no_data"))
        assert p.status == WARNING
        assert p.card_text() == "No data for prior year (Sep 2025)"
        assert p.summary_note() == "no prior year data"

    def test_failed_range_beats_no_data(self):
        p = _platform("Google Ads", (CUR, "failed", "Google Ads API error: UNAUTHENTICATED"), (PRIOR, "no_data"))
        assert p.status == FAILED
        assert p.card_text() == "Failed (current): Google Ads API error: UNAUTHENTICATED"

    def test_platform_error_and_token_expiry(self):
        assert _platform("TikTok Ads", error="timed out after 3600s").card_text() == "Failed: timed out after 3600s"
        expired = _platform("Microsoft Ads", error="token expired", token_expired=True)
        assert expired.status == FAILED
        assert "Re-authenticate" in expired.card_text()

    def test_skipped_is_warning(self):
        p = _platform("Microsoft Ads", skipped_reason="microsoft-ads.yaml missing")
        assert p.status == WARNING
        assert p.card_text() == "Skipped: microsoft-ads.yaml missing"

    def test_long_error_is_truncated_to_first_line(self):
        p = _platform("Google Ads", error="x" * 200 + "\nsecond line")
        assert len(p.card_text()) < 90 and "second" not in p.card_text()


class TestPipelineReport:
    def test_all_ok_summary(self):
        r = PipelineReport(yoy_expected=True, ready_files=["ready_a.csv"])
        r.platforms["Meta Ads"] = _platform("Meta Ads", (CUR, "saved"), (PRIOR, "saved"))
        assert r.summary() == (OK, "Completed: 1 platform, 1 YoY report")

    def test_failure_summary_names_platforms(self):
        r = PipelineReport()
        r.platforms["Google Ads"] = _platform("Google Ads", error="boom")
        r.platforms["Meta Ads"] = _platform("Meta Ads", (CUR, "saved"))
        assert r.summary() == (FAILED, "Completed with 1 failure: Google Ads")

    def test_warning_summary_includes_missing_yoy(self):
        r = PipelineReport(yoy_expected=True)
        r.platforms["Reddit Ads"] = _platform("Reddit Ads", (CUR, "saved"), (PRIOR, "no_data"))
        level, text = r.summary()
        assert level == WARNING
        assert text == "Completed with warnings: Reddit Ads (no prior year data); no YoY report built"

    def test_processing_error_wins(self):
        r = PipelineReport(processing_error="merge failed\ntraceback")
        r.platforms["Meta Ads"] = _platform("Meta Ads", (CUR, "saved"))
        assert r.summary() == (FAILED, "Processing failed: merge failed")
        assert r.level == FAILED

    def test_platform_accessor_creates_once(self):
        r = PipelineReport()
        assert r.platform("Google Ads") is r.platform("Google Ads")


class TestErrorCapture:
    def test_errors_since_mark(self):
        logger = logging.getLogger("test.pipeline_results.capture")
        capture = ErrorCapture()
        logger.addHandler(capture)
        try:
            logger.error("before")
            mark = capture.mark()
            logger.warning("just a warning")
            logger.info("info")
            assert capture.first_error_since(mark) is None
            logger.error("Google Ads API error: %s", "UNAUTHENTICATED")
            assert capture.errors_since(mark) == ["Google Ads API error: UNAUTHENTICATED"]
            assert capture.first_error_since(mark) == "Google Ads API error: UNAUTHENTICATED"
        finally:
            logger.removeHandler(capture)
