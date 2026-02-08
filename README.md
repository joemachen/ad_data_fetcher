# Ads Report Fetcher

Desktop app to pull advertising performance data from multiple platforms (Google Ads, Meta, Microsoft, Reddit, TikTok, Pinterest), process it into a standard format, and produce merged reports with optional year-over-year comparison.

## Quick start

1. **Run the app**  
   Double-click `run.bat` (or from the project folder: activate your venv and run `python main.py` or `pythonw main.py`).

2. **First run**  
   - Set a date range on the Main tab and confirm it.  
   - Configure at least one platform:
     - **Google Ads**: run `setup_auth.py` once, then add a customer in Accounts and select it on the Main tab.  
     - **Meta**: run `setup_meta_auth.py`, add `meta-ads.yaml` (or use in-app token in Settings/Meta tab).  
     - **Microsoft**: run `setup_ms_auth.py`, then add account in Accounts.  
     - **Reddit**: run the Reddit auth setup, add `reddit-ads.yaml`, then set account in Accounts.  
   - Use **Run Full Pipeline** to fetch, process, and merge.

3. **Output**  
   - Raw CSVs: `raw_reports/{platform}/` (one file per date range, e.g. `2025-01-05_2025-01-20.csv`).  
   - Processed: `processed_reports/{platform}/`.  
   - Merged: `merged_reports/` (current range + optional prior-year range).  
   - YoY: `ready_*_vs_*.csv` in the merged folder when “Also pull same range previous year” is used.

## Requirements

- **Python**: 3.10+ recommended (see `requirements.txt`).  
- **Config and credentials** live in the same folder as `main.py` (e.g. `config.json`, `*-ads.yaml`, `*_favorites.json`). Run the app from the project directory or use `run.bat` so it finds these files.

## Docs

- **[TECHNICAL_OVERVIEW.md](TECHNICAL_OVERVIEW.md)** — Architecture, data flow, pipeline, and components.  
- **[ROADMAP.md](ROADMAP.md)** — Security, robustness, testing, and future improvements.

## Version

Shown in the window title (e.g. `Ads Report Fetcher (Multi-Platform) v1.0.0`). Defined in `main.py` as `__version__`.
