"""
Meta Ads API Authentication Setup
Helps generate the meta-ads.yaml credentials file.
"""

import yaml
from pathlib import Path
from typing import Dict


def get_meta_credentials() -> Dict[str, str]:
    """Prompt user for App ID, App Secret, and Access Token."""
    print("\n" + "="*60)
    print("Meta Ads API Credentials Setup")
    print("="*60 + "\n")
    
    print("Please enter your Meta Ads API credentials:")
    print("(You can find these in the Meta for Developers portal)\n")
    
    app_id = input("App ID: ").strip()
    if not app_id:
        raise ValueError("App ID is required")
    
    app_secret = input("App Secret: ").strip()
    if not app_secret:
        raise ValueError("App Secret is required")
    
    access_token = input("Access Token: ").strip()
    if not access_token:
        raise ValueError("Access Token is required")
    
    return {
        'app_id': app_id,
        'app_secret': app_secret,
        'access_token': access_token
    }


def save_meta_ads_yaml(credentials: Dict[str, str], output_path: Path = Path("meta-ads.yaml")) -> None:
    """Save credentials to meta-ads.yaml file."""
    yaml_content = {
        'app_id': credentials['app_id'],
        'app_secret': credentials['app_secret'],
        'access_token': credentials['access_token']
    }
    
    with open(output_path, 'w') as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False)
    
    print(f"\n✓ Credentials saved to: {output_path.absolute()}")
    print("\n" + "="*60)
    print("Setup Complete!")
    print("="*60)
    print(f"\nYour meta-ads.yaml file has been created at:")
    print(f"{output_path.absolute()}")
    print("\nYou can now use the Meta Ads fetcher to download reports.\n")


def main() -> None:
    """Interactive setup of Meta Ads API credentials."""
    try:
        credentials = get_meta_credentials()
        save_meta_ads_yaml(credentials)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
    except Exception as e:
        print(f"\nError: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
