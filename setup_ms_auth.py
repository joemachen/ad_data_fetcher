"""
Microsoft Ads OAuth Setup – generate initial refresh token.

Uses OAuthDesktopMobileAuthCodeGrant from the bingads library with msads.manage scope.
Run once to get a refresh_token, then copy it into your configuration (e.g. microsoft-ads.yaml).

Usage:
    python setup_ms_auth.py

Requirements:
    pip install bingads
"""

import webbrowser
from pathlib import Path
from typing import Optional

import yaml

# Default scope for Microsoft Advertising API (required for MFA compliance)
MSADS_MANAGE = "msads.manage"

try:
    from bingads.authorization import OAuthDesktopMobileAuthCodeGrant
except ImportError:
    OAuthDesktopMobileAuthCodeGrant = None


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

    if OAuthDesktopMobileAuthCodeGrant is None:
        print("Error: bingads is required. Install with: pip install bingads")
        return 1

    print()
    print("=" * 60)
    print("Microsoft Ads – OAuth refresh token setup")
    print("=" * 60)
    print()

    try:
        client_id, _client_secret = get_client_credentials()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    # Desktop/mobile flow uses no client_secret; scope defaults to msads.manage
    authentication = OAuthDesktopMobileAuthCodeGrant(
        client_id=client_id,
        env="production",
        oauth_scope=MSADS_MANAGE,
    )

    authorization_url = authentication.get_authorization_endpoint()
    print("\n" + "=" * 60)
    print("ACTION REQUIRED: If a browser did not open, copy and paste this URL:")
    print(authorization_url)
    print("=" * 60 + "\n")
    webbrowser.open(authorization_url, new=1)

    print(
        "After clicking 'Accept', you will be redirected to a URL."
    )
    print("Paste the FULL callback URL here (the entire address from the browser bar).")
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
    print()
    print("=" * 60)
    print("Success. Copy the refresh token below into your config.")
    print("=" * 60)
    print()
    print(refresh_token)
    print()
    print("Add this to microsoft-ads.yaml (or your config) as refresh_token.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
