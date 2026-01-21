# Humble Steam Key Redeemer

Python utility script to extract Humble keys, and redeem them on Steam automagically by detecting when a game is already owned on Steam.

This is primarily designed to be a set-it-and-forget-it tool that maximizes successful entry of keys into Steam, assuring that no Steam game goes unredeemed.

This script will login to both Humble and Steam, automating the whole process. It's not perfect as I made this mostly for my own personal case and couldn't test all possibilities so YMMV. Feel free to send submit an issue if you do bump into issues.

Any revealing and redeeming the script does will output to spreadsheet files based on their actions for you to easily review what actions it took and whether it redeemed, skipped, or failed on specific keys.

---

## Fork Improvements

This fork includes several improvements over the original project:

### Automatic Browser Detection
- **Auto-detects installed browsers** (Chrome, Chromium, Brave, Firefox, Edge, Opera, Vivaldi)
- **Uses `webdriver-manager`** to automatically download and manage browser drivers
- No more manual WebDriver installation required
- Works across macOS, Linux, and Windows

### Daemon Mode for Unattended Operation
- **Auto-restart on crashes** - Script automatically restarts if it times out or crashes
- **`--auto` flag** - Automatically answers prompts for hands-off operation
- **Stale cookie detection** - Cleanly exits (instead of hanging) when login sessions expire
- **Statistics tracking** - See how many keys have been redeemed, errored, expired, etc.

Run the daemon:
```bash
# First, login manually once:
python3 humblesteamkeysredeemer.py

# Then run the daemon:
./run_daemon.sh

# Or run in background (survives terminal close):
./run_daemon.sh --background

# Check progress anytime:
./run_daemon.sh --stats
```

### Improved Reliability
- **Steam API retry logic** - Handles transient API failures gracefully
- **Session keep-alive** - Prevents browser session timeouts during long operations
- **Expired key handling** - Detects and skips expired keys (logs to `expired.csv`)
- **Better error messages** - Clear instructions when things go wrong

### Enhanced Steam App Fetching
- Incorporates improvements from [DIASILEDU's PR #55](https://github.com/FailSpy/humble-steam-key-redeemer/pull/55)
- Paginated fetching of all Steam apps
- Parallel fetching of missing app details
- Better Steam Web API key management

---

## Modes

### Auto-Redeem Mode (Steam)
Find Steam games from Humble that are unowned by your Steam user, and ONLY of those that are unowned, redeem on Steam revealed keys (This EXCLUDES non-Steam keys and unclaimed Humble Choice games)

If you choose to reveal keys in this mode, it will only reveal keys that it goes to redeem (ignoring those that are detected as already owned)

### Export Mode
Find all games from Humble, optionally revealing all unrevealed keys, and output them to a CSV (comes with an optional Steam ownership column). 

This is great if you want a manual review of what games are in your keys list that you may have missed.

### Humble Chooser Mode
For those subscribed to Humble Choice, this mode will find any Humble Monthly/Choice that has unclaimed choices, and will let you select, reveal, and optionally autoredeem on Steam the keys you select

---

## Output Files

| File | Description |
|------|-------------|
| `redeemed.csv` | Successfully redeemed keys |
| `already_owned.csv` | Keys for games you already own |
| `errored.csv` | Keys that failed to redeem |
| `expired.csv` | Keys that have expired on Humble |
| `skipped.txt` | Games skipped due to uncertain ownership |

---

## Notes

To remove an already added account, delete the associated `.(humble|steam)cookies` file.

### Steam Web API key

The script requires a Steam Web API key (create one at https://steamcommunity.com/dev/apikey). On first run it will look for `steam_api_key.txt` in the repo folder; if missing, you will be prompted to paste your key and it will be saved to that file for future runs.

---

## Dependencies

Requires Python version 3.6 or above

- `steam`: [ValvePython/steam](https://github.com/ValvePython/steam)  
- `fuzzywuzzy`: [seatgeek/fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy)  
- `requests`: [requests](https://requests.readthedocs.io/en/master/)
- `selenium`: [selenium](https://www.selenium.dev/)
- `pwinput`: [pwinput](https://github.com/asweigart/pwinput)
- `webdriver-manager`: [webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager) - Automatic WebDriver management
- `python-Levenshtein`: [ztane/python-Levenshtein](https://github.com/ztane/python-Levenshtein) **OPTIONAL**  

Install the required dependencies with:
```bash
pip install -r requirements.txt
```

If you want to install `python-Levenshtein` for faster fuzzy matching:
```bash
pip install python-Levenshtein
```

---

## Quick Start

```bash
# 1. Clone and install dependencies
git clone https://github.com/YOUR_USERNAME/humble-steam-key-redeemer.git
cd humble-steam-key-redeemer
pip install -r requirements.txt

# 2. Get a Steam Web API key from https://steamcommunity.com/dev/apikey

# 3. Run the script (first time - will prompt for logins)
python3 humblesteamkeysredeemer.py

# 4. For unattended operation, use the daemon
./run_daemon.sh --background

# 5. Check progress
./run_daemon.sh --stats
```
