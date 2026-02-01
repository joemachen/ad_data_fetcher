"""
Google Ads Report Fetcher - Automation Logic
Handles Playwright-based browser automation for downloading reports.
"""

import logging
import threading
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable
import pandas as pd
from playwright.sync_api import sync_playwright, Page, BrowserContext


class AdsReportFetcher:
    """Main class for automating Google Ads report downloads."""
    
    def __init__(self, report_url: str, output_dir: str = "reports", status_callback: Optional[Callable[[str], None]] = None, progress_callback: Optional[Callable[[int, int], None]] = None, cancel_flag: Optional[threading.Event] = None):
        """
        Initialize the fetcher.
        
        Args:
            report_url: URL to the Google Ads report
            output_dir: Directory to save downloaded reports
            status_callback: Optional callback function(status_message) to update GUI status
            progress_callback: Optional callback function(completed, total) to update progress
            cancel_flag: Optional threading.Event to check for cancellation
        """
        self.report_url = report_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
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
    
    def _update_status(self, message: str) -> None:
        """Update status message via callback if provided."""
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Error in status callback: {e}")
        self.logger.info(f"Status: {message}")
    
    def _setup_browser(self) -> None:
        """Initialize Playwright browser with persistent context using real Chrome."""
        try:
            self._update_status("Launching Browser...")
            self.logger.info("Starting Playwright...")
            
            # Note: Playwright operations are blocking, so timeout handling is limited
            # If this hangs, it may be downloading browser binaries (run: playwright install)
            try:
                self.playwright = sync_playwright().start()
                self.logger.info("Playwright started")
                
                self._update_status("Starting Chrome browser (stealth mode)...")
                
                # Setup user data directory for persistent context
                user_data_dir = Path("user_data")
                user_data_dir.mkdir(exist_ok=True)
                
                # Setup download directory
                download_path = Path("downloads")
                download_path.mkdir(exist_ok=True)
                self.download_path = download_path
                
                # Launch persistent context with real Chrome and stealth mode
                # Using channel="chrome" to use actual Google Chrome installation
                # Using launch_persistent_context for session persistence (cookies saved automatically)
                # NOT incognito by default - session will persist
                self.context = self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    channel="chrome",  # Use real Chrome instead of Chromium
                    headless=False,  # Visible mode for debugging
                    args=[
                        '--disable-blink-features=AutomationControlled'  # Hide automation flags
                    ],
                    accept_downloads=True
                )
                self.logger.info("Chrome browser launched with persistent context")
                
                # Get the first page (persistent context automatically creates one)
                pages = self.context.pages
                if pages:
                    self.page = pages[0]
                else:
                    self.page = self.context.new_page()
                
                self.logger.info("Browser initialized successfully")
                self._update_status("Browser ready")
            except Exception as e:
                error_msg = f"Failed to launch browser: {str(e)}. Ensure Google Chrome is installed on your system."
                self.logger.error(error_msg, exc_info=True)
                self._update_status(f"Error: {error_msg}")
                raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = f"Failed to setup browser: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            raise
    
    def _cleanup_browser(self) -> None:
        """Close browser and cleanup resources."""
        try:
            # With persistent context, we just close the context (browser closes automatically)
            # Session/cookies are automatically saved to user_data directory
            if self.context:
                self.context.close()
                self.logger.info("Browser context closed (session saved automatically)")
            if hasattr(self, 'playwright'):
                self.playwright.stop()
            self.logger.info("Browser cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}", exc_info=True)
    
    def _wait_for_login(self, timeout: int = 300) -> None:
        """
        Wait for user to complete login (including 2FA).
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        try:
            self._update_status("Waiting for Login...")
            self.logger.info("Waiting for user to complete login...")
            # Wait until we're on a Google Ads page (not on login page)
            self.page.wait_for_url(
                lambda url: "accounts.google.com/signin" not in url and "google.com/accounts" not in url,
                timeout=timeout * 1000
            )
            self.logger.info("Login completed")
            self._update_status("Login complete")
        except Exception as e:
            self.logger.warning(f"Login wait timeout or error: {e}")
            # Continue anyway - user may have already logged in
    
    def _navigate_to_report(self) -> None:
        """Navigate to the report URL."""
        try:
            self._update_status("Navigating to URL...")
            self.logger.info(f"Navigating to report URL: {self.report_url}")
            self.page.goto(self.report_url, wait_until="networkidle", timeout=60000)
            self.page.wait_for_load_state("networkidle")
            self.logger.info("Successfully navigated to report page")
            self._update_status("Navigation complete")
        except Exception as e:
            error_msg = f"Failed to navigate to report: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(f"Error: {error_msg}")
            raise
    
    def _take_debug_screenshot(self, context: str = "error") -> None:
        """Take a debug screenshot when element finding fails."""
        try:
            screenshot_path = Path("debug_error.png")
            self.page.screenshot(path=str(screenshot_path), full_page=True)
            self.logger.warning(f"Debug screenshot saved to {screenshot_path} ({context})")
            self._update_status(f"Debug screenshot saved: {screenshot_path}")
        except Exception as e:
            self.logger.error(f"Failed to take debug screenshot: {e}", exc_info=True)
    
    def _set_date_range(self, start_date: datetime, end_date: datetime) -> None:
        """
        Set the date range in the Google Ads interface using text-based locators.
        
        Args:
            start_date: Start date for the report
            end_date: End date for the report
        """
        try:
            self.logger.info(f"Setting date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            
            # Wait for network to be idle before trying to interact
            self.page.wait_for_load_state("networkidle", timeout=10000)
            
            # Try to find date range picker using text-based locators
            date_picker_clicked = False
            date_picker_methods = [
                lambda: self.page.get_by_label("Date range").click(timeout=10000),
                lambda: self.page.get_by_label("Date", exact=False).click(timeout=10000),
                lambda: self.page.get_by_role("button", name="Date range").click(timeout=10000),
                lambda: self.page.get_by_role("button", name=re.compile("Date", re.I)).click(timeout=10000),
                lambda: self.page.get_by_text("Date range").click(timeout=10000),
            ]
            
            for method in date_picker_methods:
                try:
                    method()
                    date_picker_clicked = True
                    self.logger.info("Date picker button clicked")
                    break
                except Exception as e:
                    self.logger.debug(f"Date picker method failed: {e}")
                    continue
            
            if not date_picker_clicked:
                # Take debug screenshot if we can't find the date picker
                self.logger.warning("Could not find date range picker button")
                self._take_debug_screenshot("date_picker_not_found")
                return
            
            # Wait for date picker dialog to appear
            self.page.wait_for_timeout(1000)
            self.page.wait_for_load_state("networkidle", timeout=5000)
            
            # Try to find and click "Custom" option if available
            try:
                self.page.get_by_text("Custom", exact=True).click(timeout=5000)
                self.page.wait_for_timeout(500)
            except:
                # Custom option might not be needed
                pass
            
            # Try to fill start date using label-based locators
            start_date_filled = False
            start_date_methods = [
                lambda: self.page.get_by_label(re.compile("Start", re.I)).fill(start_date.strftime("%m/%d/%Y")),
                lambda: self.page.get_by_label(re.compile("From", re.I)).fill(start_date.strftime("%m/%d/%Y")),
                lambda: self.page.locator('input[aria-label*="Start" i]').fill(start_date.strftime("%m/%d/%Y")),
                lambda: self.page.locator('input[aria-label*="From" i]').fill(start_date.strftime("%m/%d/%Y")),
            ]
            
            for method in start_date_methods:
                try:
                    method()
                    start_date_filled = True
                    self.logger.info("Start date filled")
                    break
                except:
                    continue
            
            # Try to fill end date using label-based locators
            end_date_filled = False
            end_date_methods = [
                lambda: self.page.get_by_label(re.compile("End", re.I)).fill(end_date.strftime("%m/%d/%Y")),
                lambda: self.page.get_by_label(re.compile("To", re.I)).fill(end_date.strftime("%m/%d/%Y")),
                lambda: self.page.locator('input[aria-label*="End" i]').fill(end_date.strftime("%m/%d/%Y")),
                lambda: self.page.locator('input[aria-label*="To" i]').fill(end_date.strftime("%m/%d/%Y")),
            ]
            
            for method in end_date_methods:
                try:
                    method()
                    end_date_filled = True
                    self.logger.info("End date filled")
                    break
                except:
                    continue
            
            # Try to click Apply/Done button
            apply_clicked = False
            apply_methods = [
                lambda: self.page.get_by_role("button", name="Apply").click(timeout=5000),
                lambda: self.page.get_by_role("button", name="Done").click(timeout=5000),
                lambda: self.page.get_by_text("Apply", exact=True).click(timeout=5000),
                lambda: self.page.get_by_text("Done", exact=True).click(timeout=5000),
            ]
            
            for method in apply_methods:
                try:
                    method()
                    apply_clicked = True
                    self.logger.info("Apply button clicked")
                    break
                except:
                    continue
            
            # Wait for date range to be applied
            self.page.wait_for_load_state("networkidle", timeout=5000)
            self.logger.info("Date range set successfully")
            
        except Exception as e:
            self.logger.warning(f"Could not set date range automatically: {e}")
            self._take_debug_screenshot("date_range_set_error")
            # Don't raise - continue with download attempt
    
    def _trigger_download(self) -> Optional[Path]:
        """
        Trigger the CSV download using text-based locators.
        
        Returns:
            Path to downloaded file or None if download failed
        """
        try:
            self.logger.info("Triggering CSV download...")
            
            # Wait for network to be idle before trying to interact
            self.page.wait_for_load_state("networkidle", timeout=10000)
            
            # Setup download event listener
            download_path = None
            with self.page.expect_download(timeout=60000) as download_info:
                # Try to find download button using text-based locators
                download_clicked = False
                download_methods = [
                    lambda: self.page.get_by_role("button", name="Download", exact=True).click(timeout=10000),
                    lambda: self.page.get_by_text("Download", exact=True).click(timeout=10000),
                    lambda: self.page.get_by_role("button", name="Download").click(timeout=10000),
                    lambda: self.page.get_by_text("Download").click(timeout=10000),
                    lambda: self.page.get_by_role("button", name="Export", exact=True).click(timeout=10000),
                    lambda: self.page.get_by_text("Export", exact=True).click(timeout=10000),
                    lambda: self.page.get_by_role("link", name="Download").click(timeout=10000),
                ]
                
                for method in download_methods:
                    try:
                        method()
                        download_clicked = True
                        self.logger.info("Download button clicked")
                        break
                    except Exception as e:
                        self.logger.debug(f"Download method failed: {e}")
                        continue
                
                if not download_clicked:
                    self.logger.error("Could not find download button after trying all methods")
                    self._take_debug_screenshot("download_button_not_found")
                    return None
                
                # Wait for download to start
                download = download_info.value
                
                # Save the downloaded file
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                download_path = self.download_path / f"download_{timestamp}.csv"
                download.save_as(download_path)
                self.logger.info(f"Download completed: {download_path}")
            
            return download_path
            
        except Exception as e:
            self.logger.error(f"Failed to trigger download: {e}", exc_info=True)
            self._take_debug_screenshot("download_error")
            return None
    
    def _process_csv(self, csv_path: str, output_filename: str, columns_to_drop: Optional[List[str]] = None) -> bool:
        """
        Process the downloaded CSV using pandas.
        
        Args:
            csv_path: Path to the downloaded CSV
            output_filename: Name for the processed output file
            columns_to_drop: List of column names to drop (optional)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            if columns_to_drop is None:
                columns_to_drop = []  # Add specific columns if needed
            
            self.logger.info(f"Processing CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            
            # Drop specified columns if they exist
            if columns_to_drop:
                existing_columns = [col for col in columns_to_drop if col in df.columns]
                if existing_columns:
                    df = df.drop(columns=existing_columns)
                    self.logger.info(f"Dropped columns: {existing_columns}")
            
            # Save processed CSV
            output_path = self.output_dir / output_filename
            df.to_csv(output_path, index=False)
            self.logger.info(f"Saved processed report to: {output_path}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to process CSV: {e}", exc_info=True)
            return False
    
    def fetch_monthly_reports(
        self,
        start_date: datetime,
        end_date: datetime,
        columns_to_drop: Optional[List[str]] = None,
        login_timeout: int = 300
    ) -> List[Tuple[datetime, bool]]:
        """
        Fetch reports for each month in the date range.
        
        Args:
            start_date: Start date of the range
            end_date: End date of the range
            columns_to_drop: List of column names to drop from CSV
            login_timeout: Timeout for login in seconds
        
        Returns:
            List of tuples (month_date, success_status)
        """
        results = []
        
        try:
            self._setup_browser()
            
            # Navigate to report URL first
            self._navigate_to_report()
            
            # Check if we need to login
            if "accounts.google.com" in self.page.url or "signin" in self.page.url.lower():
                self.logger.info("Login required - waiting for user to complete login")
                self._wait_for_login(timeout=login_timeout)
                # Re-navigate after login
                self._navigate_to_report()
            else:
                self._update_status("Already logged in")
            
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
            
            # Process each month
            for month_date in months_to_process:
                try:
                    # Calculate month start and end
                    month_start = datetime(month_date.year, month_date.month, 1)
                    if month_date.month == 12:
                        month_end = datetime(month_date.year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(month_date.year, month_date.month + 1, 1) - timedelta(days=1)
                    
                    month_str = month_start.strftime('%B %Y')
                    self.logger.info(f"Processing month: {month_str}")
                    self._update_status(f"Processing {month_str}...")
                    
                    # Set date range for this month
                    self._set_date_range(month_start, month_end)
                    
                    # Trigger download
                    self._update_status(f"Downloading {month_str}...")
                    downloaded_file = self._trigger_download()
                    
                    if downloaded_file and downloaded_file.exists():
                        # Generate output filename
                        output_filename = f"Report_{month_start.strftime('%b_%Y')}.csv"
                        # Process CSV
                        success = self._process_csv(str(downloaded_file), output_filename, columns_to_drop)
                        # Clean up temporary download
                        try:
                            downloaded_file.unlink()
                        except:
                            pass
                        results.append((month_date, success))
                    else:
                        results.append((month_date, False))
                    
                    # Wait between downloads
                    self.page.wait_for_timeout(2000)
                    
                except Exception as e:
                    self.logger.error(f"Error processing month {month_date.strftime('%B %Y')}: {e}", exc_info=True)
                    results.append((month_date, False))
            
        except Exception as e:
            self.logger.error(f"Fatal error in fetch_monthly_reports: {e}", exc_info=True)
        finally:
            self._cleanup_browser()
        
        return results
