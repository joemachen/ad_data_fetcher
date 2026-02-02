# Ads Report Fetcher — Technical Overview

## Purpose

**Ads Report Fetcher** is a desktop application that fetches advertising performance data from **Google Ads** and **Meta (Facebook) Ads**, processes it into a standardized format, and merges it into monthly reports. It supports a multi-step pipeline: fetch → process → merge, with a single “Run Full Pipeline” flow that runs fetches only for platforms selected in the GUI.

## Key Features

- **Multi-platform fetch**: Google Ads, Meta Ads, Microsoft Ads, TikTok Ads, Reddit Ads, and Pinterest Ads. A single global date range (Control Panel) and per-platform Customer/Account ID inputs. Only **Google** and **Meta** fetchers are currently wired; Microsoft, TikTok, Reddit, and Pinterest are stubs (pipeline completes without fetching).
- **Favorites**: Saved customer/account favorites for all six platforms (Google, Meta, Microsoft, TikTok, Reddit, Pinterest), editable in the Settings tab.
- **Pipeline actions**:
  - **New Fetch**: Unlocks date range and inputs so a new fetch can be configured (enabled after a fetch completes).
  - **Run Full Pipeline**: Runs only the platforms currently selected and “ready” (valid ID + confirmed date range). For each ready platform: runs its fetch (Google/Meta implemented; others stub), then processes all raw CSVs and merges. Requires no existing data (or user must clear data first). Progress and status appear in the header status bar and Live Log.
  - **Process All Data**: No fetch; processes all raw CSVs in `raw_reports/` and runs the merge step.
  - **Clear All Data**: Deletes all CSV files in `raw_reports/`, `processed_reports/`, and `merged_reports/` (with confirmation).
- **Pipeline status**: A global **Status** label (header bar) shows messages (e.g. “Checking token…”, “Token valid and saved successfully”). Run Full Pipeline is enabled only when at least one platform is selected and ready and there is no existing data.
- **Campaign classification**: During processing, campaigns are classified as Top/Bottom funnel (or excluded). Uses `mappings.json`, auto-rules (e.g. “Brand”/“Branded” → Bottom), and optional user prompts for unclassified campaigns.
- **Theme and config**: Settings tab for theme (dark/light), default favorites per platform, and Meta Ads access token. Config persisted in `config.json`.
- **Meta token**: Token can be set in Settings or, when expired during a fetch, in the Main tab (token input frame). Token is validated via Meta Graph API `debug_token` before saving to `meta-ads.yaml`; save runs in a background thread so the UI stays responsive.
- **Logging**: File (`app_debug.log`) and GUI Live Log; log messages from worker threads are enqueued and appended on the main thread to avoid Tk deadlock. Log is cleared on window close.

## Architecture

- **GUI**: Single-window CustomTkinter app. **Header**: New Fetch, Run Full Pipeline, Process All Data, Clear All Data, data-status label; below it a **Status** label (bound to `status_text`) and pipeline progress when running. **Tabs**: **Main** (Control Panel — date range; platform cards in a scrollable frame with checkbox, account dropdown, and status per platform; Process Google Files / Process Meta Files buttons; Live Log at bottom) and **Settings** (Meta token field, Favourites Editor, default favorites). All long-running work (fetch, process, merge) runs in background threads; UI updates are scheduled on the main thread.
- **Fetch**: Google via **Google Ads API** (`api_fetcher.py`); Meta via **Meta Ads API** (`meta_fetcher.py`). Microsoft, TikTok, Reddit, Pinterest are stubs in `main.py` (completion events set; fetcher modules exist but are not yet imported by main).
- **Process**: `processor.py` is platform-agnostic. Defines **INTERNAL_SCHEMA** and **PLATFORM_CONFIG** (column mapping + display name + channel per platform). Raw CSVs in `raw_reports/{platform}/` are mapped, funnel stage applied (via `mappings.json`), then validated/filled and written to `processed_reports/{platform}/`.
- **Merge**: Same module merges by `{month}_{year}.csv` across all subfolders of `processed_reports/` and writes unified monthly CSVs to `merged_reports/`.
- **Config and state**: `config.json` (theme, default favorites, default folders), `customer_favorites.json`, `meta_favorites.json`, `ms_favorites.json`, `tiktok_favorites.json`, `reddit_favorites.json`, `pinterest_favorites.json`, `mappings.json` (campaign → funnel), `google-ads.yaml`, `meta-ads.yaml` for API credentials.

## Components

| File | Role |
|------|------|
| **main.py** | GUI entry point. Builds Main tab (platform cards, date range, token-expired frame for Meta) and Settings tab (Meta token, favorites). Handles Run Full Pipeline, Process All Data, Clear All Data; starts background threads for fetch/process/merge. Meta token: validate via API, save to `meta-ads.yaml`, retry on expiry. |
| **api_fetcher.py** | Google Ads API client. Loads `google-ads.yaml`, runs GAQL queries for campaign metrics per month, saves CSVs to `raw_reports/google/` as `{month}_{year}.csv`. |
| **meta_fetcher.py** | Meta Ads API client. Loads `meta-ads.yaml` (app_id, app_secret, access_token), calls Insights API, saves to `raw_reports/meta/`. Raises `MetaTokenExpiredError` on token expiry. |
| **microsoft_fetcher.py** | Microsoft Ads fetcher (skeleton). Not imported by main; pipeline stub only. |
| **tiktok_fetcher.py** | TikTok Ads fetcher (skeleton). Not imported by main; pipeline stub only. |
| **reddit_fetcher.py** | Reddit Ads fetcher (skeleton). Not imported by main; pipeline stub only. |
| **pinterest_fetcher.py** | Pinterest Ads fetcher (skeleton). Not imported by main; pipeline stub only. |
| **processor.py** | Platform-agnostic. INTERNAL_SCHEMA, PLATFORM_CONFIG, reads raw CSVs, maps columns, applies funnel (mappings.json + auto-rules), writes processed CSVs, merges into `merged_reports/`. |

## Data Flow and Directories

1. **Raw**: `raw_reports/google/`, `raw_reports/meta/`, (future: microsoft/, tiktok/, reddit/, pinterest/) — one CSV per month per platform, e.g. `jan_2025.csv`. Subfolders are auto-created by fetchers and processor.
2. **Processed**: `processed_reports/{platform}/` — same filenames, standardized columns and funnel stage.
3. **Merged**: `merged_reports/` — one CSV per month combining all platform rows.

File naming: `{month_abbrev}_{year}.csv` (e.g. `jan_2025.csv`). Processor discovers files by this pattern in subfolders of `raw_reports`.

## Workflow

- **Main tab**: User sets date range (start/end month–year) and confirms it (locks for all platforms). User selects platforms via checkboxes and sets account IDs (or picks favorites). **Run Full Pipeline** runs fetch for each selected, ready platform (Google and Meta implemented; others stub), then process-all and merge. No per-platform “Start Google Fetch” / “Start Meta Fetch” buttons; fetching is only via Run Full Pipeline.
- **Meta token**: When token expires during a fetch, the app shows a token input frame in the Meta card; user pastes a new token and clicks **Update Token**. Token is validated via Meta `debug_token` API; if valid, saved to `meta-ads.yaml` and fetch retries. Token can also be set in Settings (same validation and save).
- **Process All Data**: No fetch; processes all raw CSVs and runs merge.
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

Setup scripts: `setup_auth.py`, `setup_meta_auth.py`, `setup_ms_auth.py`, `update_mcc_id.py` (run directly with Python). Batch: `run_debug.bat` (launch app with console), `stop_app.bat` (stop running instances). Dependencies in `requirements.txt` (no Playwright).

---

## Files and folders for removal consideration

| Item | Reason |
|------|--------|
| **favorites.json** | Not referenced in code. The app uses `customer_favorites.json`, `meta_favorites.json`, and per-platform `*_favorites.json`. If present, can be deleted (keep in `.gitignore` for local leftovers). |

**Removed (as of last cleanup):** `fetcher.py` (legacy Playwright fetcher); batch files consolidated to `run_debug.bat` and `stop_app.bat` only (removed: `run.bat`, `setup.bat`, `setup_meta.bat`, `setup_ms_auth.bat`, `update_mcc.bat`, `kill_app.bat`). Auth is done by running the Python setup scripts directly.

---

This overview reflects the current codebase. For step-by-step usage, rely on in-app labels, tooltips, and status messages (no README in repo at time of writing).
