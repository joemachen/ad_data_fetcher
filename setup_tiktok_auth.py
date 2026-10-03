"""
TikTok Marketing API OAuth Setup – get access_token and refresh_token.

Run once: authorize in browser, paste the authorization code from the callback URL;
the script exchanges it for tokens and updates tiktok-ads.yaml.

Usage:
    python setup_tiktok_auth.py

Prerequisites:
    - Create an app in TikTok for Business: https://business-api.tiktok.com/portal
    - Add app_id (client_key) and app_secret (client_secret) to tiktok-ads.yaml
    - Set redirect URI to https://mabelslabels.com/tiktok-callback in your TikTok app config

Redirect URI:
    - Must EXACTLY match the URI configured in your TikTok app (e.g. https://mabelslabels.com/tiktok-callback)
    - User authorizes in browser, then copies the 'code' from the callback URL and pastes it here
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import yaml

TIKTOK_REDIRECT_URI = "https://mabelslabels.com/tiktok-callback"
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
# Scope for Marketing API; ensure your app has Ads/Reporting permissions in TikTok for Business portal
TIKTOK_SCOPE = "user.info.basic"


def load_config(yaml_path: Path) -> dict:
    if not yaml_path.exists():
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_app_credentials() -> tuple[str, str]:
    """Return (client_key, client_secret). From tiktok-ads.yaml or prompt."""
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "tiktok-ads.yaml"
    config = load_config(yaml_path)
    client_key = (config.get("client_key") or config.get("app_id") or "").strip()
    client_secret = (config.get("client_secret") or config.get("app_secret") or config.get("secret") or "").strip()
    if not client_key:
        client_key = input("Enter your TikTok app Client Key (app_id): ").strip()
        if not client_key:
            raise SystemExit("client_key / app_id is required.")
    if not client_secret:
        client_secret = input("Enter your TikTok app Client Secret: ").strip()
        if not client_secret:
            raise SystemExit("client_secret is required for token exchange.")
    return client_key, client_secret


def main() -> int:
    if not sys.stdin.isatty():
        print(
            "Run from a console so you can paste the authorization code.\n"
            "  Open Command Prompt / PowerShell, cd to this folder, then run:\n"
            "  python setup_tiktok_auth.py",
            file=sys.stderr,
        )
        return 1

    print()
    print("=" * 60)
    print("TikTok Marketing API – OAuth tokens (access_token, refresh_token)")
    print("=" * 60)
    print()

    try:
        client_key, client_secret = get_app_credentials()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    state = "tiktok_ads_setup"
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": TIKTOK_SCOPE,
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "state": state,
    }
    auth_url = TIKTOK_AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Redirect URI:", TIKTOK_REDIRECT_URI)
    print("Ensure this exact URI is set in your TikTok app at business-api.tiktok.com")
    print()
    print("Opening browser for authorization...")
    webbrowser.open(auth_url, new=1)
    print()
    print("After authorizing, you will be redirected to the callback URL.")
    print("Copy the 'code' parameter from the URL (e.g. ?code=XXXXX&state=...)")
    print()
    try:
        code = input("Paste the authorization code here: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    if not code:
        print("No code provided.")
        return 1

    # If user pasted full URL, extract code
    if "code=" in code or "?" in code:
        parsed = urllib.parse.urlparse(code)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.fragment:
            qs.update(urllib.parse.parse_qs(parsed.fragment))
        code_list = qs.get("code")
        code = code_list[0].strip() if code_list else code

    # Exchange code for tokens
    data = urllib.parse.urlencode({
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": TIKTOK_REDIRECT_URI,
    }).encode("utf-8")
    req = urllib.request.Request(
        TIKTOK_TOKEN_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"Token exchange failed: {e.code} {e.reason}")
        if e.fp:
            print(e.fp.read().decode()[:500])
        return 1
    except Exception as e:
        print(f"Request failed: {e}")
        return 1

    try:
        tokens = json.loads(body)
    except json.JSONDecodeError:
        print("Invalid response:", body[:500])
        return 1

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not access_token:
        print("No access_token in response. Response:", body[:300])
        return 1

    # Update tiktok-ads.yaml
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "tiktok-ads.yaml"
    config = load_config(yaml_path)
    out = {
        "client_key": (config.get("client_key") or config.get("app_id") or client_key) or "",
        "client_secret": (
            config.get("client_secret") or config.get("app_secret") or config.get("secret") or client_secret
        )
        or "",
        "redirect_uri": TIKTOK_REDIRECT_URI,
        "access_token": access_token,
        "refresh_token": refresh_token or (config.get("refresh_token") or ""),
        "expires_in": tokens.get("expires_in"),
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(out, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print()
    print("=" * 60)
    print("Success. tiktok-ads.yaml has been updated with access_token and refresh_token.")
    print("=" * 60)
    print()
    print("Updated:", yaml_path)
    print("(Access token expires in ~24 hours; fetcher will use refresh_token to get new tokens.)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
