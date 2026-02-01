"""
Google Ads API Authentication Setup Tool
Helps generate the required google-ads.yaml file with OAuth credentials.
"""

import os
import yaml
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

# OAuth 2.0 scopes required for Google Ads API
SCOPES = ['https://www.googleapis.com/auth/adwords']


def get_user_credentials() -> dict:
    """Prompt user for Client ID, Client Secret, and Developer Token."""
    print("\n" + "="*60)
    print("Google Ads API Credentials Setup")
    print("="*60 + "\n")
    
    print("Please enter your Google Ads API credentials:")
    print("(You can find these in the Google Ads API Center)\n")
    
    client_id = input("Client ID: ").strip()
    if not client_id:
        raise ValueError("Client ID is required")
    
    client_secret = input("Client Secret: ").strip()
    if not client_secret:
        raise ValueError("Client Secret is required")
    
    developer_token = input("Developer Token: ").strip()
    if not developer_token:
        raise ValueError("Developer Token is required")
    
    # Ask for MCC ID (optional)
    print("\nOptional: If you use a Manager Account (MCC) to access sub-accounts,")
    print("enter your MCC ID (10-digit number). You can add/update this later.")
    print("Leave blank if not using an MCC account.")
    mcc_id = input("MCC ID (login_customer_id): ").strip()
    
    return {
        'client_id': client_id,
        'client_secret': client_secret,
        'developer_token': developer_token,
        'mcc_id': mcc_id.replace("-", "") if mcc_id else ""
    }


def run_oauth_flow(client_id: str, client_secret: str) -> dict:
    """Run OAuth desktop flow to get refresh token."""
    print("\n" + "="*60)
    print("OAuth Authentication")
    print("="*60 + "\n")
    print("A browser window will open. Please sign in and grant access.")
    print("After you click 'Allow', this script will capture your refresh token.\n")
    
    # Configure OAuth client info
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost"]
        }
    }
    
    # Create flow
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    
    # Run the flow
    credentials = flow.run_local_server(port=0, open_browser=True)
    
    print("\n[OK] Authentication successful!\n")
    
    return {
        'refresh_token': credentials.refresh_token,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret
    }


def save_google_ads_yaml(credentials: dict, developer_token: str, mcc_id: str = "", output_path: Path = Path("google-ads.yaml")) -> None:
    """Save credentials to google-ads.yaml file."""
    yaml_content = {
        'developer_token': developer_token,
        'client_id': credentials['client_id'],
        'client_secret': credentials['client_secret'],
        'refresh_token': credentials['refresh_token'],
        'use_proto_plus': True
    }
    
    # Only include login_customer_id if provided (empty string causes validation error)
    if mcc_id and mcc_id.strip():
        yaml_content['login_customer_id'] = mcc_id.strip()
    
    with open(output_path, 'w') as f:
        yaml.dump(yaml_content, f, default_flow_style=False, sort_keys=False)
    
    print(f"✓ Credentials saved to: {output_path.absolute()}")
    print("\n" + "="*60)
    print("Setup Complete!")
    print("="*60)
    print(f"\nYour google-ads.yaml file has been created at:")
    print(f"{output_path.absolute()}")
    if mcc_id and mcc_id.strip():
        print(f"\nMCC ID (login_customer_id) set to: {mcc_id.strip()}")
    else:
        print("\nNote: MCC ID not set. If you use a Manager Account (MCC) to access")
        print("      sub-accounts, run update_mcc_id.py (or .\\update_mcc.bat) to set it later.")
    print("\nYou can now use the API fetcher to download reports.\n")


def main() -> None:
    """Main setup function."""
    try:
        # Check if google-ads.yaml already exists
        yaml_path = Path("google-ads.yaml")
        if yaml_path.exists():
            response = input(f"\n{yaml_path} already exists. Overwrite? (y/n): ").strip().lower()
            if response != 'y':
                print("Setup cancelled.")
                return
        
        # Get credentials from user
        creds = get_user_credentials()
        
        # Run OAuth flow
        oauth_creds = run_oauth_flow(creds['client_id'], creds['client_secret'])
        
        # Combine credentials
        final_creds = {
            'client_id': oauth_creds['client_id'],
            'client_secret': oauth_creds['client_secret'],
            'refresh_token': oauth_creds['refresh_token']
        }
        
        # Save to yaml file
        save_google_ads_yaml(final_creds, creds['developer_token'], creds.get('mcc_id', ''), yaml_path)
        
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
    except Exception as e:
        print(f"\n[ERROR] Error during setup: {e}")
        raise


if __name__ == "__main__":
    main()
