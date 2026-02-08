# Platform status and next steps

Quick reference for what works, what’s pending, and what to do next.

| Platform        | Status   | Next step |
|----------------|----------|-----------|
| **Google Ads** | ✅ Working | None. Use Run Full Pipeline with Google selected. |
| **Meta Ads**   | ✅ Working | None. Ensure token in Settings / meta-ads.yaml. |
| **Microsoft Ads** | ⏳ Pending | Admin must **Grant admin consent** for `msads.manage` (and `ads.manage`) in Azure → Ad Data Fetcher → API permissions. Then run `setup_ms_auth.py` and add `refresh_token` to `microsoft-ads.yaml`. See [MICROSOFT_ADS_ADMIN_SETUP.md](MICROSOFT_ADS_ADMIN_SETUP.md). |
| **Reddit Ads** | ⏳ Pending | Contact Reddit (Ads/Business support) to request **reporting API allowlisting** for app “Ad Data Fetcher” or your Ads account. After access is granted, run pipeline again; no code change needed. |
| **TikTok Ads**  | 📋 Stub   | Fetcher is a stub. To enable: add `tiktok-ads.yaml` (see [TikTok setup](#tiktok-ads-setup)), implement API calls in `tiktok_fetcher.py` using TikTok Marketing API. Processor already has column mapping for TikTok. |
| **Pinterest Ads** | 📋 Stub | Fetcher is a stub. To enable: add `pinterest-ads.yaml` (see [Pinterest setup](#pinterest-ads-setup)), implement API calls in `pinterest_fetcher.py` using Pinterest Ads API. Processor already has column mapping for Pinterest. |

---

## Microsoft Ads (pending)

- **Config file:** `microsoft-ads.yaml` (client_id, refresh_token; optional client_secret, developer_token).
- **Setup:** `python setup_ms_auth.py` after admin has granted consent for **Microsoft Advertising API** → `msads.manage` (and `ads.manage`) in Azure.
- **Detail:** [MICROSOFT_ADS_ADMIN_SETUP.md](MICROSOFT_ADS_ADMIN_SETUP.md).

---

## Reddit Ads (pending)

- **Config file:** `reddit-ads.yaml` (client_id, client_secret, refresh_token, redirect_uri). Updated automatically by `setup_reddit_auth.py`.
- **Setup:** Create app at **ads.reddit.com → Developer Applications**; run `python setup_reddit_auth.py`; if reports return 401, request API allowlisting from Reddit.

---

## TikTok Ads (stub)

- **Config file:** `tiktok-ads.yaml` (e.g. access_token, app_id, app_secret — see [TikTok Marketing API](https://business-api.tiktok.com/portal/docs)).
- **Processor:** Already maps TikTok columns (campaign_name, stat_cost, conversion, show_rev) to internal schema.
- **To enable:** Add credentials to `tiktok-ads.yaml`; implement `TikTokAdsFetcher.fetch_month_data()` in `tiktok_fetcher.py` using TikTok Marketing API reporting endpoints.

---

## Pinterest Ads (stub)

- **Config file:** `pinterest-ads.yaml` (e.g. access_token, app_id, app_secret — see [Pinterest Ads API](https://developers.pinterest.com/docs/api/v5/)).
- **Processor:** Already maps Pinterest columns (campaign_name, spend_in_micro_dollar, total_conversions) to internal schema; applies Cost ÷ 1e6 transform.
- **To enable:** Add credentials to `pinterest-ads.yaml`; implement `PinterestAdsFetcher.fetch_month_data()` in `pinterest_fetcher.py` using Pinterest Ads API.

---

*Last updated: pipeline run with Google, Meta, MS (config missing), Reddit (401), TikTok/Pinterest stubs.*
