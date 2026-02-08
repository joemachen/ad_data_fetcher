"""
Microsoft Ads API Report Fetcher
Loads config from microsoft-ads.yaml, fetches campaign-level data via Bing Ads Reporting API,
saves to raw_reports/microsoft/{month}_{year}.csv. Columns match processor PLATFORM_CONFIG['microsoft'].
"""

import logging
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import pandas as pd
import yaml

_APP_DIR = Path(__file__).resolve().parent

# Optional bingads imports; report logic runs only when SDK is available
try:
    from bingads.authorization import (
        AuthorizationData,
        OAuthDesktopMobileAuthCodeGrant,
    )
    from bingads.v13.reporting.reporting_service_manager import ReportingServiceManager
    from bingads.v13.reporting.reporting_download_parameters import ReportingDownloadParameters
    _BINGADS_AVAILABLE = True
except ImportError:
    ReportingServiceManager = None
    ReportingDownloadParameters = None
    _BINGADS_AVAILABLE = False

# Column names our processor expects for Microsoft (processor.PLATFORM_CONFIG['microsoft'])
OUTPUT_COLUMNS = ["Campaign", "Impressions", "Clicks", "Spend", "AllConversions", "AllRevenue"]


class MicrosoftAdsFetcher:
    """Fetches Microsoft Ads reports via Bing Ads Reporting API."""

    def __init__(
        self,
        customer_id: str,
        output_dir: str = "raw_reports/microsoft",
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[object] = None,
    ):
        self.customer_id = customer_id.strip().replace("-", "").replace(" ", "")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        self.logger = logging.getLogger(__name__)
        if not _BINGADS_AVAILABLE:
            raise RuntimeError(
                "bingads package is required for Microsoft Ads. Install with: pip install bingads"
            )
        self._load_config()
        self._authorization_data: Optional[AuthorizationData] = None
        self._ensure_auth()

    def _load_config(self) -> None:
        """Load microsoft-ads.yaml (client_id, refresh_token, developer_token)."""
        yaml_path = _APP_DIR / "microsoft-ads.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError("microsoft-ads.yaml not found. Run setup_ms_auth.py first.")
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        self.logger.info("Microsoft Ads config loaded")

    def _update_status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        self.logger.info(f"Status: {message}")

    def _ensure_auth(self) -> None:
        """Build AuthorizationData from config; refresh access token from refresh_token."""
        client_id = (self.config.get("client_id") or "").strip()
        refresh_token = (self.config.get("refresh_token") or "").strip()
        developer_token = (self.config.get("developer_token") or "").strip()
        if not client_id or not refresh_token:
            raise ValueError(
                "microsoft-ads.yaml must contain client_id and refresh_token. Run setup_ms_auth.py and add refresh_token."
            )
        auth = OAuthDesktopMobileAuthCodeGrant(
            client_id=client_id,
            env="production",
            oauth_scope="msads.manage",
        )
        try:
            tokens = auth.request_oauth_tokens_by_refresh_token(refresh_token)
        except Exception as e:
            self.logger.error(f"Failed to refresh Microsoft Ads token: {e}", exc_info=True)
            raise RuntimeError(
                "Could not get access token from refresh_token. Re-run setup_ms_auth.py to get a new refresh token."
            ) from e
        if not tokens or not getattr(tokens, "access_token", None):
            raise RuntimeError("No access_token in response. Re-run setup_ms_auth.py.")
        auth.oauth_tokens = tokens
        account_id = int(self.customer_id) if self.customer_id.isdigit() else 0
        if account_id <= 0:
            raise ValueError("Microsoft Ads customer_id must be a positive numeric account ID.")
        self._authorization_data = AuthorizationData(
            account_id=account_id,
            customer_id=account_id,
            authentication=auth,
            developer_token=developer_token or None,
        )
        self.logger.info("Microsoft Ads authorization ready")

    def _build_report_request(self, factory, start_date: datetime, end_date: datetime):
        """Build CampaignPerformanceReportRequest for the date range (Summary aggregation)."""
        request = factory.create("CampaignPerformanceReportRequest")
        request.Format = "Csv"
        request.ReportName = "Ads Report Fetcher Campaign Performance"
        request.ReturnOnlyCompleteData = False
        request.Aggregation = "Summary"
        request.ExcludeColumnHeaders = False
        request.ExcludeReportFooter = True
        request.ExcludeReportHeader = True
        scope = factory.create("AccountThroughCampaignReportScope")
        scope.AccountIds = {"long": [int(self.customer_id)]}
        scope.Campaigns = None
        request.Scope = scope
        report_time = factory.create("ReportTime")
        report_time.ReportTimeZone = "PacificTimeUSCanadaTijuana"
        report_time.PredefinedTime = None
        report_time.CustomDateRangeStart = factory.create("Date")
        report_time.CustomDateRangeStart.Day = start_date.day
        report_time.CustomDateRangeStart.Month = start_date.month
        report_time.CustomDateRangeStart.Year = start_date.year
        report_time.CustomDateRangeEnd = factory.create("Date")
        report_time.CustomDateRangeEnd.Day = end_date.day
        report_time.CustomDateRangeEnd.Month = end_date.month
        report_time.CustomDateRangeEnd.Year = end_date.year
        request.Time = report_time
        request.Columns = {"CampaignPerformanceReportColumn": [
            "CampaignName", "Impressions", "Clicks", "Spend", "AllConversions", "AllRevenue"
        ]}
        return request

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch campaign-level data for the date range; return DataFrame with Campaign, Impressions, Clicks, Spend, AllConversions, AllRevenue."""
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        self._update_status(f"Fetching Microsoft Ads {start_str} to {end_str}...")
        try:
            manager = ReportingServiceManager(
                authorization_data=self._authorization_data,
                poll_interval_in_milliseconds=5000,
                environment="production",
            )
            factory = manager.service_client.factory
            request = self._build_report_request(factory, start_date, end_date)
            with tempfile.TemporaryDirectory(prefix="ms_ads_report_") as tmpdir:
                result_dir = str(Path(tmpdir))
                result_name = "report.csv"
                params = ReportingDownloadParameters(
                    report_request=request,
                    result_file_directory=result_dir,
                    result_file_name=result_name,
                    overwrite_result_file=True,
                    timeout_in_milliseconds=300000,
                )
                file_path = manager.download_file(params)
                if not file_path or not Path(file_path).exists():
                    self.logger.warning(f"No report file for {start_str} to {end_str}")
                    return None
                df = pd.read_csv(file_path)
            if df.empty:
                self.logger.warning(f"No rows for {start_str} to {end_str}")
                return None
            # Normalize column names to match processor: CampaignName -> Campaign
            rename = {}
            for c in df.columns:
                c2 = str(c).strip()
                if c2 == "Campaign Name" or c2 == "CampaignName":
                    rename[c] = "Campaign"
                elif c2 in OUTPUT_COLUMNS:
                    rename[c] = c2
            df = df.rename(columns=rename)
            for col in OUTPUT_COLUMNS:
                if col not in df.columns:
                    df[col] = 0 if col != "Campaign" else ""
            df = df[OUTPUT_COLUMNS].copy()
            self.logger.info(f"Fetched {len(df)} campaigns for {start_str} to {end_str}")
            return df
        except Exception as e:
            self.logger.error(f"Microsoft Ads fetch failed: {e}", exc_info=True)
            self._update_status(f"Error: {e}")
            return None

    def fetch_monthly_reports(self, start_date: datetime, end_date: datetime) -> List[Tuple[datetime, bool]]:
        """Fetch reports for each month in range; save to {month}_{year}.csv. 1s delay between months."""
        results = []
        current = datetime(start_date.year, start_date.month, 1)
        end = datetime(end_date.year, end_date.month, 1)
        months = []
        while current <= end:
            months.append(current)
            if current.month == 12:
                current = datetime(current.year + 1, 1, 1)
            else:
                current = datetime(current.year, current.month + 1, 1)
        for idx, month_date in enumerate(months):
            if self.cancel_flag and self.cancel_flag.is_set():
                break
            if idx > 0:
                time.sleep(1)
            month_start = datetime(month_date.year, month_date.month, 1)
            if month_start.month == 12:
                month_end = datetime(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = datetime(month_start.year, month_start.month + 1, 1) - timedelta(days=1)
            df = self.fetch_month_data(month_start, month_end)
            if df is not None and not df.empty:
                fn = f"{month_start.strftime('%b').lower()}_{month_start.year}.csv"
                out = self.output_dir / fn
                df.to_csv(out, index=False)
                self.logger.info(f"Saved report to: {out}")
                results.append((month_date, True))
            else:
                results.append((month_date, False))
            if self.progress_callback:
                self.progress_callback(idx + 1, len(months))
        return results
