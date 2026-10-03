# Platform status and next steps

Quick reference for what works, what’s pending, and what to do next.

| Platform        | Status   | Next step |
|----------------|----------|-----------|
| **Google Ads** | ✅ Working | None. Use Run Fetch with Google selected. |
| **Meta Ads**   | ✅ Working | None. Ensure token in Settings / meta-ads.yaml. |
| **Microsoft Ads** | ✅ Working | Requires **developer_token** in `microsoft-ads.yaml` (ads.microsoft.com → Tools → API → Developer token). OAuth: Web app flow — `setup_ms_auth.py` with client_id, client_secret, redirect `http://localhost:8400`. See [MICROSOFT_ADS_ADMIN_SETUP.md](MICROSOFT_ADS_ADMIN_SETUP.md). |
| **Reddit Ads** | ✅ Working | Run setup_reddit_auth; add reddit-ads.yaml. Campaign names and Cost/Revenue in fetcher. If 401, request allowlisting. Contact Reddit (Ads/Business support) to request **reporting API allowlisting** for app “Ad Data Fetcher” or your Ads account. After access is granted, run pipeline again; no code change needed. |
| **TikTok Ads**  | ✅ Working | Add `tiktok-ads.yaml` (client_key, client_secret); run `setup_tiktok_auth.py` to get tokens. See [TikTok setup](#tiktok-ads-setup). |
| **Pinterest Ads** | 📋 Stub | Fetcher is a stub. To enable: add `pinterest-ads.yaml` (see [Pinterest setup](#pinterest-ads-setup)), implement API calls in `pinterest_fetcher.py` using Pinterest Ads API. Processor already has column mapping for Pinterest. |

---

## Microsoft Ads

- **Config file:** `microsoft-ads.yaml` (client_id, client_secret, refresh_token, developer_token). developer_token is required for Reporting API—get it at ads.microsoft.com → Tools → API → Developer token.
- **Setup:** `python setup_ms_auth.py` after admin has granted consent for **Microsoft Advertising API** → `msads.manage` (and `ads.manage`) in Azure.
- **Detail:** [MICROSOFT_ADS_ADMIN_SETUP.md](MICROSOFT_ADS_ADMIN_SETUP.md).

---

## Reddit Ads (pending)

- **Config file:** `reddit-ads.yaml` (client_id, client_secret, refresh_token, redirect_uri). Updated automatically by `setup_reddit_auth.py`.
- **Setup:** Create app at **ads.reddit.com → Developer Applications**; run `python setup_reddit_auth.py`; if reports return 401, request API allowlisting from Reddit.

---

## TikTok Ads

- **Config file:** `tiktok-ads.yaml` (client_key, client_secret, access_token, refresh_token, redirect_uri). See [TikTok Marketing API](https://business-api.tiktok.com/portal/docs).
- **Setup:** Add client_key and client_secret to `tiktok-ads.yaml`, then run `python setup_tiktok_auth.py`. Authorize in the browser, then copy the full redirect URL from your browser's address bar and paste it into the prompt. The URL will contain an `auth_code` parameter — the script extracts it automatically. The script exchanges it for access_token and refresh_token. Tokens expire in 24 hours; the fetcher refreshes automatically.
- **Processor:** Maps TikTok columns (campaign_name, spend, impressions, clicks, conversion, revenue) to internal schema.

---

## Pinterest Ads (stub)

- **Config file:** `pinterest-ads.yaml` (e.g. access_token, app_id, app_secret — see [Pinterest Ads API](https://developers.pinterest.com/docs/api/v5/)).
- **Processor:** Already maps Pinterest columns (campaign_name, spend_in_micro_dollar, total_conversions) to internal schema; applies Cost ÷ 1e6 transform.
- **To enable:** Add credentials to `pinterest-ads.yaml`; implement `PinterestAdsFetcher.fetch_month_data()` in `pinterest_fetcher.py` using Pinterest Ads API.

---

*Last updated: v1.2.0 — Google (google-ads 33 / API v25), Meta, Microsoft (with developer_token), Reddit, TikTok working; Pinterest stub.*
