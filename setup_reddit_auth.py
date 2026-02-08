"""
Reddit Ads OAuth Setup – get refresh token for Reddit Ads API (scope: adsread).

Run once: authorize in browser, paste callback URL; the script updates reddit-ads.yaml
with the refresh_token automatically. Use duration=permanent so we get a refresh_token.

Usage:
    python setup_reddit_auth.py

Prerequisites:
    - Create an app in Reddit Ads: https://ads.reddit.com → log in → left panel
      "Developer Applications" → Create App. (Apps from reddit.com/prefs/apps
      may get 401 on Ads API; use the Ads developer portal.)
    - Put client_id (App ID) and client_secret (Secret) in reddit-ads.yaml or enter when prompted.

Redirect URI:
    - The redirect_uri must EXACTLY match the URI set in your app (Ads Developer Applications).
    - Set the same URI in BOTH: (1) Your app at ads.reddit.com → Developer Applications
      and (2) reddit-ads.yaml as redirect_uri (or enter when the script prompts).
    - If using Tailscale/ngrok: put that URL in the Reddit app, then either add
      redirect_uri: "http://your-machine.tailxxx.ts.net:PORT/reddit_oauth" to reddit-ads.yaml
      or paste it when the script asks "Redirect URI (or press Enter to keep default)".
    - Local default is http://127.0.0.1:8765/reddit_oauth; use only if that is set in the app.
"""

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

import yaml

# Default redirect URI (used only if reddit-ads.yaml has no redirect_uri).
# Reddit's form often rejects localhost and 127.0.0.1; use an HTTPS URL from ngrok instead (see docstring).
REDDIT_REDIRECT_URI_DEFAULT = "http://127.0.0.1:8765/reddit_oauth"
REDDIT_AUTH_URL = "https://www.reddit.com/api/v1/authorize"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_ADS_SCOPE = "adsread"


def load_config(yaml_path: Path) -> dict:
    if not yaml_path.exists():
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_redirect_uri(config: dict) -> str:
    """Return redirect_uri from config or default."""
    uri = (config.get("redirect_uri") or "").strip()
    return uri if uri else REDDIT_REDIRECT_URI_DEFAULT


def get_client_credentials() -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri). From reddit-ads.yaml or prompt."""
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "reddit-ads.yaml"
    config = load_config(yaml_path)
    client_id = (config.get("client_id") or "").strip()
    client_secret = (config.get("client_secret") or "").strip()
    redirect_uri = get_redirect_uri(config)
    if not client_id:
        client_id = input("Enter your Reddit app Client ID (under the app name): ").strip()
        if not client_id:
            raise SystemExit("client_id is required.")
    if not client_secret:
        client_secret = input("Enter your Reddit app Client Secret (optional for script app): ").strip()
    return client_id, client_secret, redirect_uri


def main() -> int:
    if not sys.stdin.isatty():
        print(
            "Run from a console so you can paste the callback URL.\n"
            "  Open Command Prompt / PowerShell, cd to this folder, then run:\n"
            "  python setup_reddit_auth.py",
            file=sys.stderr,
        )
        return 1

    print()
    print("=" * 60)
    print("Reddit Ads – OAuth refresh token (scope: adsread)")
    print("=" * 60)
    print()

    try:
        client_id, client_secret, redirect_uri = get_client_credentials()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    # If using default redirect_uri, offer to override (e.g. user set Tailscale/ngrok in Reddit app only)
    if redirect_uri == REDDIT_REDIRECT_URI_DEFAULT:
        print(
            "Using default redirect_uri. If you set a different URI in your Reddit app\n"
            "  (e.g. Tailscale or ngrok), enter it now – or add redirect_uri to reddit-ads.yaml."
        )
        override = input("Redirect URI (or press Enter to keep default): ").strip()
        if override:
            redirect_uri = override

    state = "reddit_ads_setup"
    params = {
        "client_id": client_id,
        "response_type": "code",
        "state": state,
        "redirect_uri": redirect_uri,
        "duration": "permanent",
        "scope": REDDIT_ADS_SCOPE,
    }
    auth_url = REDDIT_AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Redirect URI used:", redirect_uri)
    print("Scope requested: adsread (Read advertising data through my account)")
    print("Ensure this exact URI is set in your app at ads.reddit.com → Developer Applications")
    print()
    print("Opening browser for authorization...")
    webbrowser.open(auth_url, new=1)
    print()
    print("After approving, you will be redirected. Copy the FULL URL from the browser (including code=...).")
    print("If the page shows 'Connection refused', that's OK – copy the URL from the address bar.")
    print()
    try:
        callback = input("Paste the full callback URL here: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    if not callback:
        print("No URL provided.")
        return 1

    # Parse code from URL
    parsed = urllib.parse.urlparse(callback)
    qs = urllib.parse.parse_qs(parsed.query)
    if parsed.fragment:
        qs.update(urllib.parse.parse_qs(parsed.fragment))
    code_list = qs.get("code")
    code = code_list[0].strip() if code_list else None
    if not code:
        print("Could not find 'code' in the URL. Paste the full redirect URL.")
        return 1

    # Exchange code for tokens (must use same redirect_uri as in auth request)
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    req = urllib.request.Request(
        REDDIT_TOKEN_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode() if client_secret else base64.b64encode(f"{client_id}:".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        print(f"Token exchange failed: {e.code} {e.reason}")
        if e.fp:
            print(e.fp.read().decode())
        return 1
    except Exception as e:
        print(f"Request failed: {e}")
        return 1

    try:
        tokens = json.loads(body)
    except json.JSONDecodeError:
        print("Invalid response:", body[:500])
        return 1

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        print("No refresh_token in response. Did you use duration=permanent? Response:", body[:300])
        return 1

    # Update reddit-ads.yaml with refresh_token; keep or add client_id, client_secret, redirect_uri
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "reddit-ads.yaml"
    config = load_config(yaml_path)
    out = {
        "client_id": (config.get("client_id") or client_id) or "",
        "client_secret": (config.get("client_secret") or client_secret) or "",
        "redirect_uri": redirect_uri,
        "refresh_token": refresh_token,
    }
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(out, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    print()
    print("=" * 60)
    print("Success. reddit-ads.yaml has been updated with your refresh_token.")
    print("=" * 60)
    print()
    print("Updated:", yaml_path)
    print("(Token has scope 'adsread' for reading Ads API reports.)")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
