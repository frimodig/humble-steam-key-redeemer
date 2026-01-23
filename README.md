# Humble Steam Key Redeemer

> **Fork of [FailSpy/humble-steam-key-redeemer](https://github.com/FailSpy/humble-steam-key-redeemer)**  
> Original work by [FailSpy](https://github.com/FailSpy). This fork adds daemon mode, auto-browser detection, reliability improvements, and comprehensive bug fixes.

Python utility script to extract Humble keys, and redeem them on Steam automagically by detecting when a game is already owned on Steam.

This is primarily designed to be a set-it-and-forget-it tool that maximizes successful entry of keys into Steam, assuring that no Steam game goes unredeemed.

This script will login to both Humble and Steam, automating the whole process. It's not perfect as I made this mostly for my own personal case and couldn't test all possibilities so YMMV. Feel free to submit an issue if you do bump into issues.

Any revealing and redeeming the script does will output to spreadsheet files based on their actions for you to easily review what actions it took and whether it redeemed, skipped, or failed on specific keys.

---

## 🚀 Fork Improvements

This fork includes comprehensive improvements over the original project, focusing on reliability, security, unattended operation, and bug fixes.

### 🔐 Security Enhancements
- **Encrypted cookie storage** - Session cookies are encrypted using AES-128 (Fernet) when `cryptography` is installed
- **Automatic migration** - Seamlessly migrates existing unencrypted cookies to encrypted format
- **Secure key management** - Encryption keys stored with proper permissions (0o600)
- **Backward compatible** - Works without encryption library (graceful fallback)
- **File locking** - CSV files use file locking to prevent corruption from concurrent writes
- **CSV escaping** - Proper handling of Unicode and special characters in game names

### 🤖 Daemon Mode for Unattended Operation
A comprehensive daemon script (`run_daemon.sh`) enables fully automated, unattended operation:

**Features:**
- **Auto-restart on crashes** - Automatically restarts if script times out or crashes
- **`--auto` flag** - Automatically answers prompts for hands-off operation
- **Stale cookie detection** - Cleanly exits (instead of hanging) when login sessions expire
- **Health monitoring** - Background process monitors daemon health and log activity
- **Statistics tracking** - See how many keys have been redeemed, errored, expired, etc.
- **Log rotation** - Automatically rotates logs when they exceed 10MB
- **Cross-platform** - Works on macOS, Linux, and Windows (with WSL/Git Bash)
- **Configurable timeout** - Set via `HUMBLE_DAEMON_TIMEOUT` environment variable (default: 2 hours)
- **Startup error detection** - Checks for immediate errors on daemon startup
- **Process management** - Proper PID tracking and cleanup

**Usage:**
```bash
# First, login manually once:
python3 humblesteamkeysredeemer.py

# Run daemon in foreground:
./run_daemon.sh

# Run in background (survives terminal close):
./run_daemon.sh --background

# Check status:
./run_daemon.sh --status

# View statistics:
./run_daemon.sh --stats

# View recent logs:
./run_daemon.sh --log 100

# Stop daemon:
./run_daemon.sh --stop

# Restart daemon:
./run_daemon.sh --restart

# Custom timeout (4 hours):
HUMBLE_DAEMON_TIMEOUT=14400 ./run_daemon.sh --background
```

### 🌐 Automatic Browser Detection
- **Auto-detects installed browsers** (Chrome, Chromium, Brave, Firefox, Edge, Opera, Vivaldi, Arc)
- **Uses `webdriver-manager`** to automatically download and manage browser drivers
- **Smart headless mode** - Runs headless when cookies are valid, switches to visible mode only for manual login
- **Cloudflare bypass** - Intelligent handling of bot detection (visible browser fallback)
- **No manual WebDriver installation required**
- **Custom browser support** - Set `BROWSER_PATH` and `BROWSER_TYPE` environment variables
- **Input validation** - Validates browser paths and executable permissions
- Works across macOS, Linux, and Windows

### 🛡️ Improved Reliability & Error Handling
- **Steam API retry logic** - Handles transient API failures gracefully with exponential backoff
- **Session keep-alive** - Prevents browser session timeouts during long operations (especially during rate limiting)
- **Expired key handling** - Detects and skips expired keys (logs to `expired.csv`, no retries)
- **Rate limit handling** - Automatically waits and retries when Steam rate limits (403 errors)
- **Resilient order fetching** - Continues processing even if some Humble orders fail (skips corrupted data)
- **Better error messages** - Clear, actionable instructions when things go wrong
- **Progress tracking** - Shows `[X/Total] Game Name (Y remaining)` during redemption
- **Problematic key separation** - Keys from `errored.csv` are retried last, ensuring good keys are processed first
- **Deduplication** - Prevents duplicate processing of the same keys
- **Cache integrity** - Validates cached data with checksums, auto-deletes corrupted cache
- **Atomic file operations** - Prevents partial writes and corruption
- **Signal handling** - Proper cleanup on Ctrl+C and SIGTERM (no zombie processes)

### 🎮 Friend/Co-op Key Detection
- **Automatic detection** - Recognizes friend/co-op keys using common patterns
- **Custom patterns** - Add your own patterns via `friend_key_exclusions.txt`
- **Safe storage** - Friend keys saved to `friend_keys.csv` for gifting
- **User control** - Option to enable/disable friend key filtering
- **Pre-filtering** - Option to filter friend keys before processing all keys
- **Multiple detection points** - Checks `human_name`, `machine_name`, and `key_type` fields

### 📊 Enhanced Steam App Fetching
- Incorporates improvements from [DIASILEDU's PR #55](https://github.com/FailSpy/humble-steam-key-redeemer/pull/55)
- **Paginated fetching** of all Steam apps
- **Parallel fetching** of missing app details using ThreadPoolExecutor
- **Caching system** - Caches Steam app list, owned apps, and order details to reduce API calls
- **Cache integrity checking** - Validates cached data with SHA-256 checksums
- **Better Steam Web API key management**

### 🔧 Code Quality Improvements
- **Proper logging** - Uses Python `logging` module with rotating file handlers (10MB max, 3 backups)
- **Resource management** - Context managers for file operations (no leaks)
- **Type safety** - Better error handling and validation
- **Cross-platform compatibility** - Works on macOS, Linux, and Windows
- **Python version check** - Ensures Python 3.7+ is used
- **Comprehensive error recovery** - Handles network errors, timeouts, and session issues gracefully
- **Unified retry logic** - Consistent retry strategies throughout the codebase
- **Path handling** - Platform-aware paths for cache and config directories (Windows support)

### 🐛 Critical Bug Fixes
- **Fixed indentation bug** - Rate-limit loop and `write_key()` now correctly inside `for` loop
- **Fixed problematic key matching** - Now matches by `(gamekey, name)` instead of just `gamekey` (fixes shared gamekey issue)
- **Fixed duplicate retries** - Prevents retrying the same key multiple times
- **Fixed invalid key filtering** - Filters empty/expired/invalid keys before retrying
- **Fixed CSV deduplication** - Prevents duplicate entries in CSV files
- **Fixed signal handler race condition** - Prevents duplicate handler registration
- **Fixed JavaScript timeout** - Reduced to 28s to prevent conflicts with Python timeout
- **Fixed session keep-alive** - Now works during rate-limit waits

### 🎯 Choice Month Completion Tracking
- **Automatic tracking** - Tracks completed Choice months in `.choice_completed.json`
- **Smart skipping** - Skips months where all games are already selected and redeemed
- **Performance optimization** - Avoids slow API calls for months with no unselected games
- **Faster startup** - Significantly reduces startup time by skipping already-processed months

---

## Modes

### Auto-Redeem Mode (Steam)
Find Steam games from Humble that are unowned by your Steam user, and ONLY of those that are unowned, redeem on Steam revealed keys (This EXCLUDES non-Steam keys and unclaimed Humble Choice games)

If you choose to reveal keys in this mode, it will only reveal keys that it goes to redeem (ignoring those that are detected as already owned)

**Features:**
- Automatically reveals unredeemed Humble Choice games
- Auto-selects unselected Choice games when needed
- Skips already-completed Choice months (faster startup)
- Skips friend/co-op keys (saves to `friend_keys.csv`)
- Processes problematic keys last (from `errored.csv`)
- Shows accurate counts including problematic keys

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
| `errored.csv` | Keys that failed to redeem (will be retried on next run) |
| `expired.csv` | Keys that have expired on Humble |
| `friend_keys.csv` | Friend/co-op keys saved for gifting |
| `skipped.txt` | Games skipped due to uncertain ownership (temporary file) |
| `failed_orders.txt` | Orders that failed to fetch (corrupted data on Humble's side) |
| `.choice_completed.json` | Tracks completed Choice months (skipped on future runs) |

**Notes:**
- Successfully redeemed keys are automatically removed from `errored.csv` to prevent re-retrying
- Choice months are automatically tracked and skipped once all games are selected and redeemed

---

## Notes

### Session Management

To remove an already added account, delete the associated cookie files.

**Cookie Storage:**
- Cookies are stored in `.humblecookies` and `.steamcookies` (or platform-specific paths)
- If `cryptography` is installed, cookies are encrypted using AES-128
- Encryption keys are stored in `.cookie_encryption_key` (permissions: 0o600)
- Existing unencrypted cookies are automatically migrated on first run
- **Platform-aware paths:**
  - **Windows**: `%LOCALAPPDATA%\HumbleRedeemer\`
  - **Unix**: `~/.config/humble-redeemer/` or current directory (backward compatible)

### Steam Web API Key

The script requires a Steam Web API key (create one at https://steamcommunity.com/dev/apikey). On first run it will look for `steam_api_key.txt` in the repo folder; if missing, you will be prompted to paste your key and it will be saved to that file for future runs.

### Rate Limiting

Steam limits key redemption to approximately **50 keys per hour**. The script automatically:
- Detects rate limiting (403 Forbidden responses)
- Waits and retries every 5 minutes
- Shows progress updates every 5 minutes (reduced verbosity for long waits)
- Keeps Humble session alive during long waits (every 5 minutes)
- Continues processing once the limit clears
- Tracks rate limit statistics (count and total wait time)
- Minimal logging during rate limit waits to reduce log spam

### Friend/Co-op Keys

Friend/co-op keys are automatically detected and skipped during redemption. They are saved to `friend_keys.csv` for gifting later.

**Custom patterns:** Create `friend_key_exclusions.txt` with one pattern per line (comments start with `#`):
```
# Friend Key Exclusions
my custom pattern
another game name
```

### Problematic Keys

Keys that fail to redeem are saved to `errored.csv` and will be retried on the next run. The script:
- Processes problematic keys **last** (after normal keys)
- Matches by both `gamekey` AND `name` (handles shared gamekeys correctly)
- Filters out invalid/empty/expired keys before retrying
- Deduplicates entries to prevent retrying the same key multiple times
- Automatically removes successfully redeemed keys from `errored.csv`

### Troubleshooting

**Script hangs on "Fetching order details...":**
- This usually indicates Cloudflare blocking or network issues
- Try running manually (not in auto-mode) to complete interactive login
- Check browser console logs for specific errors
- The script now detects Cloudflare challenges and provides clear instructions

**Stale cookies error:**
- Run the script manually: `python3 humblesteamkeysredeemer.py`
- Complete the login process (including 2FA if prompted)
- Restart the daemon: `./run_daemon.sh --restart`

**Some orders fail to fetch:**
- This is normal - Humble Bundle sometimes has corrupted data for old orders
- The script will skip problematic orders and continue with valid ones
- Failed order IDs are logged to `failed_orders.txt` (in non-auto mode)
- The script shows a summary of failed orders

**Duplicate retries:**
- Run `python3 cleanup_errored_csv.py` to remove duplicates from `errored.csv`
- The script now automatically deduplicates entries

**"Metal Slug Tactics" or similar games not being processed:**
- These games share a `gamekey` with other Choice games
- The script now matches by both `gamekey` AND `name` to handle this correctly
- Use `check_why_not_redeemed.py "Game Name"` to diagnose specific games

---

## Dependencies

Requires **Python 3.7 or above**

### Required Dependencies
- `steam`: [FailSpy/steam-py-lib@master](https://github.com/FailSpy/steam-py-lib) (patched fork)
- `fuzzywuzzy`: [seatgeek/fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy)  
- `requests`: [requests](https://requests.readthedocs.io/en/master/)
- `selenium`: [selenium](https://www.selenium.dev/)
- `pwinput`: [pwinput](https://github.com/asweigart/pwinput)
- `webdriver-manager`: [webdriver-manager](https://github.com/SergeyPirogov/webdriver_manager) - Automatic WebDriver management

### Optional Dependencies
- `cryptography` (>=41.0.0): Enables encrypted cookie storage for enhanced security
- `python-Levenshtein`: Faster fuzzy matching (recommended for better performance)

### Installation
```bash
# Install required dependencies
pip install -r requirements.txt

# Optional: Install encryption support (recommended)
pip install cryptography

# Optional: Install faster fuzzy matching
pip install python-Levenshtein
```

**Note:** The script works without `cryptography`, but cookies will be stored unencrypted. For production use, encryption is strongly recommended.

---

## Quick Start

```bash
# 1. Clone and install dependencies
git clone https://github.com/frimodig/humble-steam-key-redeemer.git
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

---

## Additional Tools

### Export Keys for Friends

Export revealed Steam keys from `already_owned.csv` to share with friends:

```bash
# Export only potentially unused keys (recommended)
python3 export_keys_for_friends.py safe

# Export all keys with game names
python3 export_keys_for_friends.py names

# Export full CSV with status
python3 export_keys_for_friends.py full
```

**Note:** This script checks `redeemed.csv` to identify potentially used keys. Keys that appear in both files may have been manually redeemed in the past. Always test keys before sharing!

### Diagnostic Scripts

The repository includes several diagnostic scripts for troubleshooting (not tracked in git to keep the repo clean). These can be created locally as needed:
- Check game status and processing history
- Analyze why games weren't redeemed
- Diagnose Choice game detection issues
- Clean up duplicate entries in CSV files

---

## Credits & License

- **Original Project**: [FailSpy/humble-steam-key-redeemer](https://github.com/FailSpy/humble-steam-key-redeemer) by [FailSpy](https://github.com/FailSpy)
- **Steam API Improvements**: Based on [PR #55](https://github.com/FailSpy/humble-steam-key-redeemer/pull/55) by [DIASILEDU](https://github.com/DIASILEDU)
- **Fork Enhancements**: Daemon mode, browser detection, reliability improvements, bug fixes, and friend key detection by [frimodig](https://github.com/frimodig)

The original project does not specify a license. This fork's additions (daemon mode, browser detection, etc.) are provided as-is for personal use. Please respect the original author's work.
