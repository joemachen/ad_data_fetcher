"""
Microsoft Ads OAuth Setup – generate initial refresh token.

Uses the Web app flow (client_id + client_secret + redirect URI) so the token exchange
succeeds. Microsoft requires 'client_assertion' or 'client_secret' when exchanging
the authorization code for tokens.

Usage:
    python setup_ms_auth.py

Requirements:
    pip install bingads

Azure app registration (required):
  - Register as "Web" (not Native). Add Redirect URI: http://localhost:8400
  - Create a Client secret (Certificates & secrets). Put client_id and client_secret
    in microsoft-ads.yaml or enter when prompted.
  - API permission: MICROSOFT ADVERTISING API → msads.manage (see MICROSOFT_ADS_ADMIN_SETUP.md).
"""

import webbrowser
from pathlib import Path
from typing import Optional

import yaml

# Web redirect URI – must be added to Azure app (Web platform). User pastes full callback URL.
MS_REDIRECT_URI = "http://localhost:8400"
MSADS_MANAGE = "msads.manage"

try:
    from bingads.authorization import OAuthWebAuthCodeGrant
except ImportError:
    OAuthWebAuthCodeGrant = None


def load_config(yaml_path: Path) -> dict:
    """Load client_id and client_secret from microsoft-ads.yaml if it exists."""
    if not yaml_path.exists():
        return {}
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_client_credentials() -> tuple[str, Optional[str]]:
    """
    Return (client_id, client_secret).
    Prefer microsoft-ads.yaml; otherwise prompt or use placeholders.
    """
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "microsoft-ads.yaml"
    config = load_config(yaml_path)

    client_id = (config.get("client_id") or "").strip()
    client_secret = config.get("client_secret")
    if client_secret is not None and isinstance(client_secret, str):
        client_secret = client_secret.strip() or None
    elif client_secret is not None and not isinstance(client_secret, str):
        client_secret = None

    if not client_id:
        print("microsoft-ads.yaml not found or missing client_id.")
        client_id = input("Enter your Microsoft Ads Application (client) ID: ").strip()
        if not client_id:
            raise SystemExit("client_id is required.")
    if not client_secret:
        print("Client secret is required for the token exchange (Microsoft requires it for Web apps).")
        print("Create one in Azure Portal → App registration → Certificates & secrets.")
        client_secret = input("Enter your Microsoft Ads Client secret: ").strip() or None
    return client_id, client_secret


def main() -> int:
    import sys

    # Must run in a real console so user can paste the callback URL.
    # Double-clicking .py on Windows often uses pythonw.exe (no console).
    if not sys.stdin.isatty():
        print(
            "This script must be run from a console so you can paste the callback URL.\n"
            "  - Double-click setup_ms_auth.bat instead, or\n"
            "  - Open Command Prompt / PowerShell, cd to this folder, then run:\n"
            "    venv\\Scripts\\python.exe setup_ms_auth.py",
            file=sys.stderr,
        )
        return 1

    if OAuthWebAuthCodeGrant is None:
        print("Error: bingads is required. Install with: pip install bingads")
        return 1

    print()
    print("=" * 60)
    print("Microsoft Ads – OAuth refresh token setup (Web app flow)")
    print("=" * 60)
    print()
    print("In Azure Portal, your app must be registered as a Web app with:")
    print("  - Redirect URI: " + MS_REDIRECT_URI)
    print("  - Client secret created (Certificates & secrets)")
    print("  - API permission: MICROSOFT ADVERTISING API → msads.manage")
    print("  See MICROSOFT_ADS_ADMIN_SETUP.md if you see 'Need admin approval'.")
    print()

    try:
        client_id, client_secret = get_client_credentials()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    if not client_secret:
        print("Error: client_secret is required. Create one in Azure and add to microsoft-ads.yaml or enter above.")
        return 1

    # Web app flow: client_secret and redirect_uri required for token exchange
    authentication = OAuthWebAuthCodeGrant(
        client_id=client_id,
        client_secret=client_secret,
        redirection_uri=MS_REDIRECT_URI,
        env="production",
        oauth_scope=MSADS_MANAGE,
    )

    authorization_url = authentication.get_authorization_endpoint()
    print("\n" + "=" * 60)
    print("ACTION REQUIRED: If a browser did not open, copy and paste this URL:")
    print(authorization_url)
    print("=" * 60 + "\n")
    webbrowser.open(authorization_url, new=1)

    print("After clicking 'Accept', you will be redirected to " + MS_REDIRECT_URI)
    print("(The page may show 'This site can't be reached' – that is OK.)")
    print("Copy the FULL URL from the browser bar (it contains code=...) and paste it here.")
    print()
    try:
        response_uri = input("Full callback URL: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    if not response_uri:
        print("No URL provided. Exiting.")
        return 1

    try:
        authentication.request_oauth_tokens_by_response_uri(response_uri=response_uri)
    except Exception as e:
        print(f"Token exchange failed: {e}")
        return 1

    tokens = authentication.oauth_tokens
    if not tokens or not getattr(tokens, "refresh_token", None):
        print("No refresh_token in response. Check the callback URL and try again.")
        return 1

    refresh_token = tokens.refresh_token

    # Write the refresh token back to microsoft-ads.yaml automatically, preserving existing
    # keys (client_id, client_secret, developer_token, ...) — consistent with the Reddit and
    # TikTok setup scripts.
    app_dir = Path(__file__).resolve().parent
    yaml_path = app_dir / "microsoft-ads.yaml"
    saved = False
    try:
        config = load_config(yaml_path)
        config["client_id"] = client_id
        if client_secret:
            config["client_secret"] = client_secret
        config["refresh_token"] = refresh_token
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        saved = True
    except Exception as e:
        print(f"Could not write microsoft-ads.yaml automatically: {e}")

    print()
    print("=" * 60)
    if saved:
        print("Success. microsoft-ads.yaml has been updated with your refresh_token.")
    else:
        print("Success. Copy the refresh token below into your config.")
    print("=" * 60)
    print()
    print(refresh_token)
    print()
    if not saved:
        print("Add this to microsoft-ads.yaml (or your config) as refresh_token.")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
