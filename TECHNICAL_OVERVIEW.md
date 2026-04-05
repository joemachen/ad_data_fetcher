# Ads Report Fetcher — Technical Overview

For a quick **platform status and next steps** (what works, what’s pending, setup links), see **[PLATFORM_STATUS.md](PLATFORM_STATUS.md)**.

## Purpose

**Ads Report Fetcher** is a desktop application that fetches advertising performance data from **Google Ads**, **Meta (Facebook) Ads**, **Microsoft Ads**, **Reddit Ads**, and (stubs) TikTok and Pinterest. It processes data into a standardized format and merges by **date range**, with optional **year-over-year** (YoY) comparison. Pipeline: fetch → process → merge (and optionally build YoY ready reports).

## Key Features

- **Multi-platform fetch**: Google Ads, Meta Ads, Microsoft Ads, TikTok Ads, Reddit Ads, and Pinterest Ads. A single global date range (Control Panel) and per-platform Customer/Account ID inputs. **Google**, **Meta**, **Microsoft**, **Reddit**, and **TikTok** fetchers are wired; Pinterest is a stub (pipeline completes without fetching).
- **Favorites**: Saved customer/account favorites for all six platforms (Google, Meta, Microsoft, TikTok, Reddit, Pinterest), editable in the Settings tab.
- **Pipeline actions**:
  - **New Fetch**: Unlocks date range and inputs so a new fetch can be configured (enabled after a fetch completes).
  - **Run Fetch**: Runs only the platforms currently selected and “ready” (valid ID + confirmed date range). For each ready platform: fetches the current date range (and optionally the same range for the previous year), then processes all raw CSVs, merges by range, and builds YoY ready reports when prior-year data exists. Progress and status appear in the header status bar and Live Log.
  - **Process All Data**: No fetch; processes all raw CSVs and runs merge + YoY step.
  - **Clear All Data**: Deletes all CSV files in `raw_reports/`, `processed_reports/`, and `merged_reports/` (with confirmation).
- **Pipeline status**: A global **Status** label (header bar) shows messages (e.g. “Checking token…”, “Token valid and saved successfully”). During **Run Fetch**, a **per-platform progress** line appears (e.g. “Google: 2/2, Meta: 1/2, Microsoft: 0/2”) so long runs are less opaque. Run Fetch is enabled when at least one platform is selected and ready (data may exist; run overwrites).
- **Campaign classification**: During processing, campaigns are classified as Top/Bottom funnel (or excluded). Uses `mappings.json`, auto-rules (e.g. “Brand”/“Branded” → Bottom), and optional user prompts for unclassified campaigns.
- **Theme and config**: Settings tab for theme (dark/light), default favorites per platform, and Meta Ads access token. Config persisted in `config.json`.
- **Meta token**: Token can be set in Settings or, when expired during a fetch, in the Main tab (token input frame). Token is validated via Meta Graph API `debug_token` before saving to `meta-ads.yaml`; save runs in a background thread so the UI stays responsive.
- **Logging**: Rotating file (`app_debug.log`, 2 MB × 3 backups) and GUI Live Log; worker threads enqueue messages for the main thread. Tokens and full account/customer IDs are never logged (IDs are masked in log messages).

## Architecture

- **GUI**: Single-window CustomTkinter app. **Header**: New Fetch, Run Fetch, Process All Data, Clear All Data, data-status label; below it a **Status** label and pipeline progress when running. **Tabs**: **Main** (date range picker, Confirm/Unlock, “Also pull same range previous year” checkbox below, then platform cards in two rows and Live Log), **Accounts** (default account per platform), **Settings** (theme, Report directories — four editable paths with Browse, Save All Settings, then Campaign Rules Manager; default favorites, Meta token, favorites editor). Default window size 960×1150 so both platform rows and Live Log are visible. All long-running work runs in background threads; UI updates are scheduled on the main thread.
- **Fetch**: Google via **Google Ads API** (`api_fetcher.py`); Meta via **Meta Ads API** (`meta_fetcher.py`); Microsoft via **Bing Ads Reporting API** (`microsoft_fetcher.py`; requires `developer_token` in `microsoft-ads.yaml`; OAuth Web app flow with client_secret and redirect `http://localhost:8400`); Reddit via **Reddit Ads API v3** (`reddit_fetcher.py`, config in `reddit-ads.yaml`; run `setup_reddit_auth.py` once); TikTok via **TikTok Marketing API v1.3** (`tiktok_fetcher.py`, config in `tiktok-ads.yaml`: client_key, client_secret, access_token, refresh_token; run `setup_tiktok_auth.py`; OAuth redirect URI registered in TikTok developer console; report/integrated/get; token refresh for 24h expiry). Pinterest is a stub in `main.py`.
- **Process**: `processor.py` is platform-agnostic. Defines **INTERNAL_SCHEMA** and **PLATFORM_CONFIG** (column mapping + display name + channel per platform). Raw CSVs in the configured raw dir (default `raw_reports/{platform}/`) are mapped, funnel stage applied (via `mappings.json`), then validated/filled and written to the configured processed dir (default `processed_reports/{platform}/`).
- **Merge**: Processor discovers files by **date-range** pattern `YYYY-MM-DD_YYYY-MM-DD.csv` in the configured raw/processed dirs. Merges current-range and (if present) prior-year range into unified CSVs in the configured merged dir (default `merged_reports/`); builds YoY ready reports in the configured ready dir (default `ready_reports/`) as `ready_{current_range}_vs_{prior_year}.csv` with columns: Campaign, Platform, Channel, Funnel Stage, then per metric newer-year then older-year (e.g. `Impressions (2026)`, `Impressions (2025)`).
- **Config and state**: All config paths are resolved from the app directory (`_APP_DIR`, same folder as `main.py`): `config.json`, `*_favorites.json`, `mappings.json`, `*-ads.yaml`. Output directories (`raw_reports_dir`, `processed_reports_dir`, `merged_reports_dir`, `ready_reports_dir`) are in `config.json` and editable in **Settings → Report directories**. Restrictive file permissions (0o600) are applied on first write for `config.json` and `meta-ads.yaml`.

## Components

| File | Role |
|------|------|
| **main.py** | GUI entry point. Builds Main tab (platform cards, date range, token-expired frame for Meta), Accounts tab (default account grid), and Settings tab (Meta token, favorites). Handles Run Fetch, Process All Data, Clear All Data; starts background threads for fetch/process/merge. Meta token: validate via API, save to `meta-ads.yaml`, retry on expiry. |
| **api_fetcher.py** | Google Ads API client. Loads `google-ads.yaml`, runs GAQL for campaign metrics by date range, saves to `raw_reports/google/` as `YYYY-MM-DD_YYYY-MM-DD.csv`. |
| **meta_fetcher.py** | Meta Ads API client. Loads `meta-ads.yaml` (app_id, app_secret, access_token), calls Insights API, saves to `raw_reports/meta/`. Raises `MetaTokenExpiredError` on token expiry. |
| **microsoft_fetcher.py** | Microsoft Ads fetcher. Uses bingads SDK; loads `microsoft-ads.yaml`; Campaign Performance Report by date range; saves to `raw_reports/microsoft/`. |
| **tiktok_fetcher.py** | TikTok Marketing API v1.3 client. Loads `tiktok-ads.yaml`; OAuth token refresh; report/integrated/get; saves to `raw_reports/tiktok/`. |
| **reddit_fetcher.py** | Reddit Ads fetcher. OAuth2 (adsread); loads `reddit-ads.yaml`; calls Reddit Ads API v2 report; saves to `raw_reports/reddit/` with campaign_name, amount_spent, conversion. |
| **pinterest_fetcher.py** | Pinterest Ads fetcher (skeleton). Not imported by main; pipeline stub only. |
| **processor.py** | Platform-agnostic. INTERNAL_SCHEMA, PLATFORM_CONFIG, reads raw CSVs, maps columns, applies funnel (mappings.json + auto-rules), writes processed CSVs, merges into `merged_reports/`. |

## Data Flow and Directories

Output directories are configurable in **Settings → Report directories** (stored in `config.json`). Defaults:

1. **Raw**: `raw_reports/{platform}/` — one CSV per date range per platform, e.g. `2025-01-05_2025-01-20.csv`. Subfolders are auto-created. No data for a range is skipped (logged, not fatal).
2. **Processed**: `processed_reports/{platform}/` — same range filenames, standardized columns and funnel stage.
3. **Merged**: `merged_reports/` — one CSV per range combining all platforms (current range and, if pulled, prior-year range).
4. **Ready (YoY)**: `ready_reports/` by default; files named `ready_{start}_{end}_vs_{prior_year}.csv` (e.g. `ready_2025-01-05_2025-01-20_vs_2024.csv`). Columns: Campaign, Platform, Channel, Funnel Stage, then each metric with actual year in header (e.g. `Revenue (2025)`, `Revenue (2024)`), newer year first.

File naming: `YYYY-MM-DD_YYYY-MM-DD.csv`. Processor only considers this range pattern; legacy monthly filenames are not supported.

## Workflow

- **Main tab**: User sets date range (start/end; default on load: first of month → today), optionally checks “Also pull same range previous year”, and confirms (locks range). User selects platforms and account IDs (or favorites). **Run Fetch** runs fetch for each selected, ready platform for current (and if checked, prior-year) range, then process-all, merge, and YoY. Fetching is only via Run Fetch. (Pipeline runs fetch → process → merge → YoY.)
- **Meta token**: When token expires during a fetch, the app shows a token input frame in the Meta card; user pastes a new token and clicks **Update Token**. Token is validated via Meta `debug_token` API; if valid, saved to `meta-ads.yaml` and fetch retries. Token can also be set in Settings (same validation and save).
- **Process All Data**: No fetch; processes all raw CSVs and runs merge + YoY.
- **Clear All Data**: Removes all CSVs from raw, processed, and merged directories after confirmation.

## Error Handling

- **Google Ads**: API errors (e.g. permission denied) are logged and shown in status; guidance for MCC and `update_mcc_id.py` when relevant.
- **Meta Ads**: Token expiry raises `MetaTokenExpiredError`; app shows token input, validates new token via API before saving, then retries fetch. Save and validation run off the main thread so the UI does not freeze.
- **Processor**: Missing columns get defaults; invalid/missing mappings fall back to Top funnel or user prompt. Errors per file are logged without stopping the run.
- **Threading**: Cancel and completion events coordinate batch pipeline and fetches; GUI updates (including Live Log) are scheduled on the main thread only (queue-based log to avoid deadlock).

## Technologies

- **Python 3**: Main runtime.
- **GUI**: CustomTkinter (theme support).
- **Google Ads**: `google-ads`, `google-auth-oauthlib`; config in `google-ads.yaml`.
- **Meta Ads**: `facebook-business`; config in `meta-ads.yaml` (app_id, app_secret, access_token). Token checked via Graph API `debug_token` before save.
- **Data**: `pandas`, `pyyaml`; standard library `logging`, `threading`, `queue`, `pathlib`, `json`, `urllib`.
- **Utilities**: `python-dateutil`.

Setup scripts: `setup_auth.py`, `setup_meta_auth.py`, `setup_ms_auth.py`, `setup_tiktok_auth.py`, `setup_reddit_auth.py`, `update_mcc_id.py` (run directly with Python). Run: `run.bat` or `run_debug.bat` (no console; only app window in taskbar), `stop_app.bat` to stop instances. Dependencies in `requirements.txt`. Version is in `main.py` as `__version__` and shown in the window title.

---

## Files and folders for removal consideration

| Item | Reason |
|------|--------|
| **favorites.json** | Not referenced in code. The app uses `customer_favorites.json`, `meta_favorites.json`, and per-platform `*_favorites.json`. If present, can be deleted (keep in `.gitignore` for local leftovers). |

**Removed (as of last cleanup):** `fetcher.py` (legacy Playwright fetcher); Ad-Hoc tab; per-platform “Process Google/Meta Files” buttons; preset date dropdown (all ranges custom). Auth is done by running the Python setup scripts directly.

---

This overview reflects the current codebase. For run instructions and first-run steps, see **[README.md](README.md)**.
