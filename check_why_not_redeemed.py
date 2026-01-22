#!/usr/bin/env python3
"""Check why a specific game wasn't revealed/redeemed."""

import sys
import csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from humblesteamkeysredeemer import (
    get_browser_driver, validate_session, find_dict_keys,
    getHumbleOrders, try_recover_cookies, verify_logins_session
)
import time

def check_game_status(game_name):
    """Check why a game wasn't redeemed."""
    print(f"Analyzing: {game_name}\n")
    
    driver = get_browser_driver(headless=False)
    try:
        # Load saved cookies
        cookie_file = Path(".humblecookies")
        if cookie_file.exists():
            driver.get("https://www.humblebundle.com/")
            time.sleep(2)
            if try_recover_cookies(cookie_file, driver):
                time.sleep(1)
                if verify_logins_session(driver)[0]:
                    print("✓ Using saved session")
        
        driver.get("https://www.humblebundle.com/home/library")
        time.sleep(3)
        
        if not validate_session(driver):
            print("ERROR: Session invalid")
            return
        
        print("Fetching orders...")
        order_details = driver.execute_async_script(getHumbleOrders.replace('%optional%', '[]'))
        
        if isinstance(order_details, dict) and 'error' in order_details:
            print(f"ERROR: {order_details.get('message')}")
            return
        
        if not isinstance(order_details, list):
            print(f"ERROR: Unexpected format")
            return
        
        print(f"✓ Fetched {len(order_details)} orders\n")
        
        # Find the game
        game_name_lower = game_name.lower()
        game_key = None
        
        steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
        
        for key in steam_keys:
            if game_name_lower in key.get("human_name", "").lower():
                game_key = key
                break
        
        if not game_key:
            print(f"✗ {game_name} not found in orders")
            return
        
        print(f"✓ Found: {game_key.get('human_name')}")
        print(f"  Gamekey: {game_key.get('gamekey')}")
        print(f"  Steam App ID: {game_key.get('steam_app_id')}\n")
        
        # Check if revealed
        is_revealed = "redeemed_key_val" in game_key
        print(f"Status: {'REVEALED' if is_revealed else 'NOT REVEALED'}")
        
        if is_revealed:
            key_val = game_key.get("redeemed_key_val", "")
            if key_val == "EXPIRED":
                print("  → Key is EXPIRED")
            elif not key_val:
                print("  → Key revealed but empty")
            else:
                print(f"  → Key: {key_val}")
        
        # Check if in CSV files
        print("\nChecking CSV files...")
        csv_files = {
            'redeemed.csv': 'REDEEMED',
            'already_owned.csv': 'ALREADY OWNED',
            'expired.csv': 'EXPIRED',
            'errored.csv': 'ERRORED'
        }
        
        in_csv = False
        for csv_file, status in csv_files.items():
            path = Path(csv_file)
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                        if game_key.get('gamekey', '') in content:
                            print(f"  ✓ Found in {status} ({csv_file})")
                            in_csv = True
                            # Show the entry
                            reader = csv.reader(content.splitlines())
                            for row in reader:
                                if len(row) > 0 and row[0] == game_key.get('gamekey'):
                                    print(f"    Entry: {row}")
                                    break
                except Exception as e:
                    pass
        
        if not in_csv:
            print("  ✗ NOT in any CSV file")
        
        # Check if it would be filtered out
        print("\nChecking if it would be filtered...")
        
        # Check against CSV filters
        exclude_filters = ["already_owned.csv", "redeemed.csv", "expired.csv"]
        filtered_out = False
        for filter_file in exclude_filters:
            csv_path = Path(filter_file)
            if csv_path.exists():
                try:
                    with open(csv_path, "r", encoding="utf-8-sig") as f:
                        keycols = f.read()
                        filtered_keys = [keycol.strip() for keycol in keycols.replace("\n", ",").split(",")]
                        if game_key.get("redeemed_key_val", False) in filtered_keys:
                            print(f"  → Would be filtered by {filter_file}")
                            filtered_out = True
                except:
                    pass
        
        if not filtered_out and not is_revealed:
            print("  ✓ Would be included in unrevealed_keys list")
            print("\nWhy it wasn't revealed/redeemed:")
            print("  1. The script needs to be run with --auto flag (or answer 'yes' to reveal unrevealed keys)")
            print("  2. OR the script hasn't run since this game was added to your library")
            print("  3. OR there was an error during processing")
        
        # Check if it's in problematic keys
        problematic_gamekeys = set()
        errored_file = Path("errored.csv")
        if errored_file.exists():
            try:
                with open(errored_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    first_row = next(reader, None)
                    if first_row and first_row[0].lower() != "gamekey":
                        if len(first_row) >= 1:
                            problematic_gamekeys.add(first_row[0].strip())
                    for row in reader:
                        if len(row) >= 1:
                            problematic_gamekeys.add(row[0].strip())
            except:
                pass
        
        if game_key.get("gamekey", "") in problematic_gamekeys:
            print("\n  ⚠️  This game is in errored.csv - it will be retried last")
        
        input("\nPress Enter to close...")
    finally:
        driver.quit()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        game_name = " ".join(sys.argv[1:])
    else:
        game_name = "Metal Slug Tactics"
    
    check_game_status(game_name)
