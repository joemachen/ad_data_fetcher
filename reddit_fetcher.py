"""
Reddit Ads API Report Fetcher
Loads config from reddit-ads.yaml (client_id, client_secret, refresh_token).
Calls Reddit Ads API v3 "Get A Report":
  POST https://ads-api.reddit.com/api/v3/ad_accounts/{ad_account_id}/reports
  Fields: SPEND, IMPRESSIONS, CLICKS, CONVERSION_PURCHASE_CLICKS, CONVERSION_PURCHASE_VIEWS, CONVERSION_PURCHASE_TOTAL_VALUE
  Conversions = CONVERSION_PURCHASE_CLICKS + CONVERSION_PURCHASE_VIEWS (computed in fetcher).
Saves raw_reports/reddit/{month}_{year}.csv with: campaign_name, amount_spent, impressions, clicks,
  conversion_purchase_clicks, conversion_purchase_views, conversion_purchase_total_value, conversions.
"""

import base64
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Callable, Dict, Any

import pandas as pd
import yaml

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled

REDDIT_USER_AGENT = "AdsReportFetcher/1.0 (Desktop; Python)"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_REDIRECT_URI = "http://127.0.0.1:8765/reddit_oauth"

# Retries for transient API errors (5xx, 429 rate limit)
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds
RETRYABLE_HTTP_CODES = (429, 500, 502, 503, 504)

# Reddit Ads API base URLs to try (v2, v2.0, v3)
REDDIT_ADS_BASES = [
    "https://ads-api.reddit.com/api/v2.0",
    "https://ads-api.reddit.com/api/v2",
    "https://ads-api.reddit.com/api/v3",
]

# Raw CSV columns for Reddit; processor maps these to INTERNAL_SCHEMA (Campaign, Cost, Impressions, etc.)
OUTPUT_COLUMNS = [
    "campaign_name",
    "amount_spent",
    "impressions",
    "clicks",
    "conversion_purchase_clicks",
    "conversion_purchase_views",
    "conversion_purchase_total_value",
    "conversions",  # computed in fetcher: Click Purchase + View Purchase
]


class RedditAdsFetcher:
    """Fetches Reddit Ads reports via OAuth2 and Reddit Ads API v3 (Get A Report)."""

    def __init__(
        self,
        account_id: str,
        output_dir: str = "raw_reports/reddit",
        status_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_flag: Optional[object] = None,
    ):
        self.account_id = (account_id or "").strip()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.cancel_flag = cancel_flag
        self.logger = logging.getLogger(__name__)
        self._load_config()
        self._access_token: Optional[str] = None
        self._v3_me_cached: Optional[Dict[str, Any]] = None

    def _load_config(self) -> None:
        yaml_path = _APP_DIR / "reddit-ads.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError("reddit-ads.yaml not found. Add client_id, client_secret, refresh_token (run setup_reddit_auth.py).")
        with open(yaml_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f) or {}
        cid = (self.config.get("client_id") or self.config.get("app_id") or "").strip()
        self.logger.info("Reddit Ads config loaded (client_id prefix: %s)", (cid[:8] + "…") if len(cid) > 8 else cid or "missing")

    def _update_status(self, message: str) -> None:
        if self.status_callback:
            try:
                self.status_callback(message)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
        self.logger.info(f"Status: {message}")

    def _get_access_token(self) -> str:
        """Refresh and return Bearer access token."""
        if self._access_token:
            return self._access_token
        # Support both client_id/client_secret and app_id/app_secret in YAML
        client_id = (self.config.get("client_id") or self.config.get("app_id") or "").strip()
        client_secret = (self.config.get("client_secret") or self.config.get("app_secret") or "").strip()
        refresh_token = (self.config.get("refresh_token") or "").strip()
        if not client_id or not refresh_token:
            raise ValueError(
                "reddit-ads.yaml must contain client_id and refresh_token (or app_id). "
                "Run setup_reddit_auth.py and add the printed refresh_token to the file."
            )
        redirect_uri = (self.config.get("redirect_uri") or REDDIT_REDIRECT_URI).strip()
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": redirect_uri,
        }).encode("utf-8")
        req = urllib.request.Request(
            REDDIT_TOKEN_URL,
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": REDDIT_USER_AGENT},
        )
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode() if client_secret else base64.b64encode(f"{client_id}:".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.fp.read().decode() if e.fp else ""
            self.logger.error(f"Reddit token refresh failed: {e.code} {err_body}")
            if e.code == 401:
                self.logger.error(
                    "Reddit 401 Unauthorized: Check reddit-ads.yaml — use keys client_id and client_secret (not app_id/app_secret). "
                    "Ensure client_id is the string under your app name, client_secret is the 'secret', and refresh_token is the full token from setup_reddit_auth.py. "
                    "Re-run 'python setup_reddit_auth.py' to get a new refresh_token and paste it into reddit-ads.yaml."
                )
            raise RuntimeError(f"Reddit token refresh failed: {e.code}. Re-run setup_reddit_auth.py to get a new refresh_token.") from e
        token = body.get("access_token")
        if not token:
            raise RuntimeError("No access_token in Reddit response. Re-run setup_reddit_auth.py.")
        self._access_token = token
        return token

    def _headers(self) -> Dict[str, str]:
        token = self._get_access_token()
        # Reddit recommends "AppName/version (by /u/username)" for Ads API
        user_agent = REDDIT_USER_AGENT
        if self._v3_me_cached and isinstance(self._v3_me_cached.get("data"), dict):
            username = self._v3_me_cached["data"].get("reddit_username")
            if username:
                user_agent = f"AdsReportFetcher/1.0 (by /u/{username})"
        return {
            "User-Agent": user_agent,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _api_request(self, url: str, method: str = "GET", data: Optional[bytes] = None) -> Any:
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
                if data:
                    req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code in RETRYABLE_HTTP_CODES and attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF_BASE ** (attempt + 1)
                    self.logger.warning(
                        "Reddit API %s (attempt %s/%s), retrying in %ss",
                        e.code, attempt + 1, MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                else:
                    raise
            except (urllib.error.URLError, OSError) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF_BASE ** (attempt + 1)
                    self.logger.warning(
                        "Reddit API connection error (attempt %s/%s), retrying in %ss: %s",
                        attempt + 1, MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)
                else:
                    raise
        if last_error:
            raise last_error
        return None  # unreachable

    def _fetch_v3_me(self) -> Optional[Dict[str, Any]]:
        """Call GET /api/v3/me to discover profile/ad_account structure; cache result."""
        if self._v3_me_cached is not None:
            return self._v3_me_cached
        base = "https://ads-api.reddit.com/api/v3"
        try:
            raw = self._api_request(f"{base}/me")
            self._v3_me_cached = raw
            data = raw.get("data") if isinstance(raw, dict) else None
            if isinstance(data, dict):
                self.logger.info(
                    f"Reddit /api/v3/me data keys: {list(data.keys())}; "
                    f"full data (for hierarchy): {json.dumps(data, default=str)[:2000]}"
                )
            else:
                self.logger.info(f"Reddit /api/v3/me data type: {type(data).__name__}; raw sample: {json.dumps(raw, default=str)[:500]}")
            return raw
        except Exception as e:
            self.logger.debug(f"Reddit /api/v3/me failed: {e}")
            return None

    def _v3_get_a_report_body(self, start_str: str, end_str: str) -> Dict[str, Any]:
        """
        Request body for v3 "Get A Report" per docs:
        POST /api/v3/ad_accounts/{ad_account_id}/reports
        Body wrapped in "data": breakdowns, fields, starts_at, ends_at, time_zone_id.
        """
        # API requires hourly granularity: YYYY-MM-DDTHH:00:00Z (no minutes/seconds)
        starts_at = f"{start_str}T00:00:00Z"
        ends_at = f"{end_str}T23:00:00Z"
        # Breakdown by CAMPAIGN_ID; if API returns only IDs we resolve names via campaigns list
        return {
            "data": {
                "breakdowns": ["CAMPAIGN_ID"],
                "fields": [
                    "SPEND",
                    "IMPRESSIONS",
                    "CLICKS",
                    "CONVERSION_PURCHASE_CLICKS",
                    "CONVERSION_PURCHASE_VIEWS",
                    "CONVERSION_PURCHASE_TOTAL_VALUE",
                ],
                "starts_at": starts_at,
                "ends_at": ends_at,
                "time_zone_id": "GMT",
            }
        }

    def _v3_report_body(self, start_str: str, end_str: str) -> Dict[str, Any]:
        """Legacy body for other POST attempts (group_by, ad_account_id)."""
        return {
            "start_date": start_str,
            "end_date": end_str,
            "group_by": "CAMPAIGN_ID",
            "ad_account_id": self.account_id.strip(),
        }

    def _fetch_v3_get_a_report(
        self, start_str: str, end_str: str
    ) -> Tuple[Optional[List[Dict]], Optional[int]]:
        """
        Call official v3 "Get A Report": POST /api/v3/ad_accounts/{ad_account_id}/reports.
        Returns (rows, http_status). If status is 401, caller should skip fallbacks.
        """
        account_id = self.account_id.strip()
        url = f"https://ads-api.reddit.com/api/v3/ad_accounts/{account_id}/reports"
        self.logger.info(f"Reddit v3 Get A Report: POST {url} (dates {start_str} to {end_str})")
        body = self._v3_get_a_report_body(start_str, end_str)
        try:
            raw = self._api_request(url, method="POST", data=json.dumps(body).encode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = (e.fp.read().decode() if e.fp else "")[:300]
            self.logger.info(f"Reddit v3 Get A Report returned {e.code}; body={err_body}")
            if e.code == 401:
                self.logger.error(
                    "Reddit 401 Unauthorized on reports: App and token look correct but Ads API may require "
                    "allowlisting. Contact Reddit (Ads API support / business help) to request your app or "
                    "account be added to the reporting API allowlist. Also ensure ad account %s is accessible "
                    "in Business Manager (ads.reddit.com/business → Menu → Assets → Ad Accounts).",
                    account_id,
                )
            return (None, e.code)
        except Exception as e:
            self.logger.info(f"Reddit v3 Get A Report failed: {e}")
            return (None, None)
        rows = self._parse_report_response(raw, start_str, end_str)
        if rows:
            self.logger.info(f"Reddit v3 Get A Report returned {len(rows)} rows")
        else:
            if isinstance(raw, dict):
                keys = list(raw.keys())
                inner = raw.get("data")
                inner_keys = list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__
                sample = json.dumps(raw, default=str)[:500]
                self.logger.info(
                    f"Reddit v3 Get A Report returned 200 but parsed 0 rows; "
                    f"response keys={keys}; data keys={inner_keys}; sample={sample}"
                )
        return (rows, 200)

    def _v3_discover_report_paths(
        self, start_str: str, end_str: str
    ) -> List[Tuple[str, str]]:
        """
        Use v3 /me -> profiles -> businesses -> ad_accounts to build report URL paths.
        Returns list of (base_url, path) for GET.
        """
        base = "https://ads-api.reddit.com/api/v3"
        out: List[Tuple[str, str]] = []
        me = self._v3_me_cached or self._fetch_v3_me()
        if not me or not isinstance(me.get("data"), dict):
            return out
        data = me["data"]
        profile_id = data.get("id") or data.get("profile_id")
        businesses = data.get("businesses")
        if not businesses and profile_id:
            try:
                prof = self._api_request(f"{base}/profiles/{profile_id}")
                if isinstance(prof.get("data"), dict):
                    businesses = prof["data"].get("businesses")
            except Exception:
                pass
        aid = self.account_id.strip()
        if isinstance(businesses, list) and businesses:
            for b in businesses[:3]:
                bid = b.get("id") if isinstance(b, dict) else None
                if bid:
                    out.append((base, f"/businesses/{bid}/ad_accounts/{aid}/report?start_date={start_str}&end_date={end_str}&group_by=campaign"))
                    out.append((base, f"/businesses/{bid}/ad_accounts/{aid}/analytics/report?start_date={start_str}&end_date={end_str}"))
        if profile_id:
            out.append((base, f"/profiles/{profile_id}/report?start_date={start_str}&end_date={end_str}&ad_account_id={aid}"))
            out.append((base, f"/profiles/{profile_id}/ad_accounts/{aid}/report?start_date={start_str}&end_date={end_str}"))
        return out

    def _v3_discover_report_post_candidates(
        self, start_str: str, end_str: str
    ) -> List[Tuple[str, str, Dict[str, Any]]]:
        """
        Same hierarchy as _v3_discover_report_paths but path-only (no query) for POST with body.
        Returns list of (base_url, path, body).
        """
        base = "https://ads-api.reddit.com/api/v3"
        body = self._v3_report_body(start_str, end_str)
        out: List[Tuple[str, str, Dict[str, Any]]] = []
        me = self._v3_me_cached or self._fetch_v3_me()
        if not me or not isinstance(me.get("data"), dict):
            return out
        data = me["data"]
        profile_id = data.get("id") or data.get("profile_id")
        businesses = data.get("businesses")
        if not businesses and profile_id:
            try:
                prof = self._api_request(f"{base}/profiles/{profile_id}")
                if isinstance(prof.get("data"), dict):
                    businesses = prof["data"].get("businesses")
            except Exception:
                pass
        aid = self.account_id.strip()
        if isinstance(businesses, list) and businesses:
            for b in businesses[:3]:
                bid = b.get("id") if isinstance(b, dict) else None
                if bid:
                    out.append((base, f"/businesses/{bid}/ad_accounts/{aid}/report", body))
                    out.append((base, f"/businesses/{bid}/ad_accounts/{aid}/analytics/report", body))
        if profile_id:
            out.append((base, f"/profiles/{profile_id}/report", {**body, "ad_account_id": aid}))
            out.append((base, f"/profiles/{profile_id}/ad_accounts/{aid}/report", body))
        return out

    def _fetch_campaign_name_map(self) -> Dict[str, str]:
        """Fetch campaign id -> name for the ad account so we can resolve IDs in report rows. Returns {} on failure."""
        account_id = self.account_id.strip()
        if not account_id.startswith("a2_"):
            account_id = f"a2_{account_id}" if account_id.startswith("g01") else account_id
        url = f"https://ads-api.reddit.com/api/v3/ad_accounts/{account_id}/campaigns"
        try:
            raw = self._api_request(url)
            out: Dict[str, str] = {}
            data_list = raw.get("data") if isinstance(raw, dict) else None
            if isinstance(data_list, list):
                for c in data_list:
                    if isinstance(c, dict):
                        cid = c.get("id") or c.get("campaign_id") or c.get("CAMPAIGN_ID")
                        name = c.get("name") or c.get("campaign_name") or c.get("CAMPAIGN_NAME")
                        if cid and name:
                            out[str(cid)] = str(name)
            self.logger.debug("Reddit campaign name map: %s entries", len(out))
            return out
        except Exception as e:
            self.logger.debug("Reddit campaigns list failed (report may still have names): %s", e)
            return {}

    def _resolve_campaign_names(self, rows: List[Dict], name_map: Dict[str, str]) -> None:
        """Replace numeric campaign_name with resolved name from name_map (in-place)."""
        for row in rows:
            name = (row.get("campaign_name") or "").strip()
            if name and name.isdigit() and len(name) >= 10 and name in name_map:
                row["campaign_name"] = name_map[name]

    def _fetch_report_api(self, start_date: datetime, end_date: datetime) -> Optional[List[Dict]]:
        """
        Call Reddit Ads API report. Tries v3 ad_accounts first (404 on /accounts/...), then v2.0/v2.
        Returns list of row dicts with campaign_name, amount_spent, conversion.
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        # Use account_id as-is (e.g. g01qsvkpredg = ad account; t2_xxx = user account)
        account_id = self.account_id.strip()
        if not account_id.startswith("t2_") and not account_id.startswith("g01"):
            if account_id.isalnum():
                account_id = f"t2_{account_id}"
        # Call /me first so we can set User-Agent to "AppName (by /u/username)" for reports
        self._fetch_v3_me()
        # Official v3 "Get A Report": POST /api/v3/ad_accounts/{id}/reports (try first)
        rows, http_status = self._fetch_v3_get_a_report(start_str, end_str)
        if rows:
            # If report returned only campaign IDs (long numeric names), resolve to names via campaigns list
            if any((r.get("campaign_name") or "").strip().isdigit() and len((r.get("campaign_name") or "").strip()) >= 10 for r in rows):
                name_map = self._fetch_campaign_name_map()
                if name_map:
                    self._resolve_campaign_names(rows, name_map)
            return rows
        if http_status == 200:
            # v3 returned success but no rows (e.g. no ads in this date range); treat as success, don't try fallbacks
            self.logger.info("Reddit v3 reported no data for this date range; skipping fallback endpoints.")
            return []
        if http_status == 401:
            # Token not authorized for reports; skip fallbacks (they would also fail)
            return None

        # Discover v3 /me once to see structure (and so logs show what Reddit returns)
        self._fetch_v3_me()
        body = self._v3_report_body(start_str, end_str)
        body_bytes = json.dumps(body).encode("utf-8")
        first_error_logged = False

        # v3 uses POST for reports (Get A Report). Try POST first on discovered paths.
        for base_url, path, post_body in self._v3_discover_report_post_candidates(start_str, end_str):
            url = base_url.rstrip("/") + path
            try:
                raw = self._api_request(url, method="POST", data=json.dumps(post_body).encode("utf-8"))
            except urllib.error.HTTPError as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report POST (discovered) returned {e.code}; path={path[:70]}")
                    first_error_logged = True
                continue
            except Exception as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report POST (discovered) failed: {e}")
                    first_error_logged = True
                continue
            rows = self._parse_report_response(raw, start_str, end_str)
            if rows is not None and len(rows) > 0:
                return rows
            if raw and raw != [] and raw != {}:
                self.logger.info(f"Reddit API (POST discovered) returned data but no report rows; keys={list(raw.keys())[:15] if isinstance(raw, dict) else 'list'}")
        # POST to v3 fallback paths (no discovery)
        v3_base = "https://ads-api.reddit.com/api/v3"
        for path in [
            f"/ad_accounts/{account_id}/report",
            f"/ad_accounts/{account_id}/analytics/report",
            f"/ad_accounts/{account_id}/reports",
            "/report",
        ]:
            url = v3_base.rstrip("/") + path
            try:
                raw = self._api_request(url, method="POST", data=body_bytes)
            except urllib.error.HTTPError as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report POST (v3 fallback) returned {e.code}; path={path}")
                    first_error_logged = True
                continue
            except Exception as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report POST (v3 fallback) failed: {e}")
                    first_error_logged = True
                continue
            rows = self._parse_report_response(raw, start_str, end_str)
            if rows is not None and len(rows) > 0:
                return rows
            if raw and raw != [] and raw != {}:
                self.logger.info(f"Reddit API (POST v3 fallback) returned data but no report rows; keys={list(raw.keys())[:15] if isinstance(raw, dict) else 'list'}")
        # Try GET on paths derived from v3 /me (profile -> businesses -> ad_accounts)
        discovered = self._v3_discover_report_paths(start_str, end_str)
        for base_url, path in discovered:
            url = base_url.rstrip("/") + path
            try:
                raw = self._api_request(url)
            except urllib.error.HTTPError as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report GET (discovered) returned {e.code}; path={path[:70]}")
                    first_error_logged = True
                continue
            except Exception as e:
                if not first_error_logged:
                    self.logger.info(f"Reddit report GET (discovered) failed: {e}")
                    first_error_logged = True
                continue
            rows = self._parse_report_response(raw, start_str, end_str)
            if rows is not None and len(rows) > 0:
                return rows
            if raw and raw != [] and raw != {}:
                self.logger.info(f"Reddit API (discovered path) returned data but no report rows; keys={list(raw.keys())[:15] if isinstance(raw, dict) else 'list'}")
        # Fallback: try ad_accounts / accounts paths (GET)
        get_paths = [
            f"/ad_accounts/{account_id}/report?start_date={start_str}&end_date={end_str}&group_by=campaign",
            f"/ad_accounts/{account_id}/analytics/report?start_date={start_str}&end_date={end_str}",
            f"/ad_accounts/{account_id}/reports?start_date={start_str}&end_date={end_str}",
            f"/accounts/{account_id}/report?start_date={start_str}&end_date={end_str}&group_by=campaign",
            f"/accounts/{account_id}/reports?start_date={start_str}&end_date={end_str}",
            f"/accounts/{account_id}/analytics/report?start_date={start_str}&end_date={end_str}",
            f"/report?account_id={account_id}&start_date={start_str}&end_date={end_str}",
            f"/report?ad_account_id={account_id}&start_date={start_str}&end_date={end_str}",
        ]
        first_error_logged = False
        for base in REDDIT_ADS_BASES:
            for path in get_paths:
                url = base.rstrip("/") + path
                try:
                    raw = self._api_request(url)
                except urllib.error.HTTPError as e:
                    err_body = (e.fp.read().decode() if e.fp else "")[:200]
                    if not first_error_logged:
                        self.logger.info(
                            f"Reddit report GET returned {e.code}; path={path[:60]}...; body={err_body[:150]}"
                        )
                        first_error_logged = True
                    self.logger.debug(f"Reddit {base} {path} -> {e.code} {err_body}")
                    continue
                except Exception as e:
                    if not first_error_logged:
                        self.logger.info(f"Reddit report GET failed: {e}")
                        first_error_logged = True
                    self.logger.debug(f"Reddit report request failed: {e}")
                    continue
                rows = self._parse_report_response(raw, start_str, end_str)
                if rows is not None and len(rows) > 0:
                    return rows
                if raw is not None and raw != [] and raw != {}:
                    summary = list(raw.keys())[:15] if isinstance(raw, dict) else f"list(len={len(raw)})"
                    self.logger.info(f"Reddit API returned data but no report rows; response keys: {summary}; sample: {json.dumps(raw)[:300]}")
        # Try POST report with JSON body (some APIs use POST for analytics)
        body = json.dumps({
            "start_date": start_str,
            "end_date": end_str,
            "group_by": "campaign",
        }).encode("utf-8")
        for base in REDDIT_ADS_BASES:
            for path in [
                f"/ad_accounts/{account_id}/report",
                f"/ad_accounts/{account_id}/analytics/report",
                f"/accounts/{account_id}/report",
                f"/accounts/{account_id}/analytics/report",
                f"/report",
            ]:
                url = base.rstrip("/") + path
                try:
                    raw = self._api_request(url, method="POST", data=body)
                except urllib.error.HTTPError as e:
                    if not first_error_logged:
                        self.logger.info(f"Reddit report POST returned {e.code}; path={path}")
                        first_error_logged = True
                    self.logger.debug(f"Reddit POST {path} -> {e.code}")
                    continue
                except Exception as e:
                    if not first_error_logged:
                        self.logger.info(f"Reddit report POST failed: {e}")
                        first_error_logged = True
                    self.logger.debug(f"Reddit POST report failed: {e}")
                    continue
                rows = self._parse_report_response(raw, start_str, end_str)
                if rows is not None and len(rows) > 0:
                    return rows
                if raw is not None and raw != [] and raw != {}:
                    summary = list(raw.keys())[:15] if isinstance(raw, dict) else f"list(len={len(raw)})"
                    self.logger.info(f"Reddit API (POST) returned data but no report rows; response keys: {summary}")
        self.logger.warning(
            "Reddit Ads API: tried multiple report endpoints (GET/POST v2, v2.0, v3); none returned report data. "
            "Check API docs or ensure your account has reporting access."
        )
        return None

    def _parse_report_response(self, raw: Any, start_str: str, end_str: str) -> Optional[List[Dict]]:
        """Parse v3 Get A Report response into row dicts; Conversions = CONVERSION_PURCHASE_CLICKS + CONVERSION_PURCHASE_VIEWS."""
        if raw is None:
            return None
        rows = []
        data_list = None
        if isinstance(raw, list):
            data_list = raw
        elif isinstance(raw, dict):
            inner = raw.get("data")
            if isinstance(inner, dict):
                data_list = inner.get("metrics") or inner.get("rows") or inner.get("campaigns") or inner.get("items")
            if data_list is None:
                data_list = (
                    raw.get("rows") or raw.get("report_rows") or raw.get("results")
                    or raw.get("items") or raw.get("campaigns")
                    or (raw.get("report") or {}).get("rows") or (raw.get("report") or {}).get("data")
                )
            if data_list is None and isinstance(raw.get("data"), dict):
                data_list = raw["data"].get("rows") or raw["data"].get("campaigns") or raw["data"].get("items")
            if data_list is None and (raw.get("campaign_name") or raw.get("campaign_id")):
                data_list = [raw]
        if not data_list or not isinstance(data_list, list):
            return [] if raw else None
        for item in data_list:
            if not isinstance(item, dict):
                continue
            # Prefer name from breakdown (CAMPAIGN_NAME); fall back to campaign_name, name, or ID
            campaign_name = (
                item.get("CAMPAIGN_NAME") or item.get("campaign_name") or item.get("campaignName") or item.get("name")
                or str(item.get("campaign_id") or item.get("CAMPAIGN_ID") or "") or ""
            ).strip()
            amount_spent = self._to_float(
                item.get("spend") or item.get("SPEND") or item.get("amount_spent") or item.get("cost") or 0
            )
            # Reddit Ads API returns SPEND in micro-currency (1e-6); convert to dollars for display
            if amount_spent and amount_spent >= 1:
                amount_spent = amount_spent / 1_000_000
            elif amount_spent and amount_spent > 0 and amount_spent < 1e-6:
                amount_spent = amount_spent * 1_000_000
            impressions = self._to_float(
                item.get("impressions") or item.get("IMPRESSIONS") or 0
            )
            clicks = self._to_float(
                item.get("clicks") or item.get("CLICKS") or 0
            )
            conv_clicks = self._to_float(
                item.get("conversion_purchase_clicks") or item.get("CONVERSION_PURCHASE_CLICKS") or 0
            )
            conv_views = self._to_float(
                item.get("conversion_purchase_views") or item.get("CONVERSION_PURCHASE_VIEWS") or 0
            )
            conv_total_value = self._to_float(
                item.get("conversion_purchase_total_value") or item.get("CONVERSION_PURCHASE_TOTAL_VALUE") or 0
            )
            # Reddit Ads API returns CONVERSION_PURCHASE_TOTAL_VALUE in cents; convert to dollars
            if conv_total_value and conv_total_value >= 1:
                conv_total_value = conv_total_value / 100
            conversions = conv_clicks + conv_views
            rows.append({
                "campaign_name": campaign_name or "Unknown",
                "amount_spent": amount_spent,
                "impressions": impressions,
                "clicks": clicks,
                "conversion_purchase_clicks": conv_clicks,
                "conversion_purchase_views": conv_views,
                "conversion_purchase_total_value": conv_total_value,
                "conversions": conversions,
            })
        return rows if rows else None

    @staticmethod
    def _to_float(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    def fetch_month_data(self, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        self._update_status(f"Fetching Reddit Ads {start_str} to {end_str}...")
        try:
            rows = self._fetch_report_api(start_date, end_date)
            if not rows:
                self.logger.warning(f"No Reddit report data for {start_str} to {end_str}")
                return None
            df = pd.DataFrame(rows)
            for col in OUTPUT_COLUMNS:
                if col not in df.columns:
                    df[col] = "" if col == "campaign_name" else 0.0
            df = df[OUTPUT_COLUMNS].copy()
            self.logger.info(f"Fetched {len(df)} campaigns for {start_str} to {end_str}")
            return df
        except Exception as e:
            self.logger.error(f"Reddit Ads fetch failed: {e}", exc_info=True)
            self._update_status(f"Error: {e}")
            return None
