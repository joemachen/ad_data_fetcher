# Code Audit — Architecture, Resilience & Hygiene

*Audit date: 2026-10-03 · Codebase version 1.1.0*

This audit started from a generic "principal-engineer" review prompt. Some of that prompt's directives don't fit a desktop Tk application, so this document covers two things:

1. Which directives don't fit, and why (§1).
2. The findings that do apply, ranked P0–P3, with a refactoring order (§2–§3).

---

## 1. Directives that don't fit this project

| Directive | Verdict | Reasoning |
|---|---|---|
| Audit the "CSV exporter module" | Wrong target | There is no exporter module. YoY CSVs are built by `ReportProcessor.build_yoy_reports` in `processor.py`. |
| Load secrets strictly from environment variables (`.env` / Pydantic Settings) | Doesn't fit | This is a desktop EXE for non-developers. The OAuth setup scripts write tokens to `*-ads.yaml`, and the fetchers write rotated tokens back: Microsoft refresh-token rotation, and TikTok's 24h refresh. A process can't write back to its environment variables, so token rotation would break. The current approach is sound: YAML files are gitignored, written with 0o600 permissions, IDs are masked in logs, and tokens are never logged. The upgrade that fits is the OS keychain (`keyring`) with YAML as a fallback, which is already in ROADMAP §1. |
| Use `asyncio` for concurrent fetching | Doesn't fit | The Google Ads, Meta and Microsoft SDKs are synchronous, and the GUI is built on Tk plus threads. If cross-platform parallelism is ever wanted, `concurrent.futures.ThreadPoolExecutor` is the right tool. It's P3, because the batch loop depends on per-platform completion Events and an ordered progress display. |
| Validate each row with a Pydantic model before building the DataFrame | Overkill | Field normalisation is already declarative (`PLATFORM_CONFIG` column mappings plus `_validate_and_fill_schema`). Per-row models would add a dependency and slow things down for no gain. A `TypedDict` for `PLATFORM_CONFIG` would be enough. |
| Stream oversized datasets to bound memory | Not a real risk | Reports are campaign-level aggregates over a date range, typically tens to hundreds of rows. |
| Replace every `print()` with logging | Mostly misapplied | Nearly all `print()` calls are in the interactive CLI setup scripts (`setup_*.py`, `update_mcc_id.py`), where console output is correct. The real cases are the two error prints in `config_manager.py`. |
| Rename to `fetch_performance_data()` | Optional | All fetchers already share `fetch_month_data(start_date, end_date) -> Optional[pd.DataFrame]`. The name is outdated, since it takes any range rather than a month. Rename it only together with the shared base class (P1). |

---

## 2. Executive summary (ranked)

### P0 — Fixed in this change
- **The YoY ready-report column order was wrong.** It wrote all current-year metrics, then all prior-year metrics, contradicting TECHNICAL_OVERVIEW. The only test that covered it checked a copy of the list built inside the test, so it could never fail. *Fix:* `processor.interleave_period_columns()` plus real tests.

### P1
- ✅ *Fixed in this change.* **The CI lint step fails on the current codebase.** `ruff check .` (latest ruff, which CI installs unpinned) reports about 680 findings, mostly whitespace, import order and line length. Either run `ruff check --fix .` once and pin the ruff version, or relax the rules. Until then the lint gate can't catch new issues. The `pyproject.toml` ruff settings also use the deprecated top-level `select` key, which should become `[tool.ruff.lint]`.
- **`main.py` is about 4.3k lines with per-platform copy-paste.** The methods `start_google_fetch_thread`, `start_meta_fetch_thread`, `_run_ms_fetch_thread`, `_run_tiktok_fetch_thread`, `_run_reddit_fetch_thread` and the `start_*_processing_thread` variants all repeat the same steps: build the fetcher, fetch the current range, optionally fetch the prior-year range, save, and set the completion Event. `_execute_batch_fetch` picks a platform with `if/elif` on display names.
- **There's no shared fetcher contract.** The fetchers line up only because their method names match. Adding a `BaseAdsFetcher` ABC or `Protocol` (`platform_key`, `fetch_month_data`, `save`), plus a platform registry, would let the duplicated thread methods collapse into one generic runner. Pinterest, currently a stub, should implement it too.

### P2
- **Retry/backoff logic is copied five times** (`api_fetcher.py`, `meta_fetcher.py`, `microsoft_fetcher.py`, `reddit_fetcher.py`, `tiktok_fetcher.py`). None of the copies add jitter or honour `Retry-After`. TikTok's API-code retry path sleeps a fixed 2s. Replace them with one helper, e.g. `utils.retry_with_backoff(fn, is_retryable, max_attempts, base)`, using full jitter and `Retry-After` support. Reddit and TikTok each also hand-roll their own `urllib` request wrapper, which a shared helper could replace.
- **There are many broad `except Exception` handlers** (main.py ≈23, reddit ≈12, processor ≈10). Handlers at thread boundaries are fine. Elsewhere, narrow them (e.g. `_save_mappings`, the YoY CSV read) and log the HTTP status code and platform request ID where the API provides one.
- **mypy is configured but not enforced.** CI runs only ruff and pytest. Add a mypy step for `processor.py`, `utils.py` and the fetchers, leaving `main.py` out for now. There is one existing error: an unannotated `results` in `process_all`.

### P3
- **Legacy fallback code in the processor:**
  - Filename-prefix platform detection in `_get_platform_config` (a `meta_` prefix, otherwise Google). Only range-named files are scanned now.
  - The `'campaign' in raw_col` heuristic for filling missing raw columns.
- **Version strings disagree.** README and PLATFORM_STATUS say 1.0.2, while `main.py` and `pyproject.toml` say 1.1.0.
- **`config_manager.py` prints errors instead of logging them.**
- **Optional:** parallel cross-platform fetching with a ThreadPoolExecutor; OS keychain storage for credentials.

---

## 3. Refactoring strategy (one PR per step)

1. ✅ YoY metric interleaving plus real tests.
2. ✅ Make CI lint meaningful: pin ruff, run a one-time autofix, and move the ruff settings to `[tool.ruff.lint]`.
3. Shared retry helper with jitter and `Retry-After`, applied to all fetchers, with mocked-response tests.
4. `BaseAdsFetcher` ABC and a platform registry; fold the per-platform thread methods in `main.py` into one generic runner.
5. Split `main.py` into UI modules and a pipeline module (ROADMAP §4).
6. Add mypy to CI; narrow the exception handlers; remove the legacy fallbacks.
7. Optional: keychain storage for credentials, parallel fetch.
