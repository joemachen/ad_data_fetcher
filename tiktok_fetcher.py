"""
TikTok Ads API Report Fetcher (skeleton).
Loads config from tiktok-ads.yaml, fetches campaign-level data, saves to {month}_{year}.csv.
Implement API calls using TikTok Marketing API.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import pandas as pd
import yaml

_APP_DIR = Path(__file__).resolve().parent


class TikTokAdsFetcher:
    """Skeleton for fetching TikTok Ads reports via API."""

    def __init__(
        self,
        advertiser_id: str,
        output_dir: str = "raw_reports/tiktok",
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[object] = None,
    ):
        self.advertiser_id = advertiser_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        self.logger = logging.getLogger(__name__)
        self._load_config()

    def _load_config(self) -> None:
        """Load tiktok-ads.yaml (access_token, app_id, etc.)."""
        yaml_path = _APP_DIR / "tiktok-ads.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError("tiktok-ads.yaml not found. Add your TikTok Ads API credentials.")
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        self.logger.info("TikTok Ads config loaded")

    def _update_status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        self.logger.info(f"Status: {message}")

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch campaign-level data. Stub: implement with TikTok Marketing API."""
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        self.logger.info(f"Fetching TikTok Ads data for {start_str} to {end_str} (stub)")
        self._update_status(f"Fetching {start_str} to {end_str}...")
        # TODO: Call TikTok API; return DataFrame with campaign_name, stat_cost, conversion, show_rev, etc.
        return None

    def fetch_monthly_reports(self, start_date: datetime, end_date: datetime) -> List[Tuple[datetime, bool]]:
        """Fetch reports for each month; save to {month}_{year}.csv."""
        results = []
        current = datetime(start_date.year, start_date.month, 1)
        end = datetime(end_date.year, end_date.month, 1)
        months = []
        while current <= end:
            months.append(current)
            current = datetime(current.year + (1 if current.month == 12 else 0), (current.month % 12) + 1, 1)
        for idx, month_date in enumerate(months):
            if self.cancel_flag and self.cancel_flag.is_set():
                break
            month_start = datetime(month_date.year, month_date.month, 1)
            month_end = month_start + timedelta(days=32)
            month_end = month_end.replace(day=1) - timedelta(days=1)
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
