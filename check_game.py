#!/usr/bin/env python3
"""Check if a specific game has been redeemed."""

import csv
import sys
from pathlib import Path

def check_game(game_name):
    """Check if a game exists in any CSV file."""
    game_name_lower = game_name.lower()
    found = False
    
    csv_files = {
        'redeemed.csv': 'REDEEMED',
        'already_owned.csv': 'ALREADY OWNED',
        'expired.csv': 'EXPIRED',
        'errored.csv': 'ERRORED'
    }
    
    print(f"Searching for: {game_name}\n")
    
    for csv_file, status in csv_files.items():
        path = Path(csv_file)
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if len(row) >= 2:
                            name = row[1].strip()
                            if game_name_lower in name.lower():
                                print(f"✓ Found in {status} ({csv_file}):")
                                print(f"  Gamekey: {row[0] if len(row) > 0 else 'N/A'}")
                                print(f"  Name: {name}")
                                if len(row) >= 3:
                                    key = row[2].strip()
                                    if key and key != "None":
                                        print(f"  Key: {key}")
                                    else:
                                        print(f"  Key: (not revealed yet)")
                                print()
                                found = True
            except Exception as e:
                print(f"Error reading {csv_file}: {e}")
    
    if not found:
        print(f"✗ {game_name} NOT found in any CSV file")
        print("\nThis means:")
        print("  - It hasn't been processed yet")
        print("  - OR it's in your library but not yet revealed/redeemed")
        print("\nSimilar games found:")
        
        # Show similar games
        for csv_file, status in csv_files.items():
            path = Path(csv_file)
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8-sig') as f:
                        reader = csv.reader(f)
                        for row in reader:
                            if len(row) >= 2:
                                name = row[1].strip().lower()
                                # Check for partial matches
                                words = game_name_lower.split()
                                if any(word in name for word in words if len(word) > 3):
                                    print(f"  {status}: {row[1]}")
                except:
                    pass

if __name__ == "__main__":
    if len(sys.argv) > 1:
        game_name = " ".join(sys.argv[1:])
    else:
        game_name = "Metal Slug Tactics"
    
    check_game(game_name)
