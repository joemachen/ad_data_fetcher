# Ads Report Fetcher

Desktop app to pull advertising performance data from multiple platforms (Google Ads, Meta, Microsoft, Reddit, TikTok, Pinterest), process it into a standard format, and produce merged reports with optional year-over-year comparison.

**Version:** 1.0.2 (see [CHANGELOG.md](CHANGELOG.md) for release notes.)

## Quick start

1. **Run the app**  
   Double-click `run_debug.bat` (or from the project folder: activate your venv and run `python main.py` or `pythonw main.py`).

2. **First run**  
   - Set a date range on the Main tab and confirm it.  
   - Configure at least one platform:
     - **Google Ads**: run `setup_auth.py` once, then add a customer in Accounts and select it on the Main tab.  
     - **Meta**: run `setup_meta_auth.py`, add `meta-ads.yaml` (or use in-app token in Settings/Meta tab).  
     - **Microsoft**: run `setup_ms_auth.py` (Web app: client_id, client_secret, redirect URI `http://localhost:8400`), add `refresh_token` and **developer_token** to `microsoft-ads.yaml`. Get developer token at ads.microsoft.com → Tools → API → Developer token.  
     - **Reddit**: run Reddit auth setup, add `reddit-ads.yaml`, then set account in Accounts.  
     - **TikTok**: add `tiktok-ads.yaml` (client_key, client_secret), run `setup_tiktok_auth.py`, then set Advertiser ID in Accounts.  
   - Use **Run Fetch** to fetch, process, and merge.

3. **Output**  
   - Output folders are configurable in **Settings → Report directories** (defaults below).  
   - Raw CSVs: `raw_reports/{platform}/` (one file per date range, e.g. `2025-01-05_2025-01-20.csv`).  
   - Processed: `processed_reports/{platform}/`.  
   - Merged: `merged_reports/` (current range + optional prior-year range).  
   - YoY: `ready_*_vs_*.csv` in `ready_reports/` when “Also pull same range previous year” is used.

## Requirements

- **Python**: 3.10+ recommended (see `requirements.txt`).  
- **Config and credentials** live in the same folder as `main.py` (e.g. `config.json`, `*-ads.yaml`, `*_favorites.json`). Run the app from the project directory or use `run_debug.bat` so it finds these files.

## Docs

- **[TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md)** — Architecture, data flow, pipeline, and components.  
- **[ROADMAP.md](ROADMAP.md)** — Security, robustness, testing, and future improvements.  
- **[PLATFORM_STATUS.md](PLATFORM_STATUS.md)** — Per-platform status and setup.  
- **[CHANGELOG.md](CHANGELOG.md)** — Version history and release notes.

## Version

Shown in the window title (e.g. `Ads Report Fetcher (Multi-Platform) v1.0.2`). Defined in `main.py` as `__version__` and in `pyproject.toml`. See [CHANGELOG.md](CHANGELOG.md) for release notes.

## Development

- **Tests**: `pytest` (from project root with venv active). Processor tests live in `tests/test_processor.py`.
- **Lint**: `ruff check .` (config in `pyproject.toml`; CI pins `ruff==0.15.20`, so use the same version locally). Optional: `mypy .` for type checking.
- **Constants**: Timeouts and dialog waits are in `constants.py`; retry settings are in each fetcher module.
