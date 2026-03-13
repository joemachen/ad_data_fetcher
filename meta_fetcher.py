"""
Meta Ads API Report Fetcher
Fetches report data using the Meta (Facebook) Ads API.
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
from dateutil.relativedelta import relativedelta
import pandas as pd
import yaml
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adsinsights import AdsInsights
from facebook_business.exceptions import FacebookRequestError

from constants import META_RETENTION_MONTHS

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled


class MetaTokenExpiredError(Exception):
    """Exception raised when Meta access token has expired."""
    pass


class MetaAdsFetcher:
    """Main class for fetching Meta Ads reports via API."""
    
    def __init__(self, ad_account_id: str, output_dir: str = "raw_reports/meta", 
                 status_callback: Optional[Callable[[str], None]] = None,
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 cancel_flag: Optional[object] = None):
        """
        Initialize the Meta Ads fetcher.
        
        Args:
            ad_account_id: Meta Ads Account ID (e.g., act_12345678)
            output_dir: Directory to save downloaded reports (default: raw_reports/meta)
            status_callback: Optional callback function(status_message) to update GUI status
            progress_callback: Optional callback function(completed, total) to update progress
            cancel_flag: Optional threading.Event to check for cancellation
        """
        self.ad_account_id = ad_account_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        
        # Initialize Meta API client once per pipeline run; same client is reused for all months.
        # Re-initializing per month can look suspicious to Meta's security filters.
        
        self.logger = logging.getLogger(__name__)
        
        self._init_api()
    
    def _init_api(self) -> None:
        """Initialize Meta Ads API client from meta-ads.yaml."""
        try:
            yaml_path = _APP_DIR / "meta-ads.yaml"
            if not yaml_path.exists():
                raise FileNotFoundError("meta-ads.yaml not found. Please run setup_meta_auth.py first to create it.")

            with open(yaml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            app_id = config.get("app_id")
            app_secret = config.get("app_secret")
            access_token = config.get("access_token")

            if not app_id or not app_secret:
                raise ValueError("Missing required fields in meta-ads.yaml: app_id, app_secret")

            if not access_token or not str(access_token).strip():
                raise ValueError("Missing or empty access_token in meta-ads.yaml. Set a valid token in Settings.")

            access_token = str(access_token).strip()
            # Reject obviously invalid tokens (e.g. pasted requirements text)
            if "\n" in access_token or "\r" in access_token:
                raise ValueError(
                    "access_token in meta-ads.yaml contains line breaks and appears invalid. "
                    "Set a single-line token in Settings."
                )
            if any(x in access_token for x in ("Goal:", "Requirements:", "Implement ", "Pin the Log")):
                raise ValueError(
                    "access_token in meta-ads.yaml appears to be invalid (wrong content). "
                    "Set a valid Meta access token in Settings."
                )

            # Initialize Facebook Ads API
            FacebookAdsApi.init(app_id, app_secret, access_token)
            self.logger.info("Meta Ads API initialized successfully")
            
        except FileNotFoundError as e:
            self.logger.error(f"{e}")
            self._update_status(f"Error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error initializing Meta Ads API: {e}", exc_info=True)
            self._update_status(f"Error initializing API: {e}")
            raise
    
    def _update_status(self, message: str) -> None:
        """Update status message via callback if provided."""
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Error in status callback: {e}")
        self.logger.info(f"Status: {message}")
    
    def _parse_action_value(self, action_values: list, action_type: str = 'purchase') -> float:
        """
        Parse action_values list to find value for specific action_type.
        
        Args:
            action_values: List of dicts with 'action_type' and 'value' keys
            action_type: Type of action to find (default: 'purchase')
        
        Returns:
            Value as float, or 0.0 if not found
        """
        if not action_values:
            return 0.0
        
        for item in action_values:
            if isinstance(item, dict) and item.get('action_type') == action_type:
                value = item.get('value', '0')
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return 0.0
        
        return 0.0
    
    def _parse_action_count(self, actions: list, action_type: str = 'purchase') -> int:
        """
        Parse actions list to find count for specific action_type.
        
        Args:
            actions: List of dicts with 'action_type' and 'value' keys
            action_type: Type of action to find (default: 'purchase')
        
        Returns:
            Count as int, or 0 if not found
        """
        if not actions:
            return 0
        
        for item in actions:
            if isinstance(item, dict) and item.get('action_type') == action_type:
                value = item.get('value', '0')
                try:
                    return int(float(value))  # Handle string numbers
                except (ValueError, TypeError):
                    return 0
        
        return 0
    
    def _get_facebook_error_code(self, e: FacebookRequestError) -> Optional[int]:
        """Extract error code from FacebookRequestError. Returns None if unavailable."""
        try:
            code = e.api_error_code()
            return int(code) if code is not None else None
        except (AttributeError, TypeError, ValueError):
            pass
        try:
            body = getattr(e, "body", None) or getattr(e, "_body", None)
            if isinstance(body, dict):
                err = body.get("error") or body
                code = err.get("code") if isinstance(err, dict) else None
                return int(code) if code is not None else None
        except (TypeError, ValueError, KeyError):
            pass
        return None

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Fetch Meta Ads insights for a date range.
        Only raises MetaTokenExpiredError when error code is 190.
        On error code 17 (rate limit) or 1 (API unknown), pauses 5 seconds and retries.
        """
        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')
        max_retries_rate_limit = 3  # Max retries for rate limit / API unknown

        for attempt in range(max_retries_rate_limit + 1):
            if self.cancel_flag and self.cancel_flag.is_set():
                return None
            try:
                self._update_status(f"Fetching Meta Ads data for {start_str} to {end_str}...")
                account = AdAccount(self.ad_account_id)
                fields = [
                    AdsInsights.Field.campaign_name,
                    AdsInsights.Field.impressions,
                    AdsInsights.Field.inline_link_clicks,
                    AdsInsights.Field.spend,
                    AdsInsights.Field.action_values,
                    AdsInsights.Field.actions
                ]
                params = {
                    'time_range': {'since': start_str, 'until': end_str},
                    'level': 'campaign',
                    'fields': fields
                }
                insights = account.get_insights(params=params)
                rows = []
                for insight in insights:
                    campaign_name = insight.get(AdsInsights.Field.campaign_name, '')
                    impressions = int(insight.get(AdsInsights.Field.impressions, 0) or 0)
                    link_clicks = int(insight.get(AdsInsights.Field.inline_link_clicks, 0) or 0)
                    spend = float(insight.get(AdsInsights.Field.spend, 0) or 0)
                    action_values = insight.get(AdsInsights.Field.action_values, [])
                    purchase_value = self._parse_action_value(action_values, 'purchase')
                    actions = insight.get(AdsInsights.Field.actions, [])
                    purchase_count = self._parse_action_count(actions, 'purchase')
                    rows.append({
                        'Campaign name': campaign_name,
                        'Impressions': impressions,
                        'Link clicks': link_clicks,
                        'Amount spent': spend,
                        'Purchases conversion value': purchase_value,
                        'Results': purchase_count
                    })
                if not rows:
                    self.logger.warning(f"No data returned for {start_str} to {end_str}")
                    return None
                df = pd.DataFrame(rows)
                self.logger.info(f"Fetched {len(df)} campaigns for {start_str} to {end_str}")
                return df
            except FacebookRequestError as e:
                error_code = self._get_facebook_error_code(e)
                # Only raise MetaTokenExpiredError for OAuth/token expiry (code 190)
                if error_code == 190:
                    self.logger.error("Meta access token has expired (error 190)")
                    self._update_status("Meta access token has expired")
                    raise MetaTokenExpiredError("Meta access token has expired. Please provide a new token.")
                # Rate limit (17) or API unknown (1): pause 5s and retry
                if error_code in (17, 1):
                    if attempt < max_retries_rate_limit:
                        self.logger.warning(
                            f"Meta API error {error_code} (rate limit or unknown). Pausing 5s and retrying ({attempt + 1}/{max_retries_rate_limit})..."
                        )
                        self._update_status(f"Rate limit/API delay (code {error_code}). Pausing 5s, retrying...")
                        time.sleep(5)
                        continue
                    self.logger.error(f"Meta API error {error_code} after {max_retries_rate_limit} retries")
                    self._update_status(f"Error: Meta API error {error_code} after retries")
                    return None
                error_msg = f"Meta Ads API error: {e}"
                self.logger.error(error_msg, exc_info=True)
                self._update_status(f"Error: {error_msg}")
                return None
            except Exception as e:
                error_msg = f"Failed to fetch data: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                self._update_status(f"Error: {error_msg}")
                return None
        return None
