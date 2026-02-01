"""
Google Ads API Report Fetcher
Fetches report data using the Google Ads API instead of browser automation.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import pandas as pd
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException


class AdsApiFetcher:
    """Main class for fetching Google Ads reports via API."""
    
    def __init__(self, customer_id: str, output_dir: str = "raw_reports/google", status_callback: Optional[Callable[[str], None]] = None, progress_callback: Optional[Callable[[int, int], None]] = None, cancel_flag: Optional[object] = None):
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
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %I:%M:%S %p',
            handlers=[
                logging.FileHandler('app_debug.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize Google Ads client
        self.client: Optional[GoogleAdsClient] = None
        self._init_client()
    
    def _init_client(self) -> None:
        """Initialize Google Ads API client from google-ads.yaml."""
        try:
            yaml_path = Path("google-ads.yaml")
            if not yaml_path.exists():
                raise FileNotFoundError(
                    "google-ads.yaml not found. Please run setup_auth.py first to create it."
                )
            
            self.client = GoogleAdsClient.load_from_storage(str(yaml_path))
            self.logger.info("Google Ads API client initialized successfully")
        except Exception as e:
            error_msg = f"Failed to initialize Google Ads API client: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            raise RuntimeError(error_msg) from e
    
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
            
            # Execute query
            ga_service = self.client.get_service("GoogleAdsService")
            response = ga_service.search(customer_id=self.customer_id, query=query)
            
            # Collect data
            rows = []
            for row in response:
                rows.append({
                    'date': row.segments.date,
                    'campaign_name': row.campaign.name,
                    'impressions': row.metrics.impressions,
                    'clicks': row.metrics.clicks,
                    'cost': self._micros_to_currency(row.metrics.cost_micros),
                    'all_conversions_value': row.metrics.all_conversions_value,
                    'conversions': row.metrics.conversions
                })
            
            if not rows:
                self.logger.warning(f"No data found for {start_str} to {end_str}")
                return None
            
            # Convert to DataFrame
            df = pd.DataFrame(rows)
            
            # Aggregate by campaign (sum across all dates in the range)
            df_aggregated = df.groupby('campaign_name').agg({
                'impressions': 'sum',
                'clicks': 'sum',
                'cost': 'sum',
                'all_conversions_value': 'sum',
                'conversions': 'sum'
            }).reset_index()
            
            # Add date range info
            df_aggregated.insert(0, 'start_date', start_str)
            df_aggregated.insert(1, 'end_date', end_str)
            
            self.logger.info(f"Fetched {len(df_aggregated)} campaigns for {start_str} to {end_str}")
            return df_aggregated
            
        except GoogleAdsException as e:
            error_code = e.error.code().name if hasattr(e.error, 'code') else "UNKNOWN"
            error_msg = f"Google Ads API error: {error_code}"
            
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
    
    def fetch_monthly_reports(self, start_date: datetime, end_date: datetime) -> List[Tuple[datetime, bool]]:
        """
        Fetch reports for each month in the date range.
        
        Args:
            start_date: Start date of the range
            end_date: End date of the range
        
        Returns:
            List of tuples (month_date, success_status)
        """
        results = []
        
        try:
            # Generate list of months to process
            current = datetime(start_date.year, start_date.month, 1)
            end = datetime(end_date.year, end_date.month, 1)
            
            months_to_process = []
            while current <= end:
                months_to_process.append(current)
                # Move to next month
                if current.month == 12:
                    current = datetime(current.year + 1, 1, 1)
                else:
                    current = datetime(current.year, current.month + 1, 1)
            
            self._update_status(f"Processing {len(months_to_process)} month(s)...")
            
            # Process each month
            for idx, month_date in enumerate(months_to_process):
                # Check for cancellation
                if self.cancel_flag and self.cancel_flag.is_set():
                    self.logger.info("Processing cancelled by user")
                    self._update_status("Cancelled by user")
                    break
                
                try:
                    # Calculate month start and end
                    month_start = datetime(month_date.year, month_date.month, 1)
                    if month_date.month == 12:
                        month_end = datetime(month_date.year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(month_date.year, month_date.month + 1, 1) - timedelta(days=1)
                    
                    month_str = month_start.strftime('%B %Y')
                    self.logger.info(f"Processing month: {month_str}")
                    self._update_status(f"Fetching {month_str}...")
                    
                    # Fetch data for this month
                    df = self.fetch_month_data(month_start, month_end)
                    
                    if df is not None and not df.empty:
                        # Generate output filename (format: jan_2025.csv, feb_2025.csv, etc.)
                        month_abbr = month_start.strftime('%b').lower()  # jan, feb, mar, etc.
                        output_filename = f"{month_abbr}_{month_start.year}.csv"
                        output_path = self.output_dir / output_filename
                        
                        # Save to CSV
                        df.to_csv(output_path, index=False)
                        self.logger.info(f"Saved report to: {output_path}")
                        results.append((month_date, True))
                    else:
                        self.logger.warning(f"No data for {month_str}")
                        results.append((month_date, False))
                    
                    # Update progress
                    if self.progress_callback:
                        self.progress_callback(idx + 1, len(months_to_process))
                    
                except Exception as e:
                    self.logger.error(f"Error processing month {month_date.strftime('%B %Y')}: {e}", exc_info=True)
                    results.append((month_date, False))
            
            return results
            
        except Exception as e:
            self.logger.error(f"Fatal error in fetch_monthly_reports: {e}", exc_info=True)
            return results
