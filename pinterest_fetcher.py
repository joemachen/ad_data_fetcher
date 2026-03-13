"""
Pinterest Ads API Report Fetcher (skeleton).
Loads config from pinterest-ads.yaml, fetches campaign-level data, saves to {month}_{year}.csv.
Processor expects spend_in_micro_dollar (divided by 1,000,000) → Cost, total_conversions → Conversions.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import pandas as pd
import yaml

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled


class PinterestAdsFetcher:
    """Skeleton for fetching Pinterest Ads reports via API."""

    def __init__(
        self,
        advertiser_id: str,
        output_dir: str = "raw_reports/pinterest",
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
        """Load pinterest-ads.yaml (access_token, app_id, etc.)."""
        yaml_path = _APP_DIR / "pinterest-ads.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError("pinterest-ads.yaml not found. Add your Pinterest Ads API credentials.")
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        self.logger.info("Pinterest Ads config loaded")

    def _update_status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        self.logger.info(f"Status: {message}")

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Fetch campaign-level data. Stub: implement with Pinterest Marketing API."""
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        self.logger.warning(
            "Pinterest Ads fetch_month_data is not yet implemented; returning None for %s to %s. "
            "Implement the Pinterest Marketing API call and remove this warning.",
            start_str, end_str,
        )
        self._update_status("Pinterest Ads: not yet implemented, skipping.")
        # TODO: Call Pinterest API; return DataFrame with campaign_name, spend_in_micro_dollar, total_conversions
        return None
