# Ads Report Fetcher — Roadmap & Best Practices

Suggestions and recommendations to make the app more useful, efficient, futureproof, and professional. Use this as a living roadmap; priorities are for you to set.

---

## Where we are (as of v1.0.2)

| Phase | Status | Notes |
|-------|--------|--------|
| **Phase 1 – Solid base** | ✅ Done | Config path (`_APP_DIR`), file permissions, no sensitive logging, version in title, README, TECHNICAL_OVERVIEW. |
| **Phase 2 – Reliability** | ✅ Done | JSON/YAML error handling, Run Fetch re-enabled in `finally`, retries (Google/Microsoft/Reddit), log rotation. |
| **Phase 3 – Quality** | ✅ Done | Pytest (processor), ruff + mypy in pyproject.toml, `constants.py`. |
| **Phase 4 – Scale & polish** | 🔶 Partial | Configurable output dirs + Settings UI ✅. Per-platform pipeline progress ✅. Export/import settings not done. Split `main.py` deferred. |

---

## What’s next (suggested order)

1. **Export / Import settings** (Phase 4, Medium)  
   Export config + favorites (no secrets) to a zip or folder; import to restore or move to another machine. High value for backup and onboarding.

2. **CI** (Section 3, Low)  
   GitHub Actions: run `pytest` and optionally `ruff check` on push/PR. Keeps tests and lint in check.

3. **First-run / empty state** (Section 5, Low)  
   If no config or no platform set up, show a short checklist or “Set up at least one platform” with links to setup scripts.

4. **Optional later**  
   - **Keychain for credentials** (Section 1, Medium): store tokens in OS keychain with YAML fallback.  
   - **Split main.py** (Section 4, High): UI modules + pipeline module; improves maintainability.  
   - **Fetcher tests with mocks** (Section 3): lock in CSV shape and date-range filenames.

---

## 1. Security

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Credential storage** | YAML files in project dir (`*-ads.yaml`), gitignored. | Consider **platform keychain / credential manager** (e.g. `keyring`) for tokens and secrets so they’re not plain files. Keep YAML as fallback with a clear “store in keychain” option. | Medium |
| **Token in memory** | Meta token pasted in GUI and written to YAML; no explicit wipe. | Avoid keeping token in `StringVar` longer than needed; clear after save. Optionally mask token entry (e.g. `show="•"`). | Low |
| **File permissions** | YAML/config written with default umask. | On first write, set **restrictive permissions** on `*-ads.yaml` and `config.json` (e.g. `os.chmod(path, 0o600)`) so only the owner can read. | Low |
| **Sensitive logging** | Logs may contain IDs and paths. | **Never log** tokens, full API keys, or passwords. Sanitize IDs in log messages (e.g. last 4 digits). Review `app_debug.log` usage. | Low |
| **Config path** | `config.json` and favorites under CWD. | Resolve all config paths from **one app root** (e.g. `_APP_DIR` or `%APPDATA%/AdsReportFetcher`) so behavior doesn’t depend on where the user runs the app. | Medium |

---

## 2. Robustness & Error Handling

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Config path consistency** | `settings_file = Path("config.json")` vs `_APP_DIR` for YAML. | Use **single app data directory** (e.g. `_APP_DIR` or XDG/APPDATA) for `config.json`, favorites, and optional `*-ads.yaml` so paths are consistent and portable. | Medium |
| **JSON/YAML load** | `json.load` / `yaml.safe_load` with broad `except`. | Use **specific exceptions** (`json.JSONDecodeError`, `yaml.YAMLError`), log with traceback, and show a user-friendly message (e.g. “Config file is corrupted; backup or delete and restart”). | Low |
| **File I/O** | Many `open()` without explicit encoding in a few places. | Use **`encoding="utf-8"`** and **`with`** everywhere; consider a small helper (e.g. `load_json(path)`, `save_json(path, data)`) for consistency and one place to add error handling. | Low |
| **Thread errors** | Worker threads catch and report via status; some paths may not update UI. | Ensure **every** worker path calls `root.after(0, ...)` for final status and button state so the UI never stays “stuck” (e.g. disabled Run button) after an error. | Low |
| **Retries** | Meta has rate-limit retries; others mostly don’t. | Add **configurable retries with backoff** for transient API errors (5xx, rate limits) for Google, Microsoft, Reddit where applicable. | Medium |

---

## 3. Testing

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Automated tests** | No tests in repo. | Add **pytest** (or unittest). Start with: (1) **Processor**: `_parse_range_from_filename`, `_parse_month_year_from_range_filename`, column order in YoY output; (2) **Fetchers**: mock API responses, assert CSV columns and date range in filename. | Medium |
| **CI** | None. | Add **GitHub Actions** (or similar): run tests, optional lint (ruff/flake8, mypy). Block merge on test failure. | Low |
| **Integration / E2E** | Manual only. | Later: optional **smoke test** (e.g. “start app, load Main tab, no crash”) or minimal E2E with a test config. | High |

---

## 4. Code Quality & Maintainability

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **main.py size** | ~4,500+ lines. | **Split by concern**: e.g. `ui_main_tab.py`, `ui_accounts_tab.py`, `ui_settings_tab.py`, `pipeline.py` (fetch/process/merge orchestration), `settings_storage.py`. Keep `main.py` as thin entry point and wiring. | High |
| **Magic numbers** | Timeouts (300, 3600), retries (10), etc. | Move to **named constants** or a small `constants.py` / config section so they’re easy to tune and document. | Low |
| **Type hints** | Partial. | Add **type hints** to all public functions and key internals; run **mypy** in CI to catch misuse and improve IDE support. | Medium |
| **Linting** | Ad hoc. | Standardize on **ruff** (or flake8 + black) and **format on save** so style is consistent. | Low |
| **Duplication** | Repeated “platform row” logic (favorites, defaults). | Keep using small helpers (e.g. `add_platform_row`) and, where it helps, **data-driven** platform lists (list of platform keys + display names) to avoid copy-paste. | Low |

---

## 5. User Experience & Professional Polish

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Progress feedback** | Status text, pipeline progress bar, and **per-platform progress** (e.g. “Google: 2/2, Meta: 1/2…”) in header during Run Fetch. | Optional: **estimated time** where feasible. | Low |
| **Cancellation** | Google/Meta support cancel; others may not. | Ensure **all** fetch threads respect a shared cancel flag and that “stop” is visible and works for the full pipeline. | Low–Medium |
| **Empty state** | User may open app with no config. | **First-run flow**: e.g. “No config found. Set up at least one platform (Google or Meta) to get started” with links to setup scripts or a short in-app checklist. | Low |
| **Export / backup** | Config and favorites are local files. | Add **Export settings** (config + favorites, no secrets) and **Import** so users can backup or move to another machine. Optionally “Export without credentials”. | Medium |
| **Accessibility** | Not assessed. | Ensure **keyboard navigation** (Tab, Enter) and **contrast** for status and errors; avoid relying only on color. | Low |
| **Version & updates** | No visible version. | Show **version** in window title or About (e.g. from `__version__` or `pyproject.toml`). Enables “what version are you on?” support. | Low |

---

## 6. Performance & Efficiency

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Large CSVs** | Full load with pandas. | For very large files, consider **chunked read** or **streaming** in the processor so memory stays bounded; optional “sample first N rows” for preview. | Medium |
| **UI freeze** | Heavy work in threads; log via queue. | Keep **all** I/O and API calls off the main thread; double-check that no `to_csv`/`read_csv` runs on the GUI thread. | Low (audit) |
| **Startup** | Load config and favorites at startup. | Defer **non-critical** loads (e.g. mappings.json when user opens Settings) if startup feels slow; keep date range and account list fast. | Low |
| **Dependencies** | requirements.txt, broad versions. | Pin **exact versions** in production (e.g. `requirements.txt` or `pip freeze`) and document upgrade path; optional **pyproject.toml** for a single source of truth. | Low |

---

## 7. Futureproofing & Operations

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **Python version** | Not pinned. | Set **minimum Python** (e.g. 3.10) in docs and CI; add `python_requires` in `pyproject.toml` if you add one. | Low |
| **API versions** | Meta v18.0, etc. in code. | Centralize **API version** (and base URLs) in config or constants so upgrades (e.g. Meta Graph API version) are one-place changes. | Low |
| **Logging** | File + console; basic format. | Add **log rotation** (e.g. `RotatingFileHandler`) so `app_debug.log` doesn’t grow forever. Optional **log level** in config. | Low |
| **Ready report location** | `ready_reports/` next to app. | Allow **configurable output directory** (e.g. in config.json) so users can send reports to a shared drive or folder. | Medium |
| **Platform additions** | New platform = new fetcher + wiring in main. | Keep **platform-agnostic** processor and a clear “add platform” checklist (fetcher interface, config file, favorites, main.py wiring) in TECHNICAL_OVERVIEW or CONTRIBUTING. | Low (docs) |

---

## 8. Documentation & Onboarding

| Item | Current state | Recommendation | Effort |
|------|----------------|----------------|--------|
| **TECHNICAL_OVERVIEW** | Good high-level description. | Update it for **range-based** fetch, **ready report** naming (YYYY-MM-DD, actual years in headers), and **no Ad-Hoc tab**. Add a one-page “Data flow” diagram (text or Mermaid). | Low |
| **README** | Not present in list. | Add **README.md**: what the app does, how to run (`run.bat` / venv), link to TECHNICAL_OVERVIEW and PLATFORM_STATUS, and “First run” steps. | Low |
| **Setup scripts** | Separate scripts per platform. | Document **order of setup** (Google → Meta → Microsoft → Reddit) and any **prerequisites** (accounts, app creation). Consider a single `setup.py` or `setup.sh` that runs the right script per platform. | Low |
| **Changelog** | ✅ CHANGELOG.md added. | Keep updating **CHANGELOG.md** for each version bump. | Low |

---

## 9. Quick Wins (Low Effort, High Value)

- Restrict permissions on `*-ads.yaml` and `config.json` on first write (`chmod 0o600`).
- Resolve `config.json` and favorites paths from `_APP_DIR` (or a single app-data dir) so behavior doesn’t depend on CWD.
- Add `__version__` and show it in the window title or About.
- Add `README.md` with run instructions and link to TECHNICAL_OVERVIEW.
- Pin and document minimum Python version; add log rotation for `app_debug.log`.
- Ensure no tokens or secrets are ever logged; sanitize IDs in log messages.

---

## 10. Suggested Roadmap Order

1. **Phase 1 – Solid base** ✅ Done  
   Config path consistency, file permissions, no sensitive logging, version visible, README, TECHNICAL_OVERVIEW update.

2. **Phase 2 – Reliability** ✅ Done  
   Specific JSON/YAML error handling, thread error handling audit (Run Fetch re-enabled in `finally`), retries for Google/Microsoft/Reddit APIs, log rotation (RotatingFileHandler).

3. **Phase 3 – Quality** ✅ Done  
   Pytest for processor (`tests/test_processor.py`), ruff + mypy in `pyproject.toml`, constants for timeouts/retries (`constants.py`).

4. **Phase 4 – Scale & polish** (partial)  
   Configurable output dir ✅ (config.json + Settings UI). Per-platform pipeline progress ✅ (v1.0.1). Cleanup in v1.0.2 (dead code, logging, constants, launcher). Export/import settings still open. Split `main.py` deferred. See [CHANGELOG.md](CHANGELOG.md) for release notes.

Use this list as a checklist; re-prioritize based on how you use the app and who else might use it.
