#!/usr/bin/env python3
"""
Simple diagnostic to check what unredeemed games the script sees.
This will help identify why Choice games might be missing.
"""

import sys
import json
from pathlib import Path

# Import from the main script
sys.path.insert(0, str(Path(__file__).parent))
from humblesteamkeysredeemer import (
    get_browser_driver, validate_session, find_dict_keys,
    getHumbleOrders, HUMBLE_SUB_PAGE, try_recover_cookies, verify_logins_session
)
import time

def analyze_orders():
    """Analyze order details to find unredeemed games."""
    print("=" * 70)
    print("CHECKING UNREDEEMED GAMES")
    print("=" * 70)
    print()
    
    # Start browser
    print("Starting browser...")
    driver = get_browser_driver(headless=False)
    if not driver:
        print("ERROR: Could not start browser")
        return
    
    try:
        # Try to load saved cookies first (same as main script)
        cookie_file = Path(".humblecookies")
        cookies_exist = cookie_file.exists()
        
        if cookies_exist:
            print("Loading saved session cookies...")
            driver.get("https://www.humblebundle.com/")
            time.sleep(2)
            if try_recover_cookies(cookie_file, driver):
                time.sleep(1)
                if verify_logins_session(driver)[0]:
                    print("✓ Using saved Humble session")
                else:
                    print("✗ Saved session expired")
        else:
            print("No saved cookies found")
        
        # Load Humble Bundle page
        print("Loading Humble Bundle library page...")
        driver.get("https://www.humblebundle.com/home/library")
        time.sleep(3)
        
        # Check for Cloudflare
        page_title = driver.title.lower()
        page_source = driver.page_source.lower()
        if any(indicator in page_title or indicator in page_source 
               for indicator in ["challenge", "cloudflare", "just a moment", "checking your browser"]):
            print("ERROR: Cloudflare challenge detected. Please run manually to solve.")
            return
        
        # Validate session
        if not validate_session(driver):
            print("\n" + "="*60)
            print("SESSION EXPIRED - NEED TO LOG IN")
            print("="*60)
            print("\nPlease run the main script to log in:")
            print("  python3 humblesteamkeysredeemer.py")
            print("\nThis will save your session, then you can run this diagnostic again.")
            print("="*60)
            return
        
        print("✓ Session valid")
        print()
        
        # Fetch order details
        print("Fetching order details...")
        order_details = driver.execute_async_script(getHumbleOrders.replace('%optional%', '[]'))
        
        if isinstance(order_details, dict) and 'error' in order_details:
            print(f"ERROR: {order_details.get('message', 'Unknown error')}")
            return
        
        if not isinstance(order_details, list):
            print(f"ERROR: Unexpected order details format: {type(order_details)}")
            return
        
        print(f"✓ Fetched {len(order_details)} orders")
        print()
        
        # Find all Steam keys (what the main script sees)
        print("Analyzing what the main script sees...")
        steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
        print(f"Total keys with steam_app_id: {len(steam_keys)}")
        
        # Separate revealed vs unrevealed
        revealed = []
        unrevealed = []
        for key in steam_keys:
            if "redeemed_key_val" in key:
                revealed.append(key)
            else:
                unrevealed.append(key)
        
        print(f"  - Revealed: {len(revealed)}")
        print(f"  - Unrevealed: {len(unrevealed)}")
        print()
        
        # Check Choice months
        print("Checking Humble Choice months...")
        choice_months = [
            month for month in order_details 
            if "choice_url" in month.get("product", {})
        ]
        print(f"Found {len(choice_months)} Humble Choice months")
        
        # Analyze each Choice month
        choice_games_selected = 0
        choice_games_unrevealed = 0
        choice_games_revealed = 0
        
        for month in choice_months:
            month_name = month.get("product", {}).get('human_name', 'Unknown')
            gamekey = month.get("gamekey", "unknown")
            tpkd_dict = month.get("tpkd_dict", {})
            
            # Count games in this month's tpkd_dict
            month_selected = 0
            month_unrevealed = 0
            month_revealed = 0
            
            for tpkd_key, tpkd_data in tpkd_dict.items():
                if isinstance(tpkd_data, dict):
                    steam_app_id = tpkd_data.get("steam_app_id")
                    if steam_app_id:
                        month_selected += 1
                        choice_games_selected += 1
                        if "redeemed_key_val" in tpkd_data:
                            month_revealed += 1
                            choice_games_revealed += 1
                        else:
                            month_unrevealed += 1
                            choice_games_unrevealed += 1
            
            if month_selected > 0:
                print(f"\n  📦 {month_name} ({gamekey})")
                print(f"     Selected games: {month_selected}")
                print(f"       - Revealed: {month_revealed}")
                print(f"       - Unrevealed: {month_unrevealed}")
                
                # Check if these games appear in steam_keys
                month_keys_in_main = []
                for key in steam_keys:
                    key_gamekey = key.get("gamekey", "")
                    if key_gamekey == gamekey:
                        month_keys_in_main.append(key)
                
                print(f"     Found in main steam_keys: {len(month_keys_in_main)}")
                if len(month_keys_in_main) != month_selected:
                    print(f"     ⚠️  MISMATCH: {month_selected} games selected but only {len(month_keys_in_main)} in main list!")
                    print(f"     This means some Choice games are NOT being detected by find_dict_keys()")
        
        print()
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Humble Choice months: {len(choice_months)}")
        print(f"Choice games selected: {choice_games_selected}")
        print(f"  - Revealed: {choice_games_revealed}")
        print(f"  - Unrevealed: {choice_games_unrevealed}")
        print()
        print(f"Main script sees: {len(steam_keys)} total keys")
        print(f"  - Revealed: {len(revealed)}")
        print(f"  - Unrevealed: {len(unrevealed)}")
        print()
        
        if choice_games_unrevealed > len(unrevealed):
            print("⚠️  ISSUE DETECTED!")
            print(f"   There are {choice_games_unrevealed} unrevealed Choice games,")
            print(f"   but the main script only sees {len(unrevealed)} unrevealed keys.")
            print(f"   This means {choice_games_unrevealed - len(unrevealed)} Choice games are MISSING!")
            print()
            print("   The issue is likely that:")
            print("   - Choice games are selected but not yet revealed")
            print("   - They exist in tpkd_dict but don't have steam_app_id yet")
            print("   - OR they're not being found by find_dict_keys()")
        
        # Check CSV files
        print()
        print("Checking CSV files...")
        csv_files = {
            "redeemed": "redeemed.csv",
            "already_owned": "already_owned.csv",
            "expired": "expired.csv",
            "errored": "errored.csv"
        }
        
        for name, filename in csv_files.items():
            csv_path = Path(filename)
            if csv_path.exists():
                try:
                    with open(csv_path, "r", encoding="utf-8-sig") as f:
                        lines = f.readlines()
                        # Subtract 1 for header if present
                        count = len([l for l in lines if l.strip() and not l.startswith("gamekey")])
                    print(f"  {name}: {count} entries")
                except Exception as e:
                    print(f"  {name}: Error reading ({e})")
            else:
                print(f"  {name}: File not found")
        
    finally:
        input("\nPress Enter to close browser...")
        driver.quit()

if __name__ == "__main__":
    analyze_orders()
