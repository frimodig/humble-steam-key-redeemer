#!/usr/bin/env python3
"""Find a specific game in Humble Bundle orders."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from humblesteamkeysredeemer import (
    get_browser_driver, validate_session, find_dict_keys,
    getHumbleOrders, try_recover_cookies, verify_logins_session
)
import time

def find_game(game_name):
    """Find a game in order details."""
    print(f"Searching for: {game_name}\n")
    
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
        
        # Search for the game
        game_name_lower = game_name.lower()
        found = False
        
        # Search in all steam keys
        steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
        print(f"Searching through {len(steam_keys)} Steam keys...\n")
        
        for key in steam_keys:
            name = key.get("human_name", "").lower()
            if game_name_lower in name:
                found = True
                print(f"✓ FOUND!")
                print(f"  Name: {key.get('human_name', 'Unknown')}")
                print(f"  Gamekey: {key.get('gamekey', 'Unknown')}")
                print(f"  Steam App ID: {key.get('steam_app_id', 'Unknown')}")
                
                if "redeemed_key_val" in key:
                    key_val = key.get("redeemed_key_val", "")
                    if key_val and key_val != "EXPIRED":
                        print(f"  Status: REVEALED (key: {key_val})")
                    elif key_val == "EXPIRED":
                        print(f"  Status: EXPIRED")
                    else:
                        print(f"  Status: REVEALED (no key value)")
                else:
                    print(f"  Status: NOT REVEALED YET")
                
                # Check which order it's from
                for order in order_details:
                    if order.get("gamekey") == key.get("gamekey"):
                        order_name = order.get("product", {}).get("human_name", "Unknown")
                        print(f"  Order: {order_name}")
                        
                        # Check if it's a Choice month
                        if "choice_url" in order.get("product", {}):
                            print(f"  Type: Humble Choice")
                        break
                
                print()
        
        if not found:
            print(f"✗ {game_name} NOT found in your orders")
            print("\nThis could mean:")
            print("  1. It hasn't been selected from a Choice month yet")
            print("  2. It's from a bundle you haven't purchased")
            print("  3. The name might be slightly different")
            print("\nSearching for similar names...")
            
            # Show similar games
            similar = []
            for key in steam_keys:
                name = key.get("human_name", "").lower()
                words = game_name_lower.split()
                if any(word in name for word in words if len(word) > 3):
                    similar.append(key.get("human_name", "Unknown"))
            
            if similar:
                print("\nSimilar games found:")
                for name in set(similar)[:10]:
                    print(f"  - {name}")
        
        input("\nPress Enter to close...")
    finally:
        driver.quit()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        game_name = " ".join(sys.argv[1:])
    else:
        game_name = "Metal Slug Tactics"
    
    find_game(game_name)
