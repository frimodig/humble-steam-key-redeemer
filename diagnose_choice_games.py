#!/usr/bin/env python3
"""
Quick diagnostic to check if Choice games are being found correctly.
Run this to see what the script sees vs what's actually available.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from humblesteamkeysredeemer import (
    get_browser_driver, validate_session, find_dict_keys, getHumbleOrders,
    try_recover_cookies, verify_logins_session
)
from pathlib import Path
import time

print("Starting browser...")
driver = get_browser_driver(headless=False)
try:
    # Try to load saved cookies first (same as main script)
    cookie_file = Path(".humblecookies")
    cookies_exist = cookie_file.exists()
    
    if cookies_exist:
        print("Loading saved session cookies...")
        driver.get("https://www.humblebundle.com/")
        time.sleep(2)  # Let cookies load
        if try_recover_cookies(cookie_file, driver):
            time.sleep(1)
            if verify_logins_session(driver)[0]:
                print("✓ Using saved Humble session")
            else:
                print("✗ Saved session expired")
                cookies_exist = False
        else:
            print("✗ Failed to load cookies")
            cookies_exist = False
    else:
        print("No saved cookies found")
    
    # Navigate to library page
    driver.get("https://www.humblebundle.com/home/library")
    time.sleep(3)
    
    # Check if we're logged in
    if not validate_session(driver):
        print("\n" + "="*60)
        print("SESSION EXPIRED - NEED TO LOG IN")
        print("="*60)
        if not cookies_exist:
            print("\nNo saved session found.")
        else:
            print("\nYour Humble Bundle session has expired.")
        print("\nPlease run the main script to log in:")
        print("  python3 humblesteamkeysredeemer.py")
        print("\nThis will save your session, then you can run this diagnostic again.")
        print("="*60)
        sys.exit(1)
    
    print("Fetching orders...")
    order_details = driver.execute_async_script(getHumbleOrders.replace('%optional%', '[]'))
    
    if isinstance(order_details, dict) and 'error' in order_details:
        error_msg = order_details.get('message', 'Unknown error')
        print(f"\nERROR: {error_msg}")
        if '401' in error_msg or '403' in error_msg or 'auth' in error_msg.lower():
            print("\nYour session expired. Please:")
            print("  1. Log in to Humble Bundle in the browser window")
            print("  2. Run this script again")
            print("\nOr run the main script to establish a new session:")
            print("  python3 humblesteamkeysredeemer.py")
        sys.exit(1)
    
    print(f"\n✓ Fetched {len(order_details)} orders\n")
    
    # What find_dict_keys sees
    steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
    print(f"find_dict_keys found: {len(steam_keys)} keys with steam_app_id")
    
    # Check Choice months
    choice_months = [m for m in order_details if "choice_url" in m.get("product", {})]
    print(f"\nFound {len(choice_months)} Humble Choice months")
    
    total_choice_games = 0
    choice_games_with_app_id = 0
    
    for month in choice_months:
        month_name = month.get("product", {}).get('human_name', 'Unknown')
        tpkd_dict = month.get("tpkd_dict", {})
        
        month_count = 0
        month_with_app_id = 0
        
        for tpkd_key, tpkd_data in tpkd_dict.items():
            if isinstance(tpkd_data, dict):
                month_count += 1
                total_choice_games += 1
                if tpkd_data.get("steam_app_id"):
                    month_with_app_id += 1
                    choice_games_with_app_id += 1
        
        if month_count > 0:
            print(f"  {month_name}: {month_count} games in tpkd_dict, {month_with_app_id} have steam_app_id")
    
    print(f"\nTotal Choice games in tpkd_dict: {total_choice_games}")
    print(f"Choice games with steam_app_id: {choice_games_with_app_id}")
    print(f"\nDifference: {total_choice_games - choice_games_with_app_id} games selected but missing steam_app_id")
    
    # Check if any Choice games are in steam_keys
    choice_in_steam_keys = 0
    for key in steam_keys:
        gamekey = key.get("gamekey", "")
        for month in choice_months:
            if month.get("gamekey") == gamekey:
                choice_in_steam_keys += 1
                break
    
    print(f"\nChoice games found in steam_keys: {choice_in_steam_keys}")
    
    # Check what's actually unredeemed
    print("\n" + "="*70)
    print("CHECKING WHAT'S ACTUALLY UNREDEEMED")
    print("="*70)
    
    # Separate revealed vs unrevealed
    revealed = []
    unrevealed = []
    for key in steam_keys:
        if "redeemed_key_val" in key:
            revealed.append(key)
        else:
            unrevealed.append(key)
    
    print(f"\nTotal steam_keys: {len(steam_keys)}")
    print(f"  - Revealed: {len(revealed)}")
    print(f"  - Unrevealed: {len(unrevealed)}")
    
    # Check CSV files to see what's already processed
    import csv
    csv_files = {
        "redeemed": "redeemed.csv",
        "already_owned": "already_owned.csv", 
        "expired": "expired.csv"
    }
    
    processed_keys = set()
    for name, filename in csv_files.items():
        csv_path = Path(filename)
        if csv_path.exists():
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                    # Extract keys (they're in the 3rd column typically)
                    lines = content.split('\n')
                    for line in lines:
                        if line.strip() and not line.startswith("gamekey"):
                            parts = line.split(',')
                            if len(parts) >= 3:
                                key_val = parts[2].strip()
                                if key_val and key_val != "EXPIRED":
                                    processed_keys.add(key_val)
            except Exception as e:
                print(f"  Error reading {filename}: {e}")
    
    print(f"\nKeys already processed (in CSV files): {len(processed_keys)}")
    
    # Count unrevealed Choice games
    unrevealed_choice = 0
    for key in unrevealed:
        gamekey = key.get("gamekey", "")
        for month in choice_months:
            if month.get("gamekey") == gamekey:
                unrevealed_choice += 1
                break
    
    print(f"\nUnrevealed Choice games: {unrevealed_choice}")
    
    # Count revealed but not in CSV
    revealed_not_processed = 0
    for key in revealed:
        key_val = key.get("redeemed_key_val", "")
        if key_val and key_val != "EXPIRED" and key_val not in processed_keys:
            revealed_not_processed += 1
    
    print(f"Revealed but NOT in CSV files: {revealed_not_processed}")
    
    # Show some examples of unrevealed games
    if len(unrevealed) > 0:
        print(f"\nFirst 10 unrevealed games:")
        for i, key in enumerate(unrevealed[:10]):
            gamekey = key.get("gamekey", "unknown")
            name = key.get("human_name", "Unknown")
            is_choice = any(m.get("gamekey") == gamekey for m in choice_months)
            choice_tag = " [Choice]" if is_choice else ""
            print(f"  {i+1}. {name}{choice_tag} ({gamekey})")
        if len(unrevealed) > 10:
            print(f"  ... and {len(unrevealed) - 10} more")
    
    if choice_games_with_app_id > choice_in_steam_keys:
        print(f"\n⚠️  ISSUE: {choice_games_with_app_id - choice_in_steam_keys} Choice games with steam_app_id are NOT in steam_keys!")
        print("   This means find_dict_keys() is missing them.")
    elif len(unrevealed) == 0 and revealed_not_processed == 0:
        print(f"\n✓ All games appear to be processed!")
        print("   If you think there are unredeemed games, they might be:")
        print("   1. Selected but not revealed (need to reveal first)")
        print("   2. In errored.csv (will be retried)")
        print("   3. Already owned on Steam")
    
    input("\nPress Enter to close...")
finally:
    driver.quit()
