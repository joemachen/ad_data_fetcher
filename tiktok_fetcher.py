"""
TikTok Marketing API Report Fetcher
Loads config from tiktok-ads.yaml (client_key, client_secret, access_token, refresh_token).
Uses OAuth2 token refresh for 24-hour token expiry.
Calls TikTok Marketing API v1.3 report/integrated/get:
  GET https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/
  data_level=AUCTION_CAMPAIGN, dimensions=[stat_time_day, campaign_id], metrics=[spend, impressions, clicks, conversion, ctr, cpc]
Resolves campaign_id to campaign_name via campaigns list API.
Saves raw_reports/tiktok/YYYY-MM-DD_YYYY-MM-DD.csv with: campaign_name, spend, impressions, clicks, conversion, revenue.
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

import pandas as pd
import yaml

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled
from utils import TokenExpiredError

TIKTOK_REDIRECT_URI = "https://mabelslabels.com/tiktok-callback"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_REPORT_BASE = "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/"
TIKTOK_CAMPAIGNS_URL = "https://business-api.tiktok.com/open_api/v1.3/campaign/get/"

# Retries for transient API errors (5xx, 429)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
RETRYABLE_HTTP_CODES = (429, 500, 502, 503, 504)

# Raw CSV columns for TikTok; processor maps these to INTERNAL_SCHEMA
OUTPUT_COLUMNS = [
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "conversion",
    "revenue",
]


class TikTokAdsFetcher:
    """Fetches TikTok Ads reports via Marketing API v1.3 with OAuth2 token refresh."""

    def __init__(
        self,
        advertiser_id: str,
        output_dir: str = "raw_reports/tiktok",
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[object] = None,
    ):
        self.advertiser_id = (advertiser_id or "").strip()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        self.logger = logging.getLogger(__name__)
        # Reason the last fetch_month_data call failed (None if it succeeded or found no data)
        self.last_error: Optional[str] = None
        self._load_config()
        self._access_token: Optional[str] = None

    def _load_config(self) -> None:
        yaml_path = _APP_DIR / "tiktok-ads.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(
                "tiktok-ads.yaml not found. Add client_key, client_secret; run setup_tiktok_auth.py to get tokens."
            )
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        ck = (self.config.get("client_key") or self.config.get("app_id") or "").strip()
        self.logger.info("TikTok Ads config loaded (client_key prefix: %s)", (ck[:8] + "…") if len(ck) > 8 else ck or "missing")

    def _update_status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        self.logger.info(f"Status: {message}")

    def _get_access_token(self) -> str:
        """Refresh and return Bearer access token. Handles 24-hour expiry via refresh_token."""
        if self._access_token:
            return self._access_token
        client_key = (self.config.get("client_key") or self.config.get("app_id") or "").strip()
        client_secret = (self.config.get("client_secret") or self.config.get("app_secret") or self.config.get("secret") or "").strip()
        refresh_token = (self.config.get("refresh_token") or "").strip()
        access_token = (self.config.get("access_token") or "").strip()
        if refresh_token and client_key and client_secret:
            # Prefer refresh flow
            data = urllib.parse.urlencode({
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }).encode("utf-8")
            req = urllib.request.Request(
                TIKTOK_TOKEN_URL,
                data=data,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode())
                new_access = body.get("access_token")
                new_refresh = body.get("refresh_token")
                if new_access:
                    self._access_token = new_access
                    if new_refresh:
                        self.config["refresh_token"] = new_refresh
                        self.config["access_token"] = new_access
                        _save_config_safe(self.config)
                    return new_access
            except urllib.error.HTTPError as e:
                err_body = (e.fp.read().decode() if e.fp else "")[:300]
                self.logger.error(f"TikTok token refresh failed: {e.code} {err_body}")
                raise TokenExpiredError(f"TikTok token refresh failed: {e.code}. Re-run setup_tiktok_auth.py.", platform="TikTok") from e
            except Exception as e:
                self.logger.error(f"TikTok token refresh failed: {e}", exc_info=True)
                raise RuntimeError(f"TikTok token refresh failed: {e}") from e
        if access_token and client_key:
            self._access_token = access_token
            return access_token
        raise ValueError(
            "tiktok-ads.yaml must contain access_token and refresh_token (or run setup_tiktok_auth.py). "
            "Access tokens expire in 24 hours; refresh_token is used to obtain new ones."
        )

    def _api_request(self, url: str, method: str = "GET", data: Optional[bytes] = None, extra_headers: Optional[Dict[str, str]] = None) -> Any:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                token = self._get_access_token()
                headers = {
                    "Access-Token": token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                if extra_headers:
                    headers.update(extra_headers)
                req = urllib.request.Request(url, data=data, method=method)
                for k, v in headers.items():
                    req.add_header(k, v)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code == 401:
                    self._access_token = None
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_BACKOFF_BASE)
                        continue
                    raise TokenExpiredError("TikTok 401 Unauthorized. Token may have expired. Re-run setup_tiktok_auth.py.", platform="TikTok") from e
                if e.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF_BASE ** (attempt + 1)
                    self.logger.warning("TikTok API %s (attempt %s/%s), retrying in %ss", e.code, attempt + 1, MAX_RETRIES, delay)
                    time.sleep(delay)
                else:
                    raise
            except (urllib.error.URLError, OSError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF_BASE ** (attempt + 1)
                    self.logger.warning("TikTok API connection error (attempt %s/%s), retrying: %s", attempt + 1, MAX_RETRIES, e)
                    time.sleep(delay)
                else:
                    raise
        if last_error:
            raise last_error
        return None

    def _fetch_campaign_name_map(self) -> Dict[str, str]:
        """Fetch campaign id -> name for the advertiser. Returns {} on failure."""
        try:
            params = urllib.parse.urlencode({
                "advertiser_id": self.advertiser_id,
                "page": 1,
                "page_size": 1000,
            })
            url = f"{TIKTOK_CAMPAIGNS_URL}?{params}"
            raw = self._api_request(url)
            out: Dict[str, str] = {}
            data = raw.get("data") if isinstance(raw, dict) else None
            if isinstance(data, dict):
                campaigns = data.get("list") or data.get("campaigns") or []
            else:
                campaigns = data if isinstance(data, list) else []
            for c in campaigns if isinstance(campaigns, list) else []:
                if isinstance(c, dict):
                    cid = c.get("campaign_id") or c.get("id")
                    name = c.get("campaign_name") or c.get("name")
                    if cid and name:
                        out[str(cid)] = str(name)
            self.logger.debug("TikTok campaign name map: %s entries", len(out))
            return out
        except Exception as e:
            self.logger.debug("TikTok campaigns list failed: %s", e)
            return {}

    def _resolve_campaign_names(self, rows: List[Dict], name_map: Dict[str, str]) -> None:
        for row in rows:
            cid = (row.get("campaign_id") or "").strip()
            if cid and cid in name_map:
                row["campaign_name"] = name_map[cid]
            elif cid:
                row["campaign_name"] = cid

    def _fetch_report(self, start_date: datetime, end_date: datetime) -> Optional[List[Dict]]:
        """Call TikTok report/integrated/get; return list of row dicts."""
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        # TikTok API may expect YYYYMMDD; try both formats - docs vary
        start_compact = start_date.strftime("%Y%m%d")
        end_compact = end_date.strftime("%Y%m%d")
        params = urllib.parse.urlencode({
            "advertiser_id": self.advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_CAMPAIGN",
            "dimensions": json.dumps(["stat_time_day", "campaign_id"]),
            "metrics": json.dumps(["spend", "impressions", "clicks", "conversion", "ctr", "cpc"]),
            "start_date": start_compact,
            "end_date": end_compact,
        })
        url = f"{TIKTOK_REPORT_BASE}?{params}"
        self.logger.info("TikTok report: GET %s (dates %s to %s)", TIKTOK_REPORT_BASE[:60], start_str, end_str)
        try:
            raw = self._api_request(url)
        except Exception as e:
            self.logger.error("TikTok report failed: %s", e)
            return None
        return self._parse_report_response(raw, start_str, end_str)

    def _parse_report_response(self, raw: Any, start_str: str, end_str: str) -> Optional[List[Dict]]:
        """Parse TikTok report response into rows with campaign_name, spend, impressions, clicks, conversion, revenue."""
        if not isinstance(raw, dict):
            return None
        data = raw.get("data")
        if data is None:
            return []
        rows_data = data.get("list") or data.get("rows") or []
        if not isinstance(rows_data, list):
            return []
        rows: List[Dict] = []
        for item in rows_data:
            if not isinstance(item, dict):
                continue
            # TikTok returns dimensions and metrics at top level or nested
            cid = item.get("campaign_id") or item.get("campaign") or ""
            spend = _to_float(item.get("spend") or 0)
            impressions = _to_float(item.get("impressions") or 0)
            clicks = _to_float(item.get("clicks") or 0)
            conversion = _to_float(item.get("conversion") or 0)
            revenue = _to_float(item.get("total_purchase_value") or item.get("conversion_value") or 0)
            rows.append({
                "campaign_id": str(cid) if cid else "",
                "campaign_name": str(cid) if cid else "",
                "spend": spend,
                "impressions": impressions,
                "clicks": clicks,
                "conversion": conversion,
                "revenue": revenue,
            })
        if rows:
            name_map = self._fetch_campaign_name_map()
            if name_map:
                self._resolve_campaign_names(rows, name_map)
        return rows if rows else None

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        self.last_error = None
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        self._update_status(f"Fetching TikTok Ads {start_str} to {end_str}...")
        try:
            rows = self._fetch_report(start_date, end_date)
            if not rows:
                self.logger.warning("No TikTok report data for %s to %s", start_str, end_str)
                return None
            df = pd.DataFrame(rows)
            for col in OUTPUT_COLUMNS:
                if col not in df.columns:
                    df[col] = "" if col == "campaign_name" else 0.0
            df = df[OUTPUT_COLUMNS].copy()
            self.logger.info("Fetched %s rows for %s to %s", len(df), start_str, end_str)
            return df
        except TokenExpiredError:
            raise  # let the GUI show the Re-authenticate button
        except Exception as e:
            self.last_error = str(e)
            self.logger.error("TikTok Ads fetch failed: %s", e, exc_info=True)
            self._update_status(f"Error: {e}")
            return None


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _save_config_safe(config: Dict) -> None:
    try:
        yaml_path = _APP_DIR / "tiktok-ads.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e:
        logging.getLogger(__name__).warning("Could not save refreshed tokens to tiktok-ads.yaml: %s", e)
