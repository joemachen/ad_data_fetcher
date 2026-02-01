# Ads Report Fetcher — Technical Overview

## Purpose

**Ads Report Fetcher** is a desktop application that fetches advertising performance data from **Google Ads** and **Meta (Facebook) Ads**, processes it into a standardized format, and merges it into monthly reports. It supports a multi-step pipeline: fetch → process → merge, with optional per-platform fetch and a single “Run Full Pipeline” flow.

## Key Features

- **Multi-platform fetch**: Google Ads, Meta Ads, Microsoft Ads, TikTok Ads, Reddit Ads, and Pinterest Ads (API) with a single global date range (Control Panel) and per-platform Customer/Account ID inputs.
- **Favorites**: Saved customer/account favorites (Google and Meta) with dropdown selection; favorites are edited in the Settings tab.
- **Pipeline actions**:
  - **New Fetch**: Unlocks inputs so a new fetch can be configured (enabled after a fetch completes).
  - **Run Full Pipeline**: Loops through only the platforms currently selected in the GUI; fetches each ready platform (locked ID + date range), then processes and merges. Requires no existing data (or user must clear data first).
  - **Process All Data**: Processes all raw CSVs in `raw_reports/` and runs the merge step (no fetch).
  - **Clear All Data**: Deletes all CSV files in `raw_reports/`, `processed_reports/`, and `merged_reports/` (with confirmation).
- **Pipeline status**: Checklist shows readiness for Google Ads, Meta Ads, and “has data”; Run Full Pipeline is enabled only when both platforms are ready and there is no existing data.
- **Campaign classification**: During processing, campaigns are classified as Top/Bottom funnel (or excluded). Uses `mappings.json`, auto-rules (e.g. “Brand”/“Branded” → Bottom), and optional user prompts for unclassified campaigns.
- **Theme and config**: Settings tab for theme (dark/light), default favorites, and download/output folders; persisted in `config.json`.
- **Logging**: File (`app_debug.log`) and GUI log area; log is cleared on window close.

## Architecture

- **GUI**: Single-window CustomTkinter app with a Control Panel layout: header bar (New Fetch, Run Full Pipeline, Process All Data, Clear All Data), global date range at top, Source Selection and Account IDs inside a CTkScrollableFrame (450px), Live Log pinned at the bottom (grid row weight=0). All long-running work (fetch, process, merge) runs in background threads so the UI stays responsive.
- **Fetch**: Google via **Google Ads API** (`api_fetcher.py`); Meta via **Meta Ads API** (`meta_fetcher.py`). A legacy Playwright-based Google fetcher exists in `fetcher.py` but is not used by the main app.
- **Process**: `processor.py` is platform-agnostic. It uses a standard **INTERNAL_SCHEMA** (Month, Year, Platform, Channel, Campaign, Funnel Stage, Impressions, Clicks, Cost, Revenue, Conversions) and a **PLATFORM_CONFIG** dictionary that maps each platform’s raw column names to the schema. Raw CSVs in `raw_reports/{platform}/` are mapped, funnel stage is applied (via `mappings.json` for all platforms), then validated/filled against the schema and written to `processed_reports/{platform}/`.
- **Merge**: Same module merges by `{month}_{year}.csv` across **all** subfolders of `processed_reports/` (google/, meta/, future platforms) and writes unified monthly CSVs to `merged_reports/`.
- **Config and state**: `config.json` (theme, defaults), `customer_favorites.json`, `meta_favorites.json`, `mappings.json` (campaign → funnel), `google-ads.yaml` and `meta-ads.yaml` for API credentials.

## Components

| File | Role |
|------|------|
| **main.py** | GUI entry point. Builds tabs (Google Ads, Meta Ads, Settings), buttons, date/ID inputs, favorites dropdowns, pipeline checklist, log area. Starts background threads for fetch/process/merge and handles Meta token expiry (prompt to update token). |
| **api_fetcher.py** | Google Ads API client. Loads `google-ads.yaml`, runs GAQL queries for campaign metrics (impressions, clicks, cost, conversions, revenue) per month, aggregates by campaign, saves CSVs to `raw_reports/google/` as `{month}_{year}.csv`. |
| **meta_fetcher.py** | Meta Ads API client. Loads `meta-ads.yaml` (app_id, app_secret, access_token), calls Insights API for campaign-level metrics, saves to `raw_reports/meta/`. Raises `MetaTokenExpiredError` on token expiry. |
| **microsoft_fetcher.py** | Microsoft Ads fetcher (skeleton). Loads `microsoft-ads.yaml`, saves to `raw_reports/microsoft/` as `{month}_{year}.csv`. |
| **tiktok_fetcher.py** | TikTok Ads fetcher (skeleton). Loads `tiktok-ads.yaml`, saves to `raw_reports/tiktok/`. |
| **reddit_fetcher.py** | Reddit Ads fetcher (skeleton). Loads `reddit-ads.yaml`, uses custom User-Agent in headers, saves to `raw_reports/reddit/`. |
| **pinterest_fetcher.py** | Pinterest Ads fetcher (skeleton). Loads `pinterest-ads.yaml`, saves to `raw_reports/pinterest/`. |
| **fetcher.py** | Legacy Playwright-based Google Ads fetcher (browser automation). Not used by the current main flow; main uses `api_fetcher.py`. |
| **processor.py** | Platform-agnostic. Defines **INTERNAL_SCHEMA** and **PLATFORM_CONFIG** (column mapping + display name + channel per platform). Reads raw CSVs from `raw_reports/{platform}/`, maps via config, adds Month/Year from filename, applies funnel logic (mappings.json + auto-rules) for all platforms, validates/fills schema, writes to `processed_reports/{platform}/`. Merges by `{month}_{year}.csv` across all processed subfolders into `merged_reports/`. Logs file- and row-level validation issues. |

## Data Flow and Directories

1. **Raw**: `raw_reports/google/`, `raw_reports/meta/`, `raw_reports/microsoft/`, `raw_reports/tiktok/`, `raw_reports/reddit/`, `raw_reports/pinterest/` — one CSV per month per platform, e.g. `jan_2025.csv`. Subfolders are auto-created by the processor and fetchers.
2. **Processed**: `processed_reports/{platform}/` — same filenames, standardized columns and funnel stage.
3. **Merged**: `merged_reports/` — one CSV per month combining all platform rows (e.g. `jan_2025.csv`).

File naming: `{month_abbrev}_{year}.csv` (e.g. `jan_2025.csv`). Processor discovers files via this pattern in subfolders of `raw_reports`.

## Workflow

- **Google Ads tab**: User sets Customer ID and date range (start/end month–year), optionally picks a favorite. “Lock” confirms ID and date range; “Start Google Fetch” runs the API fetcher for each month in the range. Progress and status are shown in the UI and log.
- **Meta Ads tab**: Same idea with Account ID (e.g. `act_123`) and date range; “Start Meta Fetch” runs the Meta fetcher. If the token is expired, the app catches `MetaTokenExpiredError`, prompts for a new token, and (if configured) can update `meta-ads.yaml` and retry.
- **Run Full Pipeline**: Runs only the platforms currently selected in the GUI (Google, Meta, Microsoft, TikTok, Reddit, Pinterest). For each selected and ready platform, runs its fetch step, then process-all, then merge. Pipeline progress bar and status text reflect current step.
- **Process All Data**: No fetch; finds all raw CSVs, runs process-all and merge. Useful when raw data already exists or after manual edits.
- **Clear All Data**: Removes all CSVs from raw, processed, and merged directories after confirmation.

## Error Handling

- **Google Ads**: API errors (e.g. permission denied) are logged and shown in status; guidance for MCC/login_customer_id and `update_mcc_id.py` when relevant.
- **Meta Ads**: Token expiry is detected (e.g. OAuthException, code 190, “session has expired” / “access token expired”). App raises `MetaTokenExpiredError`, shows a message, and can prompt for a new token and re-run (token update flow is wired in the GUI).
- **Processor**: Missing columns in raw CSVs get defaults; invalid or missing mappings fall back to Top funnel or user prompt. Errors per file are logged and reported without stopping the whole run.
- **Threading**: Cancel events and completion events are used so that batch pipeline and single-platform fetches can be coordinated and the UI updated from the main thread.

## Technologies

- **Python 3**: Main runtime.
- **GUI**: CustomTkinter (modern look, theme support).
- **Google Ads**: `google-ads` (Google Ads API client), `google-auth-oauthlib`; config in `google-ads.yaml`.
- **Meta Ads**: `facebook-business` (Meta Marketing API); config in `meta-ads.yaml` (app_id, app_secret, access_token).
- **Data**: `pandas` for CSV read/write and aggregation; `pyyaml` for config files.
- **Utilities**: `python-dateutil`, standard library `logging`, `threading`, `pathlib`, `json`.

Setup scripts (e.g. `setup_auth.py`, `setup_meta_auth.py`, `update_mcc_id.py`) and batch files (`run.bat`, `setup.bat`, `setup_meta.bat`, etc.) support first-time auth and MCC updates. Dependencies are listed in `requirements.txt` (no Playwright in the main app path; fetcher.py would require it if used).

---

This overview describes the app’s behavior and layout as implemented in the codebase. For step-by-step usage, see the README or in-app labels and tooltips.
