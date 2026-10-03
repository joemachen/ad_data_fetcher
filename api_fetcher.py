"""
Google Ads API Report Fetcher
Fetches report data using the Google Ads API instead of browser automation.
"""

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import grpc
import pandas as pd
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import exceptions as api_exceptions

from utils import retry_call

# gRPC statuses worth retrying: throttling, server overload/timeouts, internal errors
_TRANSIENT_GRPC_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.RESOURCE_EXHAUSTED,
    grpc.StatusCode.INTERNAL,
}
_TRANSIENT_API_CORE_ERRORS = (
    api_exceptions.ServiceUnavailable,
    api_exceptions.DeadlineExceeded,
    api_exceptions.ResourceExhausted,
    api_exceptions.InternalServerError,
)


def _is_transient(exc: BaseException) -> bool:
    """True for errors a retry can fix (rate limits, 5xx/timeouts); False for bad queries, auth, etc."""
    if isinstance(exc, GoogleAdsException):
        try:
            return exc.error.code() in _TRANSIENT_GRPC_CODES
        except Exception:
            return False
    return isinstance(exc, _TRANSIENT_API_CORE_ERRORS)


class AdsApiFetcher:
    """Main class for fetching Google Ads reports via API."""

    def __init__(
        self,
        customer_id: str,
        output_dir: str = "raw_reports/google",
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[object] = None,
    ):
        """
        Initialize the API fetcher.

        Args:
            customer_id: Google Ads customer ID (10-digit number as string)
            output_dir: Directory to save downloaded reports (default: raw_reports/google)
            status_callback: Optional callback function(status_message) to update GUI status
            progress_callback: Optional callback function(completed, total) to update progress
            cancel_flag: Optional threading.Event to check for cancellation
        """
        self.customer_id = customer_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag

        self.logger = logging.getLogger(__name__)

        # Initialize Google Ads client
        self.client: Optional[GoogleAdsClient] = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize Google Ads API client from google-ads.yaml (in app directory)."""
        try:
            _app_dir = Path(__file__).resolve().parent
            yaml_path = _app_dir / "google-ads.yaml"
            if not yaml_path.exists():
                raise FileNotFoundError("google-ads.yaml not found. Please run setup_auth.py first to create it.")

            self.client = GoogleAdsClient.load_from_storage(str(yaml_path))
            self.logger.info("Google Ads API client initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize Google Ads API client: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            raise RuntimeError(error_msg) from e

    def _log_retry(self, attempt: int, delay: float, exc: BaseException) -> None:
        code = exc.error.code().name if isinstance(exc, GoogleAdsException) else type(exc).__name__
        request_id = getattr(exc, "request_id", None)
        self.logger.warning(
            f"Google Ads API transient error {code} (attempt {attempt}), retrying in {delay:.1f}s"
            + (f" [request_id={request_id}]" if request_id else "")
        )

    def _update_status(self, message: str) -> None:
        """Update status message via callback if provided."""
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Error in status callback: {e}")
        self.logger.info(f"Status: {message}")

    def _micros_to_currency(self, micros: int) -> float:
        """Convert cost_micros to standard currency (divide by 1,000,000)."""
        return micros / 1_000_000.0

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        Fetch report data for a specific date range.

        Args:
            start_date: Start date for the report
            end_date: End date for the report

        Returns:
            DataFrame with report data or None if failed
        """
        try:
            # Format dates for GAQL query (YYYY-MM-DD)
            start_str = start_date.strftime("%Y-%m-%d")
            end_str = end_date.strftime("%Y-%m-%d")

            self.logger.info(f"Fetching data for {start_str} to {end_str}")

            # GAQL query - segments.date must be in SELECT when using it in WHERE
            query = f"""
                SELECT
                    campaign.name,
                    segments.date,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.cost_micros,
                    metrics.all_conversions_value,
                    metrics.conversions
                FROM campaign
                WHERE segments.date BETWEEN '{start_str}' AND '{end_str}'
                ORDER BY segments.date, campaign.name
            """

            # Execute query (all pages) with retries for transient errors only
            ga_service = self.client.get_service("GoogleAdsService")
            response = retry_call(
                lambda: list(ga_service.search(customer_id=self.customer_id, query=query)),
                is_retryable=_is_transient,
                on_retry=self._log_retry,
                cancel_event=self.cancel_flag if isinstance(self.cancel_flag, threading.Event) else None,
            )

            # Collect data
            rows = []
            for row in response:
                rows.append(
                    {
                        'date': row.segments.date,
                        'campaign_name': row.campaign.name,
                        'impressions': row.metrics.impressions,
                        'clicks': row.metrics.clicks,
                        'cost': self._micros_to_currency(row.metrics.cost_micros),
                        'all_conversions_value': row.metrics.all_conversions_value,
                        'conversions': row.metrics.conversions,
                    }
                )

            if not rows:
                self.logger.warning(f"No data found for {start_str} to {end_str}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(rows)

            # Aggregate by campaign (sum across all dates in the range)
            df_aggregated = (
                df.groupby('campaign_name')
                .agg(
                    {
                        'impressions': 'sum',
                        'clicks': 'sum',
                        'cost': 'sum',
                        'all_conversions_value': 'sum',
                        'conversions': 'sum',
                    }
                )
                .reset_index()
            )

            # Add date range info
            df_aggregated.insert(0, 'start_date', start_str)
            df_aggregated.insert(1, 'end_date', end_str)

            self.logger.info(f"Fetched {len(df_aggregated)} campaigns for {start_str} to {end_str}")
            return df_aggregated

        except GoogleAdsException as e:
            error_code = e.error.code().name if hasattr(e.error, 'code') else "UNKNOWN"
            error_msg = f"Google Ads API error: {error_code} [request_id={getattr(e, 'request_id', None)}]"

            # Special handling for permission errors
            if "USER_PERMISSION_DENIED" in error_code or "PERMISSION_DENIED" in error_code:
                error_msg += "\nCheck if your MCC ID is set correctly as login_customer_id in google-ads.yaml"
                error_msg += "\nIf using a Manager Account (MCC), run update_mcc_id.py to set it."

            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            return None
        except Exception as e:
            error_msg = f"Failed to fetch data: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            return None
