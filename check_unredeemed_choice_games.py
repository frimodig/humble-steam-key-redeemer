#!/usr/bin/env python3
"""
Diagnostic script to check for unredeemed Humble Choice games.
This script will:
1. Fetch all order details
2. Identify Humble Choice months
3. Check which games are selected but not yet revealed/redeemed
4. Show a detailed report
"""

import sys
import json
from pathlib import Path

# Import from the main script
sys.path.insert(0, str(Path(__file__).parent))
from humblesteamkeysredeemer import (
    get_browser_driver, validate_session, get_choices,
    find_dict_keys, get_month_data, requests
)

def check_choice_games():
    """Check for unredeemed Humble Choice games."""
    print("=" * 70)
    print("HUMBLE CHOICE GAMES DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # Start browser
    print("Starting browser...")
    driver = get_browser_driver(headless=False)
    if not driver:
        print("ERROR: Could not start browser")
        return
    
    try:
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
            print("ERROR: Session invalid. Please log in manually first.")
            return
        
        print("✓ Session valid")
        print()
        
        # Fetch order details
        print("Fetching order details...")
        from humblesteamkeysredeemer import getHumbleOrders
        order_details = driver.execute_async_script(getHumbleOrders.replace('%optional%', '[]'))
        
        if isinstance(order_details, dict) and 'error' in order_details:
            print(f"ERROR: {order_details.get('message', 'Unknown error')}")
            return
        
        if not isinstance(order_details, list):
            print(f"ERROR: Unexpected order details format: {type(order_details)}")
            return
        
        print(f"✓ Fetched {len(order_details)} orders")
        print()
        
        # Find all Humble Choice months
        print("Analyzing Humble Choice months...")
        choice_months = [
            month for month in order_details 
            if "choice_url" in month.get("product", {})
        ]
        
        print(f"Found {len(choice_months)} Humble Choice months")
        print()
        
        # Check each month
        request_session = requests.Session()
        for cookie in driver.get_cookies():
            request_session.cookies.set(
                cookie['name'], 
                cookie['value'],
                domain=cookie['domain'].replace('www.', ''),
                path=cookie['path']
            )
        
        total_unselected = 0
        total_selected_unrevealed = 0
        total_revealed_unredeemed = 0
        
        for month in choice_months:
            month_name = month.get("product", {}).get('human_name', 'Unknown Month')
            gamekey = month.get("gamekey", "unknown")
            choices_remaining = month.get("choices_remaining", 0)
            is_v3 = month.get("product", {}).get("is_subs_v3_product", False)
            
            print(f"\n📦 {month_name} ({gamekey})")
            print(f"   Choices remaining: {choices_remaining}")
            
            try:
                # Get choice data
                month["choice_data"] = get_month_data(request_session, month)
                
                if not month["choice_data"].get('canRedeemGames', True):
                    print("   ⚠️  Cannot redeem games (expired or invalid)")
                    continue
                
                # Get chosen games
                chosen_games = set(find_dict_keys(month.get("tpkd_dict", {}), "machine_name"))
                
                # Get available choices
                v3 = not month["choice_data"].get("usesChoices", True)
                if v3:
                    identifier = "initial"
                    choice_options = month["choice_data"]["contentChoiceData"]["game_data"]
                else:
                    identifier = "initial" if "initial" in month["choice_data"]["contentChoiceData"] else "initial-classic"
                    if identifier not in month["choice_data"]["contentChoiceData"]:
                        for key in month["choice_data"]["contentChoiceData"].keys():
                            if "content_choices" in month["choice_data"]["contentChoiceData"][key]:
                                identifier = key
                                break
                    
                    choice_options = month["choice_data"]["contentChoiceData"][identifier]["content_choices"]
                
                # Find unselected games
                available_choices = [
                    game[1]
                    for game in choice_options.items()
                    if set(find_dict_keys(game[1], "machine_name")).isdisjoint(chosen_games)
                ]
                
                # Find selected but unrevealed games
                selected_unrevealed = []
                selected_revealed = []
                
                # Check all games in the month's tpkd_dict
                tpkd_dict = month.get("tpkd_dict", {})
                for tpkd_key, tpkd_data in tpkd_dict.items():
                    if isinstance(tpkd_data, dict):
                        # Check if it has a steam_app_id (selected)
                        steam_app_id = tpkd_data.get("steam_app_id")
                        if steam_app_id:
                            # Check if it has been revealed
                            if "redeemed_key_val" not in tpkd_data:
                                selected_unrevealed.append({
                                    "name": tpkd_data.get("human_name", "Unknown"),
                                    "steam_app_id": steam_app_id,
                                    "machine_name": tpkd_data.get("machine_name", "")
                                })
                            else:
                                selected_revealed.append({
                                    "name": tpkd_data.get("human_name", "Unknown"),
                                    "steam_app_id": steam_app_id,
                                    "key": tpkd_data.get("redeemed_key_val", "")
                                })
                
                # Count totals
                total_unselected += len(available_choices)
                total_selected_unrevealed += len(selected_unrevealed)
                
                # Check revealed keys against CSV files
                revealed_unredeemed_count = 0
                for game in selected_revealed:
                    key = game.get("key", "")
                    if key and key != "EXPIRED":
                        # Check if it's in redeemed.csv or already_owned.csv
                        redeemed = False
                        for csv_file in ["redeemed.csv", "already_owned.csv"]:
                            csv_path = Path(csv_file)
                            if csv_path.exists():
                                try:
                                    with open(csv_path, "r", encoding="utf-8-sig") as f:
                                        content = f.read()
                                        if key in content:
                                            redeemed = True
                                            break
                                except:
                                    pass
                        
                        if not redeemed:
                            revealed_unredeemed_count += 1
                            total_revealed_unredeemed += 1
                
                # Print summary for this month
                if len(available_choices) > 0:
                    print(f"   ⚠️  {len(available_choices)} games NOT YET SELECTED")
                    for choice in available_choices[:5]:  # Show first 5
                        print(f"      - {choice.get('title', 'Unknown')}")
                    if len(available_choices) > 5:
                        print(f"      ... and {len(available_choices) - 5} more")
                
                if len(selected_unrevealed) > 0:
                    print(f"   ⚠️  {len(selected_unrevealed)} games SELECTED but NOT REVEALED")
                    for game in selected_unrevealed[:5]:  # Show first 5
                        print(f"      - {game['name']}")
                    if len(selected_unrevealed) > 5:
                        print(f"      ... and {len(selected_unrevealed) - 5} more")
                
                if revealed_unredeemed_count > 0:
                    print(f"   ⚠️  {revealed_unredeemed_count} games REVEALED but NOT REDEEMED")
                    for game in selected_revealed:
                        key = game.get("key", "")
                        if key and key != "EXPIRED":
                            redeemed = False
                            for csv_file in ["redeemed.csv", "already_owned.csv"]:
                                csv_path = Path(csv_file)
                                if csv_path.exists():
                                    try:
                                        with open(csv_path, "r", encoding="utf-8-sig") as f:
                                            if key in f.read():
                                                redeemed = True
                                                break
                                    except:
                                        pass
                            if not redeemed:
                                print(f"      - {game['name']} (key: {key[:20]}...)")
                                if revealed_unredeemed_count <= 5:
                                    break
                
                if len(available_choices) == 0 and len(selected_unrevealed) == 0 and revealed_unredeemed_count == 0:
                    print("   ✓ All games selected and processed")
                    
            except Exception as e:
                print(f"   ❌ Error processing month: {e}")
                import traceback
                traceback.print_exc()
        
        # Final summary
        print()
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        print(f"Total Humble Choice months: {len(choice_months)}")
        print(f"Games NOT YET SELECTED: {total_unselected}")
        print(f"Games SELECTED but NOT REVEALED: {total_selected_unrevealed}")
        print(f"Games REVEALED but NOT REDEEMED: {total_revealed_unredeemed}")
        print()
        print(f"TOTAL UNREDEEMED: {total_unselected + total_selected_unrevealed + total_revealed_unredeemed}")
        print()
        
        if total_unselected > 0:
            print("⚠️  You have games that need to be SELECTED first.")
            print("   Run the script in mode 3 (Humble Choice chooser) to select them.")
        
        if total_selected_unrevealed > 0:
            print("⚠️  You have games that are SELECTED but NOT REVEALED.")
            print("   The script will reveal them automatically when you run it.")
        
        if total_revealed_unredeemed > 0:
            print("⚠️  You have games that are REVEALED but NOT REDEEMED on Steam.")
            print("   The script should redeem these automatically.")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    import time
    check_choice_games()
