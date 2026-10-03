# Changelog

All notable changes to Ads Report Fetcher are documented here. The project follows [Semantic Versioning](https://semver.org/).

---

## [1.2.0] — 2026-10-03

**Upgrading from 1.1.0:** run `pip install -r requirements.txt`. `google-ads` moves from 22.x to 33.x, because Google has shut off the API version the old one called. The Windows EXE already bundles the new version.

### Added

- **Pipeline results on the cards and in the status row.** Each Run Fetch now records what happened to every platform (`pipeline_results.py`).
  - **Cards:** each platform card shows its outcome:
    - green "✓ Saved 2 ranges";
    - amber "No data for prior year (Sep 2025)" or "Skipped: microsoft-ads.yaml missing";
    - red "Failed (current): Google Ads API error: UNAUTHENTICATED …", "timed out" or "Token expired", with a red border.
  - **Summary:** the status row shows a colored summary (e.g. "Completed with 1 failure: Google Ads"), plus a **View log** button when anything failed or was skipped.
  - **How failures are detected:** an ERROR logged while a range was being fetched means it failed; otherwise an empty result means "no data".
  - **Previously unreported:** platforms skipped for missing config, fetch timeouts and processing errors are reported too.
  - **Reset:** results clear on New Fetch, Unlock, Clear data or the next run.
- **"Open ready reports ↗"** in the status row opens the ready-reports folder in Explorer (Finder / xdg-open elsewhere). It appears whenever that folder has CSVs.
- **"Clear data…"** in the status row appears whenever report data exists. It deletes the CSVs in the raw, processed, merged and ready folders after confirmation, the same action as Settings → Data.

### Changed

- **UI refresh, first pass:**
  - **One design system:** colors, fonts and spacing now live in `ui_theme.py` as (light, dark) pairs, replacing about 30 inline colors. Light mode keeps working.
  - **Toolbar:** a single row. Run Fetch is the only accent-colored button; New Fetch and Process All Data are outlined. The ☢ emoji and the neon green/red status text are gone.
  - **Clear All Data** moved from the toolbar to a new **Settings → Data** section. It still asks for confirmation.
  - **Date range:** the two full calendars are replaced by compact date fields with a drop-down calendar (`tkcalendar.DateEntry`, already a dependency). Preset chips (Month to date, Last month, Last 7 days, Last 30 days) come from the new `date_presets.py`. "Last N days" ends yesterday, like the ad platforms. The prior-year checkbox is now a YoY switch.
  - **Live Log:** now a collapsible drawer. Collapsed, it shows a one-line ticker of the latest message, with errors in red and warnings in amber. The open/closed choice is remembered.
  - **Window:** the default size dropped from 960×1150 to 960×820, so it fits a 1080p laptop screen.
  - **Accounts:** Add, Edit and Delete are outlined buttons; Delete shows muted red text with a red tint on hover. Deletes still ask for confirmation.

- **Shared retry logic for all fetchers** (`utils.retry_call`, `utils.backoff_delay`, `utils.http_retry_after`). Each fetcher used to have its own retry loop. Now they all share one helper. Retries now:
  - **Use jittered backoff**, so retries aren't synchronized.
  - **Honour the server's `Retry-After` header**, capped at 120s.
  - **Only retry errors a retry can fix.** Each fetcher has its own rule:
    - **Google:** gRPC UNAVAILABLE, DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED or INTERNAL. Invalid queries and permission errors fail immediately.
    - **Meta:** rate-limit and temporary codes 1, 2, 4, 17, 32 and 613, or `is_transient`. Code 190 still prompts for a new token.
    - **Microsoft:** API error codes 0 (internal) and 117 (rate limit), plus network timeouts. Errors like "Invalid client data" now fail on the first try, and the log shows the API's actual error code and message.
    - **Reddit and TikTok:** HTTP 429 and 5xx, plus connection errors.
    - **TikTok also** checks the JSON `code` in successful (HTTP 200) responses. It retries 40100 (rate limit) and 50000/50002 (system errors). Any other non-zero code is logged with its message and `request_id`. Before, it silently returned no rows.
- Google and Meta now fetch every result page inside the retry, so a throttled later page is retried too.

### Fixed

- **Date picker arrows sometimes closed the calendar** instead of changing the month or year. tkcalendar 1.5's `DateEntry` closes its drop-down whenever the calendar loses focus, and on Windows clicking the ◂ ▸ buttons sometimes triggers that. The new `date_entry.DateEntry` only closes the drop-down when the pointer is outside it. Dates are also capped at today, so you can't pick a future start date anymore. Picking a start after the end, or an end before the start, now moves the other date to match instead of showing an error.
- **"No existing data" while data existed:** the data check only looked at the Google and Meta raw folders plus merged and ready, so Microsoft/TikTok/Reddit-only or processed-only data went unnoticed, and Clear/Process stayed disabled. It now checks every CSV in all four folders.
- **New Fetch left the date pickers disabled:** it re-enabled only the fallback month/year dropdowns, not the calendars. Locking, unlocking and New Fetch now share one helper that enables or disables all the date controls together.
- **YoY ready-report column order**: metrics are now interleaved side-by-side per metric (`Impressions (2026)`, `Impressions (2025)`, `Clicks (2026)`, `Clicks (2025)`, …) instead of one block per year, matching TECHNICAL_OVERVIEW. Ordering is handled by the new `processor.interleave_period_columns()`, which parses `<Metric> (<period>)` headers dynamically, with no hardcoded years, and supports any number of periods.
- **CI lint**: `ruff check .` now passes. CI was failing at the lint step on `main`, so tests never ran. The existing findings were fixed with ruff's auto-fixer, range-limited `ruff format` on over-long lines, and a handful of manual edits: removed unused variables, moved a constant below imports in `meta_fetcher.py`, replaced a bare `except` in `update_mcc_id.py`. Apart from those manual edits, behavior is unchanged (verified by comparing syntax trees). CI now pins `ruff==0.15.20`, and the ruff settings moved to `[tool.ruff.lint]`, with `[tool.ruff.format] quote-style = "preserve"`.
- **Google Ads fetch failing with `501 GRPC target method can't be resolved`** (and `No module named 'pkg_resources'` on newer setuptools): `google-ads` raised from `~=22.0` (API v13–v15, which Google has shut off) to `~=33.0` (API v23–v25). The new version doesn't import `pkg_resources`. Every GAQL field the fetcher uses exists in v25.
- **Microsoft Ads "Invalid client data" for ranges ending after today**: the Reporting API rejects custom ranges that end in the future, so the end date is now capped at today. A range that starts in the future is skipped.
- **Processing summary undercounted** (e.g. "Found 5 file(s)" then "2/2 processed"): `process_all()` keyed its results by bare filename, so platforms sharing a date-range filename overwrote each other. They're now keyed `platform/filename`.
- **Tests**: replaced the YoY column-order test, which only checked a local copy of the list, with unit tests for `interleave_period_columns()` and an exact-header assertion on a generated ready report.

---

## [1.1.0] — 2026-06-28

### Added

- **Per-platform "Re-authenticate" button**: when a fetch fails because an OAuth token expired, a 🔑 Re-authenticate button appears on that platform's card (Microsoft, Reddit, TikTok, Meta). Clicking it opens a console running the matching `setup_*_auth` script so the user can log in / paste the callback URL, then re-run the fetch. The button hides on the next successful fetch.
- **Setup launchers** (`setup_ms_auth.bat`, `setup_reddit_auth.bat`, `setup_tiktok_auth.bat`, `setup_meta_auth.bat`): visible-console wrappers that activate the venv and run the corresponding setup script. Works when running from source; in the packaged EXE the button shows an explanatory message instead (setup scripts are not bundled).
- **`utils.TokenExpiredError`**: typed exception carrying the platform name so the GUI can reliably detect token expiry (instead of matching error strings). Raised by the Microsoft/Reddit/TikTok fetchers; `MetaTokenExpiredError` now subclasses it.
- **`tests/test_microsoft_fetcher.py`**: covers Microsoft refresh-token rotation persistence, no-op when unchanged, soft-fail on write error, and `TokenExpiredError` on expiry.

### Changed

- **Microsoft refresh-token rotation**: `_ensure_auth` now writes the rotated `refresh_token` back to `microsoft-ads.yaml` after each refresh, resetting the 90-day inactivity window every run instead of pinning it to the original issue date (the cause of the `AADSTS700082` failure).
- **`setup_ms_auth.py`**: writes the new `refresh_token` to `microsoft-ads.yaml` automatically (preserving existing keys) instead of only printing it.
- **`setup_meta_auth.py`**: on re-auth, reuses the stored `app_id`/`app_secret` and prompts only for a new access token, preserving other keys on write.
- **Meta token-expiry UX**: the inline "paste new token" frame is replaced by the unified Re-authenticate button.

---

## [1.0.3] — 2026-04-05

### Added

- **CI workflow** (`.github/workflows/ci.yml`): runs `pytest` and `ruff` on every push/PR to `main`. Release workflow now also runs tests before building the EXE so a broken test cannot produce a release artifact.
- **Expanded test suite**: 8 → 26 tests. New classes cover `process_file()` (column mapping, schema fill, month/year from filename), `determine_funnel()` (Brand/Branded auto-rules, mappings lookup, DELETE/SKIP callbacks), `merge_platform_data()`, and `build_yoy_reports()` (consecutive-year pairing, column order, non-consecutive skip). All fixtures redirect `mappings.json` writes to `tmp_path` for isolation.
- **`utils.py`**: `_parse_id_from_favorite_display` and `_mask_id_for_log` extracted from `main.py`.
- **`log_handler.py`**: `GUILogHandler` extracted from `main.py`.
- **`config_manager.py`**: `ConfigManager` class owns all JSON file I/O (`config.json`, `*_favorites.json`). `main.py` delegates to it, removing ~400 lines of duplicated boilerplate.

### Changed

- **Reddit token auto-refresh**: `_api_request` now clears the cached access token and retries transparently on a first 401 (expired token). No YAML write-back needed — Reddit's `refresh_token` is permanent.
- **Settings tab scrolling**: entire Settings tab content is now wrapped in a `CTkScrollableFrame` so the Campaign Rules Manager list no longer clips at the bottom of the window.
- **Pinterest/TikTok platform cards**: "API not yet connected" italic label added to both cards. Pinterest checkbox is blocked from selection (API stub — no fetch code yet).

### Removed

- **`run_debug.bat`**: removed (identical to `run.bat`; use `run.bat` to launch).

### Fixed

- Hardcoded production domain removed from `PLATFORM_STATUS.md` and `TECHNICAL_OVERVIEW.md`; replaced with generic OAuth redirect URI instructions.

---

## [1.0.2] — 2026-02-01

### Removed

- **Dead code:** `fetch_monthly_reports` removed from all six fetchers (`api_fetcher`, `meta_fetcher`, `microsoft_fetcher`, `reddit_fetcher`, `tiktok_fetcher`, `pinterest_fetcher`). The app uses only `fetch_month_data`; the pipeline drives date ranges from `main.py`.
- **Redundant logging:** `logging.basicConfig` and duplicate `FileHandler`/`StreamHandler` setup removed from `api_fetcher.py`, `meta_fetcher.py`, and `processor.py`. Logging is configured once by the main app; these modules use `logging.getLogger(__name__)` only.

### Changed

- **Constants:** `META_RETENTION_MONTHS` (37) moved to `constants.py`; `main.py` and `meta_fetcher.py` import it from there.
- **Google Ads config path:** `api_fetcher.py` now loads `google-ads.yaml` from the app directory (`Path(__file__).resolve().parent`) so behavior does not depend on CWD.
- **Launcher:** `run_debug.bat` now uses `pythonw.exe` so only the app window appears in the taskbar (no console). `run.bat` and `run_debug.bat` both launch without a console.

### Documentation

- **TECHNICAL_OVERVIEW.md:** Launcher description updated (both run.bat and run_debug.bat, no console).
- **ROADMAP.md:** "Where we are" and summary updated to v1.0.2 where relevant.

---

## [1.0.1] — 2026-02-01

### Added

- **Per-platform pipeline progress**  
  During **Run Fetch**, the header status bar now shows live per-platform progress (e.g. `Google: 2/2, Meta: 1/2, Microsoft: 0/2`) so long runs are less opaque. Each platform reports completed date ranges (current + optional prior year). Stub platforms (TikTok, Pinterest) show as 1/1 when skipped.

---

## [1.0.0] — 2026-02-20

First versioned release. Multi-platform ads report fetcher with configurable output directories, Settings UI for report paths, Reddit and Microsoft Ads improvements, and reliability fixes.

### Added

- **Versioning**
  - `__version__` in `main.py` (shown in window title: "Ads Report Fetcher (Multi-Platform) v1.0.0").
  - `version` in `pyproject.toml` for tooling and packaging.
  - This changelog (`CHANGELOG.md`).

- **Configurable output directories**
  - Settings in `config.json`: `raw_reports_dir`, `processed_reports_dir`, `merged_reports_dir`, `ready_reports_dir` (defaults: `raw_reports`, `processed_reports`, `merged_reports`, `ready_reports`).
  - All fetch, process, merge, YoY, and Clear All Data use these paths.
  - **Settings tab**: Four editable fields with Browse for Raw reports, Processed reports, Merged reports, and Ready reports (YoY). Save All Settings persists them to `config.json`.
  - Report directories and Theme appear above Campaign Rules Manager in Settings so they are visible without scrolling.

- **Constants**
  - `constants.py`: `PIPELINE_FETCH_WAIT_SECONDS` (3600), `DIALOG_WAIT_SECONDS` (300). Used by pipeline wait and dialog timeouts.

- **Tests**
  - `tests/test_processor.py`: Pytest tests for `_parse_range_from_filename`, `_parse_month_year_from_range_filename`, YoY column order, and `RANGE_FILENAME_PATTERN`.
  - `pyproject.toml`: pytest, ruff, and mypy configuration.

- **Developer token requirement for Microsoft Ads**
  - Clear error when `developer_token` is missing in `microsoft-ads.yaml`, with instructions to get it from ads.microsoft.com → Tools → API → Developer token.

### Changed

- **Reddit Ads**
  - **Campaign names**: Report returns campaign IDs; fetcher now resolves names via `GET /api/v3/ad_accounts/{id}/campaigns` and replaces numeric IDs with human-readable names (e.g. "Retargeting Campaign USA").
  - **Cost (SPEND)**: API returns micro-currency; now converted to dollars (÷ 1,000,000) so Cost displays with decimals (e.g. 389.97).
  - **Revenue (CONVERSION_PURCHASE_TOTAL_VALUE)**: API returns cents; now converted to dollars (÷ 100) so Revenue displays with decimals (e.g. 2171.76).
  - **Empty date ranges**: When v3 "Get A Report" returns 200 with empty metrics (no ads in range), treat as success and skip fallback endpoints instead of retrying and warning.

- **Microsoft Ads**
  - **OAuth**: Token exchange requires `client_secret`. Setup and fetcher use **Web app flow**: redirect URI `http://localhost:8400`, client_id + client_secret in `microsoft-ads.yaml`. Run `setup_ms_auth.py` with Web app credentials; add redirect URI in Azure (Web platform).
  - **Token refresh**: Fetcher uses `OAuthWebAuthCodeGrant` when `client_secret` is present so refresh succeeds. Removed invalid `auth.oauth_tokens = tokens` assignment (tokens are set internally by bingads).
  - **Developer token**: Required for Reporting API; added validation and clear error message if missing.

- **Settings tab layout**
  - Theme, Report directories, and Save All Settings are packed first so they appear at the top; Campaign Rules Manager follows and expands into remaining space. Fixes issue where report directory fields were off-screen below Campaign Rules.

- **Config loading**
  - `_load_settings()` merges loaded `config.json` with defaults so new keys (e.g. `raw_reports_dir`) are present when saving and not dropped.

### Fixed

- **Edit rule crash**: Settings → Campaign Rules → Edit caused deadlock (main thread blocked on `Event.wait()` after `after(0, show_dialog)`). Fixed by building and showing the dialog on the main thread and using `dialog.wait_window(dialog)` instead of a separate event.

- **Run Fetch button**: Re-enabled in `finally` of pipeline thread so it is never left disabled after completion or error.

- **JSON/YAML errors**: Specific handling for `json.JSONDecodeError` and `yaml.YAMLError` (and `OSError`) when loading config, mappings, and favorites; user-facing message and fallback to defaults or empty list where appropriate.

- **Retries**: Google Ads, Microsoft Ads, and Reddit fetchers use configurable retries (e.g. 3 attempts, exponential backoff) for transient errors (5xx, 429). Google skips retry on permission-denied.

### Documentation

- **README.md**: Quick start, first run, output folders, requirements (Python 3.10+), links to TECHNICAL_OVERVIEW, ROADMAP, and CHANGELOG. Version and Development (pytest, ruff, mypy) sections.
- **TECHNICAL_OVERVIEW.md**: Range-based fetch, Run Fetch, Main/Accounts/Settings tabs, default window 960×1150, configurable dirs, checkbox below date controls, Reddit v3, Microsoft Web auth and developer token.
- **PLATFORM_STATUS.md**: Microsoft and Reddit setup details; developer_token required; configurable dirs noted where relevant.
- **ROADMAP.md**: Phases 1–4 progress; CHANGELOG and versioning in place.
- **MICROSOFT_ADS_ADMIN_SETUP.md**: Referenced for Azure admin consent and Web app setup.

### Security & robustness (from roadmap)

- Config and favorites paths use `_APP_DIR` (same folder as `main.py`).
- Restrictive file permissions (`_restrict_file_permissions`) on `config.json` and `meta-ads.yaml` after first write.
- Rotating file handler for `app_debug.log` (2 MB × 3 backups); `*.log.*` in `.gitignore`.
- `_mask_id_for_log()` for IDs; tokens and full secrets never logged.
- Thread/UI: pipeline `finally` re-enables Run Fetch; Edit rule uses `wait_window` to avoid deadlock.

### Removed

- Deprecated favorite methods and duplicate dialog code (add/edit/delete favorites for legacy paths); UI uses `_on_settings_*` handlers.
- Old Settings folder fields (Download folder / Output folder) replaced by the four report directory fields.

---

## Planned

- Export/Import settings (config + favorites, no secrets).
- Optional: per-platform progress in pipeline UI.
- Future: keychain/credential manager for tokens.

---

[1.2.0]: https://github.com/joemachen/ad_data_fetcher/releases/tag/v1.2.0
[1.0.0]: https://github.com/joemachen/ad_data_fetcher/releases/tag/v1.0.0
