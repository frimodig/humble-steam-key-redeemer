#!/usr/bin/env python3
"""
Clean up errored.csv by removing duplicates.
Keeps the first occurrence of each (gamekey, name) combination.
If multiple entries exist with different key values, keeps the one with a valid key.
"""
import csv
from pathlib import Path

def cleanup_errored_csv():
    """Remove duplicates from errored.csv, preferring entries with valid keys."""
    errored_file = Path("errored.csv")
    
    if not errored_file.exists():
        print("errored.csv not found")
        return
    
    # Read all entries
    entries = []
    with errored_file.open("r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 3:
                entries.append({
                    'gamekey': row[0].strip(),
                    'name': row[1].strip(),
                    'key_val': row[2].strip()
                })
    
    print(f"Found {len(entries)} total entries")
    
    # Deduplicate: keep best entry for each (gamekey, name) combination
    def valid_steam_key(key):
        """Check if key is valid Steam key format."""
        if not isinstance(key, str) or not key:
            return False
        key_parts = key.split("-")
        return (
            len(key) == 17
            and len(key_parts) == 3
            and all(len(part) == 5 for part in key_parts)
        )
    
    seen = {}  # (gamekey, name) -> best entry
    for entry in entries:
        key_id = (entry['gamekey'], entry['name'].lower())
        key_val = entry['key_val']
        
        if key_id not in seen:
            # First occurrence - keep it
            seen[key_id] = entry
        else:
            # Already seen - keep the better one
            existing = seen[key_id]
            existing_val = existing['key_val']
            
            # Prefer valid keys over empty/invalid ones
            if not valid_steam_key(existing_val) and valid_steam_key(key_val):
                seen[key_id] = entry
            # If both are invalid or both are valid, keep the first one
    
    # Write deduplicated entries back
    unique_entries = list(seen.values())
    print(f"After deduplication: {len(unique_entries)} unique entries")
    print(f"Removed {len(entries) - len(unique_entries)} duplicates")
    
    # Backup original file
    backup_file = errored_file.with_suffix('.csv.backup')
    errored_file.rename(backup_file)
    print(f"Backed up original to {backup_file}")
    
    # Write cleaned file
    with errored_file.open("w", encoding="utf-8-sig", newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['gamekey', 'human_name', 'redeemed_key_val'])  # Header
        for entry in unique_entries:
            writer.writerow([entry['gamekey'], entry['name'], entry['key_val']])
    
    print(f"✓ Cleaned errored.csv written")
    print(f"✓ Original backed up to {backup_file}")

if __name__ == "__main__":
    cleanup_errored_csv()
