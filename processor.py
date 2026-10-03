"""
Report Processor
Transforms raw platform CSV reports into a standardized schema for the reporting dashboard.
Platform-agnostic: new platforms (TikTok, Reddit, etc.) can be added via PLATFORM_CONFIG.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled

# --- Standardized Schema (platform-agnostic internal format) ---

INTERNAL_SCHEMA = (
    'Month',
    'Year',
    'Platform',
    'Channel',
    'Campaign',
    'Funnel Stage',
    'Impressions',
    'Clicks',
    'Cost',
    'Revenue',
    'Conversions',
)
"""Mandatory columns for all processed files. Missing columns are filled with 0 or Unknown."""

# Default value per schema column: "Unknown" for text, 0 for numeric
SCHEMA_DEFAULTS: Dict[str, Any] = {
    'Month': 'Unknown',
    'Year': 'Unknown',
    'Platform': 'Unknown',
    'Channel': 'Unknown',
    'Campaign': 'Unknown',
    'Funnel Stage': 'Top',
    'Impressions': 0,
    'Clicks': 0,
    'Cost': 0,
    'Revenue': 0,
    'Conversions': 0,
}

# Numeric columns (for validation/fill)
SCHEMA_NUMERIC = {'Impressions', 'Clicks', 'Cost', 'Revenue', 'Conversions'}


# --- Platform configuration: maps platform key -> column mapping + display/channel ---
# Add new platforms here; funnel logic uses mappings.json consistently for all.

PLATFORM_CONFIG: Dict[str, Dict[str, Any]] = {
    'google': {
        'column_mapping': {
            'campaign_name': 'Campaign',
            'impressions': 'Impressions',
            'clicks': 'Clicks',
            'cost': 'Cost',
            'all_conversions_value': 'Revenue',
            'conversions': 'Conversions',
        },
        'display_name': 'Google Ads',
        'channel': 'SEM',
    },
    'meta': {
        'column_mapping': {
            'Campaign name': 'Campaign',
            'Impressions': 'Impressions',
            'Link clicks': 'Clicks',
            'Amount spent': 'Cost',
            'Purchases conversion value': 'Revenue',
            'Results': 'Conversions',
        },
        'display_name': 'Meta Ads',
        'channel': 'Paid Social',
    },
    'microsoft': {
        'column_mapping': {
            'Campaign': 'Campaign',
            'Impressions': 'Impressions',
            'Clicks': 'Clicks',
            'Spend': 'Cost',
            'AllConversions': 'Conversions',
            'AllRevenue': 'Revenue',
        },
        'display_name': 'Microsoft Ads',
        'channel': 'SEM',
    },
    'tiktok': {
        'column_mapping': {
            'campaign_name': 'Campaign',
            'spend': 'Cost',
            'impressions': 'Impressions',
            'clicks': 'Clicks',
            'conversion': 'Conversions',
            'revenue': 'Revenue',
        },
        'display_name': 'TikTok Ads',
        'channel': 'Paid Social',
    },
    'reddit': {
        'column_mapping': {
            'campaign_name': 'Campaign',
            'amount_spent': 'Cost',
            'impressions': 'Impressions',
            'clicks': 'Clicks',
            'conversion_purchase_total_value': 'Revenue',
            'conversions': 'Conversions',
        },
        'display_name': 'Reddit Ads',
        'channel': 'Paid Social',
    },
    'pinterest': {
        'column_mapping': {
            'campaign_name': 'Campaign',
            'spend_in_micro_dollar': 'Cost',
            'total_conversions': 'Conversions',
        },
        'display_name': 'Pinterest Ads',
        'channel': 'Paid Social',
        'column_transforms': {'Cost': 'divide_1e6'},
    },
}


# --- Funnel stage rules (used for all platforms via mappings.json + auto-rules) ---

BOTTOM_FUNNEL_KEYWORDS = ['Brand', 'Branded']

# --- Range-based filename: YYYY-MM-DD_YYYY-MM-DD.csv (same month-day across years pairs for YoY) ---
RANGE_FILENAME_PATTERN = re.compile(r'^(\d{4})-(\d{2})-(\d{2})_(\d{4})-(\d{2})-(\d{2})\.csv$')

# --- Period-suffixed metric columns, e.g. "Impressions (2025)" or "Cost (USD) (2025-01-05_2025-01-20)" ---
# Anchors on the last parenthetical so metric names may themselves contain parentheses.
PERIOD_COLUMN_PATTERN = re.compile(r'^(?P<metric>.*\S)\s*\((?P<period>[^()]+)\)$')


def interleave_period_columns(columns: Sequence[str], periods: Optional[Sequence[str]] = None) -> List[str]:
    """
    Reorder columns so each metric's comparison periods sit side-by-side.

    Columns of the form "<Metric> (<period>)" are grouped by metric (in order of first appearance);
    within each group, periods follow `periods` if given, else order of first appearance.
    All other columns (e.g. Campaign, Platform, Channel, Funnel Stage) lead, in their original order.

    When `periods` is given, only columns whose suffix is one of those periods are treated as
    period columns, so metadata like "Campaign (ID)" is left alone.

    Example: [Campaign, Clicks (2026), Cost (2026), Clicks (2025), Cost (2025)]
          -> [Campaign, Clicks (2026), Clicks (2025), Cost (2026), Cost (2025)]
    """
    period_filter = set(periods) if periods is not None else None
    lead: List[str] = []
    metric_order: List[str] = []
    period_order: List[str] = list(periods) if periods is not None else []
    by_metric: Dict[str, Dict[str, str]] = {}  # metric -> {period: column}

    for col in columns:
        m = PERIOD_COLUMN_PATTERN.match(col)
        if not m or (period_filter is not None and m.group('period') not in period_filter):
            lead.append(col)
            continue
        metric, period = m.group('metric'), m.group('period')
        if metric not in by_metric:
            by_metric[metric] = {}
            metric_order.append(metric)
        if periods is None and period not in period_order:
            period_order.append(period)
        by_metric[metric][period] = col

    ordered = list(lead)
    for metric in metric_order:
        ordered.extend(by_metric[metric][p] for p in period_order if p in by_metric[metric])
    return ordered


class ReportProcessor:
    """Processes raw platform CSV files into standardized INTERNAL_SCHEMA format."""

    def __init__(
        self,
        input_dir: str = "raw_reports",
        output_dir: str = "processed_reports",
        merged_dir: str = "merged_reports",
        ready_dir: str = "ready_reports",
        status_callback: Optional[Callable[[str], None]] = None,
        user_input_callback: Optional[Callable[[str], str]] = None,
    ):
        """
        Initialize the ReportProcessor.

        Args:
            input_dir: Directory containing raw CSV files to process (default: raw_reports)
            output_dir: Directory to save processed files (default: processed_reports)
            merged_dir: Directory for merged CSVs (default: merged_reports)
            ready_dir: Directory for YoY ready reports (default: ready_reports)
            status_callback: Optional callback function(message: str) to report status updates
            user_input_callback: Optional callback function(campaign_name: str) -> str to get user input
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.merged_dir = Path(merged_dir)
        self.ready_dir = Path(ready_dir)
        self.status_callback = status_callback
        self.user_input_callback = user_input_callback

        self.logger = logging.getLogger(__name__)

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Output directory: {self.output_dir.absolute()}")

        # Load campaign mappings (same path as GUI: _APP_DIR / mappings.json)
        self.mappings_file = _APP_DIR / "mappings.json"
        self.campaign_mappings: Dict[str, str] = {}
        self._load_mappings()

    def _update_status(self, message: str) -> None:
        """Update status message via callback if provided."""
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Error in status callback: {e}")
        self.logger.info(f"Status: {message}")

    def _load_mappings(self) -> None:
        """Load campaign mappings from JSON file."""
        try:
            if self.mappings_file.exists():
                with open(self.mappings_file, 'r', encoding='utf-8') as f:
                    self.campaign_mappings = json.load(f)
                self.logger.info(f"Loaded {len(self.campaign_mappings)} campaign mappings from {self.mappings_file}")
            else:
                self.campaign_mappings = {}
                self.logger.info(f"Mappings file {self.mappings_file} not found, starting with empty mappings")
        except json.JSONDecodeError as e:
            self.logger.error(f"mappings.json is corrupted (invalid JSON): {e}", exc_info=True)
            self.campaign_mappings = {}
        except OSError as e:
            self.logger.error(f"Error reading mappings file: {e}", exc_info=True)
            self.campaign_mappings = {}

    def _save_mappings(self) -> None:
        """Save campaign mappings to JSON file."""
        try:
            with open(self.mappings_file, 'w', encoding='utf-8') as f:
                json.dump(self.campaign_mappings, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved {len(self.campaign_mappings)} campaign mappings to {self.mappings_file}")
        except Exception as e:
            self.logger.error(f"Error saving mappings: {e}", exc_info=True)

    def determine_funnel(self, campaign_name: str) -> str:
        """
        Determine funnel stage based on campaign name using memory, auto-rules, or user input.

        Step 1 (Memory): Check if campaign is in mappings.json
        Step 2 (Auto-Rules): Check if "Brand" or "Branded" is in name
        Step 3 (Ask User): If neither, ask user via callback

        Args:
            campaign_name: Name of the campaign

        Returns:
            "Top", "Bottom", "SKIP" (skip this report only, not saved), or "DELETE" (always ignore, saved to mappings)
        """
        if not campaign_name or not isinstance(campaign_name, str):
            return "Top"

        # Step 1: Check memory (mappings.json) — case-insensitive match
        campaign_lower = campaign_name.lower()
        for k, v in self.campaign_mappings.items():
            if k.lower() == campaign_lower:
                return v

        # Step 2: Auto-rules (check for Brand/Branded keywords)
        for keyword in BOTTOM_FUNNEL_KEYWORDS:
            if keyword.lower() in campaign_lower:
                # Auto-assign and save; replace any existing key that matches case-insensitively
                existing = next((key for key in self.campaign_mappings if key.lower() == campaign_lower), None)
                if existing is not None:
                    del self.campaign_mappings[existing]
                self.campaign_mappings[campaign_name] = "Bottom"
                self._save_mappings()
                self.logger.info(f"Auto-classified '{campaign_name}' as Bottom (contains '{keyword}')")
                return "Bottom"

        # Step 3: Ask user (if callback provided)
        if self.user_input_callback:
            try:
                user_choice = self.user_input_callback(campaign_name)
                if user_choice in ["Top", "Bottom", "DELETE"]:
                    # Save to mappings; replace any existing key that matches case-insensitively
                    existing = next((key for key in self.campaign_mappings if key.lower() == campaign_lower), None)
                    if existing is not None:
                        del self.campaign_mappings[existing]
                    self.campaign_mappings[campaign_name] = user_choice
                    self._save_mappings()
                    if user_choice != "DELETE":
                        log_msg = f"User classified '{campaign_name}' as {user_choice}"
                        self._update_status(log_msg)
                        self.logger.info(log_msg)
                    return user_choice
                elif user_choice == "SKIP":
                    # SKIP: Don't save to mappings (user will be asked again next time)
                    self.logger.info(f"User skipped '{campaign_name}' for this report only")
                    return "SKIP"
                else:
                    # Invalid choice, default to Top
                    self.logger.warning(f"Invalid user choice '{user_choice}' for '{campaign_name}', defaulting to Top")
                    return "Top"
            except Exception as e:
                self.logger.error(f"Error getting user input for '{campaign_name}': {e}", exc_info=True)
                return "Top"

        # Fallback: default to Top if no callback
        return "Top"

    def _parse_range_from_filename(self, filename: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse date-range filename of form YYYY-MM-DD_YYYY-MM-DD.csv (e.g. 2025-01-05_2025-01-20.csv).
        Returns (start_str, end_str, range_id) where range_id is MM-DD_MM-DD for YoY pairing; None if no match.
        """
        m = RANGE_FILENAME_PATTERN.match(filename)
        if not m:
            return None
        y1, mo1, d1, y2, mo2, d2 = m.groups()
        start_str = f"{y1}-{mo1}-{d1}"
        end_str = f"{y2}-{mo2}-{d2}"
        range_id = f"{mo1}-{d1}_{mo2}-{d2}"  # same month-day across years
        return (start_str, end_str, range_id)

    def _parse_month_year_from_range_filename(self, filename: str) -> Tuple[str, str]:
        """
        Derive Month and Year from range filename YYYY-MM-DD_YYYY-MM-DD.csv (use start date).
        Returns (Month_str, Year_str) for INTERNAL_SCHEMA; ('Unknown', 'Unknown') if pattern does not match.
        """
        parsed = self._parse_range_from_filename(filename)
        if not parsed:
            return ('Unknown', 'Unknown')
        start_str, _, _ = parsed
        try:
            dt = datetime.strptime(start_str, "%Y-%m-%d")
            month_display = dt.strftime("%B")  # January, February, ...
            year_str = str(dt.year)
            return (month_display, year_str)
        except ValueError:
            return ('Unknown', 'Unknown')

    def _get_platform_config(self, parent_dir_name: str, filename: str) -> Tuple[str, Dict[str, Any]]:
        """
        Resolve platform key and config from parent directory (or filename fallback).
        Returns (platform_key, config). Raises ValueError if platform is unknown.
        """
        platform_key = parent_dir_name.lower()
        if platform_key in PLATFORM_CONFIG:
            return (platform_key, PLATFORM_CONFIG[platform_key])
        # Fallback: filename prefix (e.g. meta_jan_2025.csv)
        if filename.lower().startswith('meta_'):
            platform_key = 'meta'
        else:
            platform_key = 'google'
        if platform_key in PLATFORM_CONFIG:
            return (platform_key, PLATFORM_CONFIG[platform_key])
        raise ValueError(
            f"Unknown platform for directory '{parent_dir_name}' / file '{filename}'. Add to PLATFORM_CONFIG."
        )

    def _validate_and_fill_schema(self, df: pd.DataFrame, filename: str) -> Tuple[pd.DataFrame, List[str]]:
        """
        Ensure df has all INTERNAL_SCHEMA columns before saving. Fill missing with 0 or Unknown.
        Returns (validated_df, list of validation messages for logging).
        """
        messages: List[str] = []
        out = df.copy()

        for col in INTERNAL_SCHEMA:
            if col not in out.columns:
                default = SCHEMA_DEFAULTS.get(col, 0 if col in SCHEMA_NUMERIC else 'Unknown')
                out[col] = default
                messages.append(f"File {filename}: missing column '{col}' filled with {repr(default)}")
                self.logger.warning(messages[-1])
            else:
                # Coerce numeric columns; fill NaN with 0 and log row-level validation
                if col in SCHEMA_NUMERIC:
                    try:
                        numeric = pd.to_numeric(out[col], errors='coerce')
                        filled_count = numeric.isna().sum()
                        if filled_count > 0:
                            msg = (
                                f"File {filename}: {int(filled_count)} row(s) had missing/invalid "
                                f"'{col}', filled with 0"
                            )
                            messages.append(msg)
                            self.logger.warning(msg)
                        out[col] = numeric.fillna(0)
                    except Exception as e:
                        messages.append(f"File {filename}: column '{col}' coercion failed: {e}")
                        self.logger.warning(messages[-1])
                        out[col] = 0
                else:
                    out[col] = out[col].fillna(SCHEMA_DEFAULTS.get(col, 'Unknown')).astype(str)

        # Reorder to INTERNAL_SCHEMA
        out = out[[c for c in INTERNAL_SCHEMA if c in out.columns]]
        return (out, messages)

    def _find_report_files(self) -> List[Path]:
        """
        Find all CSV report files in subdirectories of the input directory.

        Scans raw_reports/{platform}/ for files matching pattern: YYYY-MM-DD_YYYY-MM-DD.csv

        Returns:
            List of Path objects for found CSV files
        """
        report_files = []
        if self.input_dir.exists():
            for platform_dir in self.input_dir.iterdir():
                if platform_dir.is_dir():
                    for file_path in platform_dir.glob("*.csv"):
                        if RANGE_FILENAME_PATTERN.match(file_path.name):
                            report_files.append(file_path)
        report_files.sort()
        return report_files

    def process_file(self, file_path: Path) -> Optional[Path]:
        """
        Process a single CSV file: map platform columns to INTERNAL_SCHEMA, apply funnel logic,
        validate/fill schema, then save to processed_reports/{platform_key}/.

        Args:
            file_path: Path to the raw CSV file to process

        Returns:
            Path to the output file if successful, None if failed
        """
        filename = file_path.name
        try:
            self.logger.info(f"Processing file: {filename}")
            self._update_status(f"Processing {filename}...")

            df = pd.read_csv(file_path)
            parent_dir_name = file_path.parent.name

            # Resolve platform from directory (or filename fallback)
            try:
                platform_key, config = self._get_platform_config(parent_dir_name, filename)
            except ValueError as e:
                self.logger.error(f"File {filename}: {e}")
                self._update_status(str(e))
                return None

            column_mapping = config['column_mapping']
            display_name = config['display_name']
            channel = config['channel']
            column_transforms = config.get('column_transforms') or {}

            # Fill missing raw columns with defaults so mapping does not fail
            for raw_col in column_mapping.keys():
                if raw_col not in df.columns:
                    self.logger.warning(f"File {filename}: missing raw column '{raw_col}', using default")
                    df[raw_col] = '' if 'campaign' in raw_col.lower() or 'name' in raw_col.lower() else 0

            # Map platform columns to internal schema (Campaign, Impressions, etc.)
            processed_df = pd.DataFrame()
            for raw_col, schema_col in column_mapping.items():
                if raw_col in df.columns:
                    processed_df[schema_col] = df[raw_col]
                else:
                    processed_df[schema_col] = SCHEMA_DEFAULTS.get(
                        schema_col, 0 if schema_col in SCHEMA_NUMERIC else ''
                    )

            # Apply optional column transforms (e.g. Pinterest: Cost = spend_in_micro_dollar / 1e6)
            for schema_col, transform_name in column_transforms.items():
                if schema_col in processed_df.columns and transform_name == 'divide_1e6':
                    processed_df[schema_col] = (
                        pd.to_numeric(processed_df[schema_col], errors='coerce').fillna(0) / 1_000_000
                    )

            # Add Month, Year from range filename (start date)
            month_str, year_str = self._parse_month_year_from_range_filename(filename)
            processed_df['Month'] = month_str
            processed_df['Year'] = year_str

            # Add Platform and Channel (platform-agnostic)
            processed_df['Platform'] = display_name
            processed_df['Channel'] = channel

            # Funnel stage: same logic for all platforms (mappings.json + auto-rules + user callback)
            if 'Campaign' in processed_df.columns:
                processed_df['Funnel Stage'] = processed_df['Campaign'].apply(self.determine_funnel)

                before_count = len(processed_df)
                campaigns_to_delete = processed_df[processed_df['Funnel Stage'] == 'DELETE']['Campaign'].tolist()
                campaigns_to_skip = processed_df[processed_df['Funnel Stage'] == 'SKIP']['Campaign'].tolist()
                processed_df = processed_df[~processed_df['Funnel Stage'].isin(['DELETE', 'SKIP'])].copy()
                after_count = len(processed_df)

                for campaign_name in campaigns_to_delete:
                    log_msg = f"Dropping excluded campaign (always ignored): {campaign_name}"
                    self._update_status(log_msg)
                    self.logger.info(log_msg)
                for campaign_name in campaigns_to_skip:
                    log_msg = f"Skipping campaign (this report only): {campaign_name}"
                    self._update_status(log_msg)
                    self.logger.info(log_msg)
                if before_count > after_count:
                    self.logger.info(f"Removed {before_count - after_count} excluded/skipped campaign(s)")
            else:
                processed_df['Funnel Stage'] = SCHEMA_DEFAULTS['Funnel Stage']

            # Validate and fill any missing INTERNAL_SCHEMA columns before save
            processed_df, validation_messages = self._validate_and_fill_schema(processed_df, filename)
            for msg in validation_messages:
                self._update_status(msg)

            # Write to processed_reports/{platform_key}/
            platform_dir = self.output_dir / platform_key
            platform_dir.mkdir(parents=True, exist_ok=True)
            output_path = platform_dir / filename
            processed_df.to_csv(output_path, index=False)

            self.logger.info(f"Saved processed file: {output_path}")
            self._update_status(f"Done: {filename} ({display_name})")
            return output_path

        except Exception as e:
            error_msg = f"Error processing {filename}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(error_msg)
            return None

    def process_all(self) -> Dict[str, bool]:
        """
        Process all report files in the input directory.

        Returns:
            Dictionary mapping filename -> success status (True/False)
        """
        results = {}

        # Find all report files
        report_files = self._find_report_files()

        if not report_files:
            msg = "No report files found to process"
            self.logger.warning(msg)
            self._update_status(msg)
            return results

        self._update_status(f"Found {len(report_files)} file(s) to process")

        # Process each file
        for file_path in report_files:
            output_path = self.process_file(file_path)
            results[file_path.name] = output_path is not None

        # Summary
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        summary_msg = f"Processing complete: {success_count}/{total_count} files processed successfully"
        self._update_status(summary_msg)
        self.logger.info(summary_msg)

        return results

    def merge_platform_data(self) -> None:
        """
        Merge processed data by YYYY-MM-DD_YYYY-MM-DD.csv across all subfolders in processed_reports/.
        Each subfolder (google/, meta/, etc.) is scanned; matching filenames are combined
        and saved to merged_reports/ with INTERNAL_SCHEMA column order and validation.
        """
        try:
            self._update_status("Starting merge of platform data...")
            self.logger.info("Starting merge of platform data")

            self.merged_dir.mkdir(parents=True, exist_ok=True)

            # Collect all unique YYYY-MM-DD_YYYY-MM-DD.csv from any platform subfolder
            filenames = set()
            if self.output_dir.exists():
                for platform_dir in self.output_dir.iterdir():
                    if platform_dir.is_dir():
                        for csv_file in platform_dir.glob("*.csv"):
                            if RANGE_FILENAME_PATTERN.match(csv_file.name):
                                filenames.add(csv_file.name)

            if not filenames:
                self._update_status("No files found to merge")
                self.logger.info("No processed files found for merging")
                return

            merged_count = 0
            for filename in sorted(filenames):
                dfs = []
                row_counts: Dict[str, int] = {}

                for platform_dir in sorted(self.output_dir.iterdir()):
                    if not platform_dir.is_dir():
                        continue
                    platform_key = platform_dir.name
                    candidate = platform_dir / filename
                    if not candidate.exists():
                        continue
                    try:
                        df = pd.read_csv(candidate)
                        dfs.append(df)
                        row_counts[platform_key] = len(df)
                        self.logger.debug(f"Loaded {len(df)} rows from {platform_key}/{filename}")
                    except Exception as e:
                        self.logger.error(f"Error loading {platform_key}/{filename}: {e}")
                        self._update_status(f"Error loading {platform_key}/{filename}")

                if not dfs:
                    self.logger.warning(f"No data found for {filename} in any platform")
                    continue

                try:
                    merged_df = pd.concat(dfs, ignore_index=True)
                    merged_df, validation_messages = self._validate_and_fill_schema(merged_df, f"merged/{filename}")
                    for msg in validation_messages:
                        self.logger.warning(msg)

                    output_path = self.merged_dir / filename
                    merged_df.to_csv(output_path, index=False)
                    merged_count += 1
                    counts_str = ", ".join(f"{k}: {v} rows" for k, v in sorted(row_counts.items()))
                    log_msg = f"Merged {filename}: {counts_str}"
                    self._update_status(log_msg)
                    self.logger.info(log_msg)
                except Exception as e:
                    error_msg = f"Error merging {filename}: {e}"
                    self.logger.error(error_msg, exc_info=True)
                    self._update_status(error_msg)

            summary_msg = f"Merge complete: {merged_count} file(s) merged successfully"
            self._update_status(summary_msg)
            self.logger.info(summary_msg)

        except Exception as e:
            error_msg = f"Error during merge: {e}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(error_msg)

    def build_yoy_reports(self) -> None:
        """
        Build Year-over-Year (YoY) comparison CSVs from merged_reports.

        Pairs merged files by same month-day range (e.g. 2025-01-05_2025-01-20 and 2024-01-05_2024-01-20).
        Produces one ready file per pair: ready_2025-01-05_2025-01-20_vs_2024.csv.

        Column order: Campaign, Platform, Channel, Funnel Stage, then each metric with the
        current year next to the prior year: Impressions (2025), Impressions (2024), Clicks (2025), ...
        """
        try:
            self._update_status("Building YoY reports...")
            self.logger.info("Building YoY reports from %s", self.merged_dir)
            if not self.merged_dir.exists():
                self._update_status("No merged_reports directory")
                self.logger.info("No merged_reports directory; skipping YoY")
                return
            # Group merged filenames by range_id (MM-DD_MM-DD) and year (from first YYYY in filename)
            range_to_files: Dict[str, Dict[int, str]] = {}  # range_id -> {year: filename}
            for csv_path in self.merged_dir.glob("*.csv"):
                parsed = self._parse_range_from_filename(csv_path.name)
                if not parsed:
                    continue
                start_str, end_str, range_id = parsed
                year = int(start_str[:4])
                if range_id not in range_to_files:
                    range_to_files[range_id] = {}
                range_to_files[range_id][year] = csv_path.name
            key_cols = ['Campaign', 'Platform', 'Channel', 'Funnel Stage']
            metric_cols = ['Impressions', 'Clicks', 'Cost', 'Revenue', 'Conversions']
            self.ready_dir.mkdir(parents=True, exist_ok=True)
            built = 0
            for range_id, year_to_filename in range_to_files.items():
                years = sorted(year_to_filename.keys())
                if len(years) < 2:
                    continue
                # Use consecutive year pair: prior = min, current = next year present
                for i in range(len(years) - 1):
                    y1, y2 = years[i], years[i + 1]
                    if y2 - y1 != 1:
                        continue
                    fn1 = self.merged_dir / year_to_filename[y1]
                    fn2 = self.merged_dir / year_to_filename[y2]
                    if not fn1.exists() or not fn2.exists():
                        continue
                    try:
                        df1 = pd.read_csv(fn1)
                        df2 = pd.read_csv(fn2)
                    except Exception as e:
                        self.logger.error(f"Error reading {fn1.name} or {fn2.name}: {e}")
                        continue
                    for col in key_cols + metric_cols:
                        if col not in df1.columns:
                            df1[col] = 0 if col in SCHEMA_NUMERIC else 'Unknown'
                        if col not in df2.columns:
                            df2[col] = 0 if col in SCHEMA_NUMERIC else 'Unknown'
                    df1 = df1[key_cols + metric_cols].copy()
                    df2 = df2[key_cols + metric_cols].copy()
                    df1 = df1.groupby(key_cols, as_index=False)[metric_cols].sum()
                    df2 = df2.groupby(key_cols, as_index=False)[metric_cols].sum()
                    merged = df1.merge(df2, on=key_cols, how='outer', suffixes=(f' ({y1})', f' ({y2})'))
                    for c in merged.columns:
                        if f' ({y1})' in c or f' ({y2})' in c:
                            merged[c] = pd.to_numeric(merged[c], errors='coerce').fillna(0)
                    # Column order: key cols, then each metric's years side-by-side, newer year first
                    merged = merged[interleave_period_columns(merged.columns, periods=[str(y2), str(y1)])]
                    # Output: ready_2025-01-05_2025-01-20_vs_2024.csv (current range vs prior year)
                    out_name = f"ready_{year_to_filename[y2].replace('.csv', '')}_vs_{y1}.csv"
                    out_path = self.ready_dir / out_name
                    merged.to_csv(out_path, index=False)
                    self._update_status(f"YoY report saved: {out_path.name}")
                    self.logger.info(f"YoY report saved: {out_path} ({len(merged)} rows)")
                    built += 1
            if built == 0:
                self._update_status("No YoY pairs found (need same date range in two consecutive years)")
                self.logger.info("No YoY pairs found; skipping %s", self.ready_dir)
            else:
                self._update_status(f"YoY complete: {built} report(s) saved to {self.ready_dir}/")
        except Exception as e:
            error_msg = f"Error building YoY reports: {e}"
            self.logger.error(error_msg, exc_info=True)
            self._update_status(error_msg)
