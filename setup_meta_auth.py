"""
Meta Ads API Authentication Setup
Helps generate / refresh the meta-ads.yaml credentials file.

On re-authentication, the App ID and App Secret are usually unchanged and only the access
token expires. So if meta-ads.yaml already has app_id/app_secret, this script reuses them
and prompts only for a new access token. Existing keys are preserved on write.
"""

import yaml
from typing import Dict

from _app_dir import APP_DIR as _APP_DIR  # frozen-safe: resolves to exe dir when bundled

YAML_PATH = _APP_DIR / "meta-ads.yaml"


def load_existing() -> Dict[str, str]:
    """Return the current meta-ads.yaml contents (or empty dict if absent/unreadable)."""
    if not YAML_PATH.exists():
        return {}
    try:
        with open(YAML_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_meta_credentials(existing: Dict[str, str]) -> Dict[str, str]:
    """Prompt for credentials, reusing stored App ID / App Secret when present."""
    print("\n" + "=" * 60)
    print("Meta Ads API Credentials Setup")
    print("=" * 60 + "\n")

    app_id = (existing.get("app_id") or "").strip()
    app_secret = (existing.get("app_secret") or "").strip()

    if app_id and app_secret:
        print("Found existing App ID and App Secret in meta-ads.yaml — reusing them.")
        print("(You only need to paste a new Access Token.)\n")
    else:
        print("Please enter your Meta Ads API credentials:")
        print("(You can find these in the Meta for Developers portal)\n")
        if not app_id:
            app_id = input("App ID: ").strip()
            if not app_id:
                raise ValueError("App ID is required")
        if not app_secret:
            app_secret = input("App Secret: ").strip()
            if not app_secret:
                raise ValueError("App Secret is required")

    access_token = input("New Access Token: ").strip()
    if not access_token:
        raise ValueError("Access Token is required")

    return {
        "app_id": app_id,
        "app_secret": app_secret,
        "access_token": access_token,
    }


def save_meta_ads_yaml(credentials: Dict[str, str], existing: Dict[str, str]) -> None:
    """Write credentials to meta-ads.yaml, preserving any other existing keys."""
    out = dict(existing)  # keep keys we don't manage (e.g. retention settings)
    out["app_id"] = credentials["app_id"]
    out["app_secret"] = credentials["app_secret"]
    out["access_token"] = credentials["access_token"]

    with open(YAML_PATH, "w", encoding="utf-8") as f:
        yaml.dump(out, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\n✓ Credentials saved to: {YAML_PATH}")
    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("\nYou can now re-run the Meta Ads fetch.\n")


def main() -> int:
    """Interactive setup of Meta Ads API credentials."""
    try:
        existing = load_existing()
        credentials = get_meta_credentials(existing)
        save_meta_ads_yaml(credentials, existing)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        return 0
    except Exception as e:
        print(f"\nError: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
