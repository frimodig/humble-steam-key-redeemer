# Humble Steam Key Redeemer

> **Fork of [FailSpy/humble-steam-key-redeemer](https://github.com/FailSpy/humble-steam-key-redeemer)**  
> Original work by [FailSpy](https://github.com/FailSpy). This fork adds daemon mode, auto-browser detection, and reliability improvements.

Python utility script to extract Humble keys, and redeem them on Steam automagically by detecting when a game is already owned on Steam.

This is primarily designed to be a set-it-and-forget-it tool that maximizes successful entry of keys into Steam, assuring that no Steam game goes unredeemed.

This script will login to both Humble and Steam, automating the whole process. It's not perfect as I made this mostly for my own personal case and couldn't test all possibilities so YMMV. Feel free to send submit an issue if you do bump into issues.

Any revealing and redeeming the script does will output to spreadsheet files based on their actions for you to easily review what actions it took and whether it redeemed, skipped, or failed on specific keys.

---

## Fork Improvements

This fork includes comprehensive improvements over the original project, focusing on reliability, security, and unattended operation.

### 🔐 Security Enhancements
- **Encrypted cookie storage** - Session cookies are encrypted using AES-128 (Fernet) when `cryptography` is installed
- **Automatic migration** - Seamlessly migrates existing unencrypted cookies to encrypted format
- **Secure key management** - Encryption keys stored with proper permissions (0o600)
- **Backward compatible** - Works without encryption library (graceful fallback)

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
- **Auto-detects installed browsers** (Chrome, Chromium, Brave, Firefox, Edge, Opera, Vivaldi)
- **Uses `webdriver-manager`** to automatically download and manage browser drivers
- **Smart headless mode** - Runs headless when cookies are valid, switches to visible mode only for manual login
- **Cloudflare bypass** - Intelligent handling of bot detection (visible browser fallback)
- **No manual WebDriver installation required**
- Works across macOS, Linux, and Windows

### 🛡️ Improved Reliability & Error Handling
- **Steam API retry logic** - Handles transient API failures gracefully with exponential backoff
- **Session keep-alive** - Prevents browser session timeouts during long operations
- **Expired key handling** - Detects and skips expired keys (logs to `expired.csv`, no retries)
- **Rate limit handling** - Automatically waits and retries when Steam rate limits (403 errors)
- **Resilient order fetching** - Continues processing even if some Humble orders fail (skips corrupted data)
- **Better error messages** - Clear, actionable instructions when things go wrong
- **Progress tracking** - Shows `[X/Total] Game Name (Y remaining)` during redemption
- **Problematic key separation** - Keys from `errored.csv` are retried last, ensuring good keys are processed first

### 📊 Enhanced Steam App Fetching
- Incorporates improvements from [DIASILEDU's PR #55](https://github.com/FailSpy/humble-steam-key-redeemer/pull/55)
- **Paginated fetching** of all Steam apps
- **Parallel fetching** of missing app details using ThreadPoolExecutor
- **Caching system** - Caches Steam app list, owned apps, and order details to reduce API calls
- **Better Steam Web API key management**

### 🔧 Code Quality Improvements
- **Proper logging** - Uses Python `logging` module with rotating file handlers
- **Resource management** - Context managers for file operations (no leaks)
- **Type safety** - Better error handling and validation
- **Cross-platform compatibility** - Works on macOS, Linux, and Windows
- **Python version check** - Ensures Python 3.7+ is used
- **Comprehensive error recovery** - Handles network errors, timeouts, and session issues gracefully

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

### Session Management

To remove an already added account, delete the associated `.(humble|steam)cookies` file.

**Cookie Storage:**
- Cookies are stored in `.humblecookies` and `.steamcookies`
- If `cryptography` is installed, cookies are encrypted using AES-128
- Encryption keys are stored in `.cookie_encryption_key` (permissions: 0o600)
- Existing unencrypted cookies are automatically migrated on first run

### Steam Web API Key

The script requires a Steam Web API key (create one at https://steamcommunity.com/dev/apikey). On first run it will look for `steam_api_key.txt` in the repo folder; if missing, you will be prompted to paste your key and it will be saved to that file for future runs.

### Rate Limiting

Steam limits key redemption to approximately **50 keys per hour**. The script automatically:
- Detects rate limiting (403 Forbidden responses)
- Waits and retries every 5 minutes
- Shows progress during wait periods
- Continues processing once the limit clears

### Troubleshooting

**Script hangs on "Fetching order details...":**
- This usually indicates Cloudflare blocking or network issues
- Try running manually (not in auto-mode) to complete interactive login
- Check browser console logs for specific errors

**Stale cookies error:**
- Run the script manually: `python3 humblesteamkeysredeemer.py`
- Complete the login process (including 2FA if prompted)
- Restart the daemon: `./run_daemon.sh --restart`

**Some orders fail to fetch:**
- This is normal - Humble Bundle sometimes has corrupted data for old orders
- The script will skip problematic orders and continue with valid ones
- Failed order IDs are logged to `failed_orders.txt` (in non-auto mode)

---

## Dependencies

Requires **Python 3.7 or above**

### Required Dependencies
- `steam`: [ValvePython/steam](https://github.com/ValvePython/steam)  
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

---

## Credits & License

- **Original Project**: [FailSpy/humble-steam-key-redeemer](https://github.com/FailSpy/humble-steam-key-redeemer) by [FailSpy](https://github.com/FailSpy)
- **Steam API Improvements**: Based on [PR #55](https://github.com/FailSpy/humble-steam-key-redeemer/pull/55) by [DIASILEDU](https://github.com/DIASILEDU)
- **Fork Enhancements**: Daemon mode, browser detection, reliability improvements by [frimodig](https://github.com/frimodig)

The original project does not specify a license. This fork's additions (daemon mode, browser detection, etc.) are provided as-is for personal use. Please respect the original author's work.
