# Changelog

All notable changes to Ads Report Fetcher are documented here. The project follows [Semantic Versioning](https://semver.org/).

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

## [Unreleased]

- Export/Import settings (config + favorites, no secrets).
- Optional: per-platform progress in pipeline UI.
- Future: keychain/credential manager for tokens.

---

[1.0.0]: https://github.com/joemachen/ad_data_fetcher/releases/tag/v1.0.0
