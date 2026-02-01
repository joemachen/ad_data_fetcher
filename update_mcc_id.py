"""
Update MCC ID (login_customer_id) in google-ads.yaml
Helper script to add or update the login_customer_id field.
"""

import yaml
from pathlib import Path


def update_login_customer_id(mcc_id: str, yaml_path: Path = Path("google-ads.yaml")) -> None:
    """
    Update login_customer_id in google-ads.yaml file.
    
    Args:
        mcc_id: The MCC (Manager Account) ID (10-digit number)
        yaml_path: Path to google-ads.yaml file
    """
    if not yaml_path.exists():
        print(f"Error: {yaml_path} not found. Please run setup_auth.py first.")
        return
    
    # Validate MCC ID format (10 digits, optionally with dashes)
    mcc_id_clean = mcc_id.replace("-", "").replace(" ", "")
    if not mcc_id_clean.isdigit() or len(mcc_id_clean) != 10:
        print("Error: MCC ID must be a 10-digit number")
        return
    
    # Load existing YAML
    try:
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Error reading {yaml_path}: {e}")
        return
    
    # Update login_customer_id (store as string, not empty string)
    old_value = config.get('login_customer_id', '')
    # Handle empty string case (YAML might have login_customer_id: '')
    if old_value == '' or old_value is None:
        old_value_display = '(not set)'
    else:
        old_value_display = old_value
    config['login_customer_id'] = mcc_id_clean  # Store without dashes
    
    # Save updated YAML
    try:
        with open(yaml_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        if old_value_display != '(not set)':
            print(f"[OK] Updated login_customer_id from '{old_value_display}' to '{mcc_id_clean}'")
        else:
            print(f"[OK] Added login_customer_id: {mcc_id_clean}")
        print(f"Updated {yaml_path.absolute()}")
    except Exception as e:
        print(f"Error saving {yaml_path}: {e}")


def main() -> None:
    """Interactive update of MCC ID."""
    yaml_path = Path("google-ads.yaml")
    
    if not yaml_path.exists():
        print(f"Error: {yaml_path} not found. Please run setup_auth.py first.")
        return
    
    # Load current value
    try:
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f) or {}
        current_mcc = config.get('login_customer_id', '')
        # Handle empty string case
        if current_mcc == '' or current_mcc is None:
            current_mcc = '(not set)'
    except:
        current_mcc = '(unknown)'
    
    print("\n" + "="*60)
    print("Update MCC ID (login_customer_id)")
    print("="*60)
    print(f"\nCurrent login_customer_id: {current_mcc}")
    print("\nEnter your MCC (Manager Account) ID (10-digit number)")
    print("This is the ID of the account you use to access sub-accounts.")
    print("Leave blank to keep current value.\n")
    
    mcc_id = input("MCC ID: ").strip()
    
    if not mcc_id:
        print("No changes made.")
        return
    
    update_login_customer_id(mcc_id, yaml_path)


if __name__ == "__main__":
    main()
