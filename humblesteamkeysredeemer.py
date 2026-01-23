import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.common.exceptions import (
    WebDriverException, 
    TimeoutException,
    InvalidSessionIdException,
    NoSuchWindowException,
    StaleElementReferenceException
)
from fuzzywuzzy import fuzz
import steam.webauth as wa
import time
import pickle
from pwinput import pwinput
import os
import json
import sys
import webbrowser
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import atexit
import signal
from http.client import responses
from http import HTTPStatus
from typing import Union, Dict, Any, Tuple, Optional
import argparse
import csv
import threading
import functools
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
from contextlib import contextmanager
from pathlib import Path
import hashlib
from enum import IntEnum
import re

# Try to import encryption support
try:
    from cryptography.fernet import Fernet
    HAS_ENCRYPTION = True
except ImportError:
    HAS_ENCRYPTION = False

# Try to import file locking support
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

# Auto mode flag - when True, auto-answers prompts for daemon/unattended operation
AUTO_MODE = False


# Steam redemption error codes (from Steam API responses)
class SteamErrorCode(IntEnum):
    """
    Steam key redemption error codes.
    
    Note: EXPIRED is a Humble Bundle-specific code (not a Steam error).
    Uses negative value (-1) to avoid conflicts with Steam's positive error codes.
    
    Example usage:
        >>> code = SteamErrorCode.SUCCESS
        >>> write_key(code, key_dict)
        
        >>> # String "EXPIRED" is automatically converted
        >>> write_key("EXPIRED", key_dict)
    """
    SUCCESS = 0
    INVALID_KEY = 14
    DUPLICATE_KEY = 15
    ALREADY_OWNED = 9
    RATE_LIMITED = 53
    # Humble Bundle specific code - negative to avoid Steam error code conflicts
    EXPIRED = -1  # Key expired on Humble Bundle (not a Steam error)


def normalize_error_code(code: Union[SteamErrorCode, int, str]) -> Union[SteamErrorCode, int]:
    """
    Normalize error code to int/IntEnum type for consistent handling.
    
    Converts string "EXPIRED" to SteamErrorCode.EXPIRED enum value.
    This ensures backward compatibility while maintaining type consistency.
    
    Args:
        code: Error code in various formats (SteamErrorCode enum, int, or "EXPIRED" string)
        
    Returns:
        Normalized error code (SteamErrorCode enum or int)
        
    Raises:
        ValueError: If code is invalid type
        
    Example:
        >>> normalize_error_code("EXPIRED")
        SteamErrorCode.EXPIRED
        >>> normalize_error_code(SteamErrorCode.SUCCESS)
        SteamErrorCode.SUCCESS
        >>> normalize_error_code(0)
        0
    """
    if isinstance(code, str):
        if code == "EXPIRED":
            return SteamErrorCode.EXPIRED
        else:
            logging.warning(f"Unknown string error code: {code}, treating as generic error")
            return -2  # Generic error code for unknown string codes
    elif isinstance(code, (int, IntEnum)):
        return code
    else:
        raise ValueError(f"Invalid code type: {type(code)}, expected SteamErrorCode, int, or str")


# Friend key detection confidence thresholds
FRIEND_KEY_HIGH_CONFIDENCE_THRESHOLD = 0.8
FRIEND_KEY_LOW_CONFIDENCE_THRESHOLD = 0.5

# Success codes for Steam key redemption (used for cleanup operations)
SUCCESS_CODES = {
    SteamErrorCode.SUCCESS,
    SteamErrorCode.ALREADY_OWNED,
    SteamErrorCode.DUPLICATE_KEY
}

# CSV file paths used by the script
class CSVFiles:
    """CSV file paths and operations configuration."""
    # File paths
    ERRORED = "errored.csv"
    REDEEMED = "redeemed.csv"
    ALREADY_OWNED = "already_owned.csv"
    EXPIRED = "expired.csv"
    FRIEND_KEYS = "friend_keys.csv"
    SKIPPED = "skipped.txt"
    
    # File operation configuration
    ENCODING = "utf-8-sig"
    
    @classmethod
    def get_exclusion_filters(cls):
        """Return list of CSV files used for duplicate filtering."""
        return [cls.ALREADY_OWNED, cls.REDEEMED, cls.EXPIRED, cls.FRIEND_KEYS]


# Mapping from error codes to CSV files for cleaner code organization
# Defined after CSVFiles class to avoid forward reference errors
CODE_TO_FILE_MAP = {
    SteamErrorCode.SUCCESS: CSVFiles.REDEEMED,
    SteamErrorCode.DUPLICATE_KEY: CSVFiles.ALREADY_OWNED,
    SteamErrorCode.ALREADY_OWNED: CSVFiles.ALREADY_OWNED,
    SteamErrorCode.EXPIRED: CSVFiles.EXPIRED,
}

# CSV encoding constant (for backward compatibility and convenience)
CSV_ENCODING = CSVFiles.ENCODING

# Compiled regex patterns for better performance (compiled once at module level)
PLATFORM_SUFFIX_PATTERN = re.compile(r'\s*\(Steam\)\s*$', re.IGNORECASE)

# Windows file locking constants
# Lock 1 byte at offset 0 - this is the standard practice for file locking on Windows.
# 
# Unlike Unix (which locks the whole file with flock), Windows uses byte-range locking.
# This single byte acts as a lock flag for the entire file on Windows.
# Locking just 1 byte is standard and sufficient - locking more bytes would waste
# address space without providing additional synchronization benefits.
WINDOWS_LOCK_SIZE = 1  # Lock 1 byte at offset 0 (standard practice for file locking)

# Cache directory for storing fetched data
CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)

# Cache version - increment when data structure changes to invalidate old caches
CACHE_VERSION = 1

# Choice month completion tracking file
CHOICE_COMPLETED_FILE = Path(".choice_completed.json")

def load_completed_choice_months():
    """
    Load the set of completed Choice month gamekeys.
    
    Returns:
        Set of gamekeys for Choice months that have been fully processed
    """
    if not CHOICE_COMPLETED_FILE.exists():
        return set()
    
    try:
        with open(CHOICE_COMPLETED_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Support both old format (list) and new format (dict with metadata)
            if isinstance(data, list):
                return set(data)
            elif isinstance(data, dict) and 'completed_months' in data:
                return set(data['completed_months'])
            else:
                return set()
    except (IOError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logging.warning(f"Error loading completed Choice months: {e}")
        return set()

def save_completed_choice_months(completed_months):
    """
    Save the set of completed Choice month gamekeys.
    
    Args:
        completed_months: Set of gamekeys for completed months
    """
    try:
        data = {
            'completed_months': list(completed_months),
            'last_updated': datetime.now().isoformat(),
            'version': 1
        }
        with open(CHOICE_COMPLETED_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except (IOError, OSError, TypeError) as e:
        logging.error(f"Error saving completed Choice months: {e}")

def is_choice_month_complete(month_gamekey, order_details):
    """
    Check if a Choice month is complete (all games selected and all keys redeemed).
    
    A month is complete when:
    1. All games in the month are selected (in tpkd_dict)
    2. All keys for that month are in redeemed.csv or already_owned.csv
    
    Args:
        month_gamekey: The gamekey of the Choice month
        order_details: The order details dictionary
        
    Returns:
        True if the month is complete, False otherwise
    """
    # Find the month in order_details
    month = None
    for order in order_details:
        if order.get('gamekey') == month_gamekey:
            month = order
            break
    
    if not month:
        return False
    
    # Check if all games are selected
    tpkd_dict = month.get('tpkd_dict', {})
    chosen_games = set(find_dict_keys(tpkd_dict, "machine_name"))
    
    # Get all games for this month
    month_keys = [key for key in find_dict_keys(order_details, "steam_app_id", True) 
                  if key.get('gamekey') == month_gamekey]
    
    if not month_keys:
        # No keys found for this month - might not be a Choice month
        return False
    
    # Check if all keys are redeemed or already owned
    redeemed_keys = _get_cached_keys(CSVFiles.REDEEMED)
    owned_keys = _get_cached_keys(CSVFiles.ALREADY_OWNED)
    all_keys = redeemed_keys | owned_keys
    
    for key in month_keys:
        gamekey = key.get('gamekey', '')
        human_name = key.get('human_name', '')
        if gamekey and human_name:
            if (gamekey, human_name.lower()) not in all_keys:
                # At least one key is not redeemed/owned
                return False
    
    # All keys are redeemed/owned - month is complete
    return True

def mark_choice_month_complete(month_gamekey):
    """
    Mark a Choice month as complete.
    
    Args:
        month_gamekey: The gamekey of the Choice month to mark as complete
    """
    completed = load_completed_choice_months()
    completed.add(month_gamekey)
    save_completed_choice_months(completed)

# ============================================================================
# Configuration Constants
# ============================================================================

# Timeouts and delays (in seconds)
SCRIPT_TIMEOUT_SECONDS = 40  # Reduced to give 10s buffer after JS timeout (30s)
JS_TIMEOUT_SECONDS = 30  # JavaScript execution timeout
PAGE_LOAD_TIMEOUT_SECONDS = 30  # Page load timeout
NETWORK_REQUEST_TIMEOUT_SECONDS = 30  # HTTP request timeout
DEFAULT_SLEEP_SECONDS = 2  # Default sleep between operations
SHORT_SLEEP_SECONDS = 1  # Short sleep for quick operations
MEDIUM_SLEEP_SECONDS = 2  # Medium sleep for page loads
LONG_SLEEP_SECONDS = 3  # Long sleep for complex operations
EXTENDED_SLEEP_SECONDS = 5  # Extended sleep for retries and longer waits
VERY_LONG_SLEEP_SECONDS = 30  # Very long sleep (e.g., after rate limit)

# Rate limiting
RATE_LIMIT_RETRY_INTERVAL_SECONDS = 300  # 5 minutes between retries
RATE_LIMIT_CHECK_INTERVAL_SECONDS = 10  # Check every 10 seconds
RATE_LIMIT_APPROXIMATE_DURATION_SECONDS = 3600  # ~1 hour total duration
STEAM_RATE_LIMIT_KEYS_PER_HOUR = 50  # Steam's approximate rate limit

# Retry logic
DEFAULT_RETRY_COUNT = 3  # Default number of retries
DEFAULT_RETRY_DELAY_SECONDS = 2  # Default delay between retries
MAX_RETRY_ATTEMPTS = 3  # Maximum retry attempts for operations

# Session management
KEEP_ALIVE_INTERVAL_SECONDS = 300  # 5 minutes between keep-alive checks
SESSION_VALIDATION_TIMEOUT_SECONDS = 10  # Session validation timeout
PROGRESS_DOT_INTERVAL_SECONDS = 5  # Progress indicator update interval

# File operations
CSV_FLUSH_INTERVAL = 1  # Flush CSV after each write
LOG_ROTATION_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_ROTATION_BACKUP_COUNT = 3  # Keep 3 backup log files

# Browser detection
BROWSER_DETECTION_TIMEOUT_SECONDS = 5  # Timeout for browser detection

# Legacy constant removed - all references now use SCRIPT_TIMEOUT_SECONDS directly

try:
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager
    from webdriver_manager.core.os_manager import ChromeType
    HAS_WEBDRIVER_MANAGER = True
except ImportError:
    HAS_WEBDRIVER_MANAGER = False

#patch steam webauth for password feedback
wa.getpass = pwinput

# Setup proper logging with rotation
def setup_logging():
    """Setup rotating log handler to prevent unbounded log growth."""
    # Create logger
    logger = logging.getLogger('humble_redeemer')
    logger.setLevel(logging.DEBUG)  # Capture all levels
    
    # File handler for errors and warnings (rotating)
    file_handler = RotatingFileHandler('error.log', maxBytes=10*1024*1024, backupCount=3)
    file_handler.setLevel(logging.WARNING)  # Only warnings and errors to file
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler for errors only (to original stderr)
    console_handler = logging.StreamHandler(sys.__stderr__)
    console_handler.setLevel(logging.ERROR)  # Only errors to console
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Redirect stderr to logger with smart level detection
    class LoggerWriter:
        def __init__(self, logger):
            self.logger = logger
            self.buffer = []
        
        def write(self, message):
            # Buffer messages to handle multi-line output
            if message and message != '\n':
                self.buffer.append(message)
                if message.endswith('\n') or '\n' in message:
                    full_message = ''.join(self.buffer).strip()
                    self.buffer = []
                    if full_message:
                        self._log_with_level(full_message)
        
        def _log_with_level(self, message):
            """Detect log level from message content."""
            msg_lower = message.lower()
            if any(x in msg_lower for x in ['error', 'exception', 'failed', 'fail', 'traceback']):
                self.logger.error(message)
            elif any(x in msg_lower for x in ['warning', 'warn']):
                self.logger.warning(message)
            elif any(x in msg_lower for x in ['debug', '[debug]']):
                self.logger.debug(message)
            else:
                # Default to warning for stderr (since it's usually important)
                self.logger.warning(message)
        
        def flush(self):
            if self.buffer:
                full_message = ''.join(self.buffer).strip()
                if full_message:
                    self._log_with_level(full_message)
                self.buffer = []
    
    sys.stderr = LoggerWriter(logger)

if __name__ == "__main__":
    # Check Python version
    MIN_PYTHON = (3, 7)
    if sys.version_info < MIN_PYTHON:
        print(f"Error: This script requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or higher.")
        print(f"You are running Python {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)
    
    setup_logging()
    
    # Inform about encryption availability (only once at startup, not in auto-mode)
    if not HAS_ENCRYPTION and not AUTO_MODE:
        print("[INFO] cryptography package not found. Cookies will be stored unencrypted.")
        print("      Install with: pip install cryptography")
        print("      Using restrictive file permissions (600) as fallback.")

# Humble endpoints
HUMBLE_LOGIN_PAGE = "https://www.humblebundle.com/login"
HUMBLE_KEYS_PAGE = "https://www.humblebundle.com/home/library"
HUMBLE_SUB_PAGE = "https://www.humblebundle.com/subscription/"

HUMBLE_LOGIN_API = "https://www.humblebundle.com/processlogin"
HUMBLE_REDEEM_API = "https://www.humblebundle.com/humbler/redeemkey"
HUMBLE_ORDERS_API = "https://www.humblebundle.com/api/v1/user/order"
HUMBLE_ORDER_DETAILS_API = "https://www.humblebundle.com/api/v1/order/"
HUMBLE_SUB_API = "https://www.humblebundle.com/api/v1/subscriptions/humble_monthly/subscription_products_with_gamekeys/"

HUMBLE_PAY_EARLY = "https://www.humblebundle.com/subscription/payearly"
HUMBLE_CHOOSE_CONTENT = "https://www.humblebundle.com/humbler/choosecontent"

# Steam endpoints
STEAM_KEYS_PAGE = "https://store.steampowered.com/account/registerkey"
STEAM_USERDATA_API = "https://store.steampowered.com/dynamicstore/userdata/"
STEAM_REDEEM_API = "https://store.steampowered.com/account/ajaxregisterkey/"
STEAM_APP_LIST_API = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"

# May actually be able to do without these, but for now they're in.
headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# Script execution timeout (seconds)
# Duplicate removed - all references now use SCRIPT_TIMEOUT_SECONDS directly


def retry_on_session_error(max_retries=3, delay=2):
    """Decorator to retry operations on session errors."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (InvalidSessionIdException, NoSuchWindowException) as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"[DEBUG] Session error in {func.__name__}, attempt {attempt + 1}/{max_retries}: {e}")
                    time.sleep(delay)
                except TimeoutException as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"[DEBUG] Timeout in {func.__name__}, attempt {attempt + 1}/{max_retries}")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


def validate_session(driver):
    """Check if the WebDriver session is still valid."""
    try:
        # Simple check - get current URL
        _ = driver.current_url
        return True
    except (InvalidSessionIdException, NoSuchWindowException):
        return False
    except Exception as e:
        print(f"[DEBUG] Unexpected error validating session: {e}")
        return False


def refresh_page_if_needed(driver, url=None):
    """Refresh the page if session seems stale."""
    try:
        if url:
            driver.get(url)
        else:
            driver.refresh()
        time.sleep(DEFAULT_SLEEP_SECONDS)
        return True
    except Exception as e:
        print(f"[DEBUG] Failed to refresh page: {e}")
        return False


def find_dict_keys(node, kv, parent=False):
    """Recursively find all values (or parent dicts) with a given key."""
    if isinstance(node, list):
        for i in node:
            for x in find_dict_keys(i, kv, parent):
               yield x
    elif isinstance(node, dict):
        if kv in node:
            if parent:
                yield node
            else:
                yield node[kv]
        for j in node.values():
            for x in find_dict_keys(j, kv, parent):
                yield x

getHumbleOrders = '''
var done = arguments[arguments.length - 1];
var list = arguments[0] || [];  // Get list from arguments (safer than string replacement)
console.log('[DEBUG] Starting getHumbleOrderDetails');

// Prevent duplicate callbacks with a flag
var callbackFired = false;
var timeoutId = null;

function safeCallback(result) {
    if (!callbackFired) {
        callbackFired = true;
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        done(result);
    }
}

// Add timeout wrapper to ensure callback is always called
timeoutId = setTimeout(function() {
    console.error('[DEBUG] Timeout: Fetching order details took too long');
    safeCallback({error: 'timeout', message: 'Request timed out after 30 seconds'});
}, 30000);  // Reduced from 50s to 30s

var getHumbleOrderDetails = async (list) => {
  const HUMBLE_ORDERS_API_URL = 'https://www.humblebundle.com/api/v1/user/order';
  const HUMBLE_ORDER_DETAILS_API = 'https://www.humblebundle.com/api/v1/order/';

  try {
    var orders = []
    if(list.length){
      orders = list.map(item => ({ gamekey: item }));
    } else {
      try {
        console.log('[DEBUG] Fetching orders list from:', HUMBLE_ORDERS_API_URL);
        // Add timeout using AbortController for better compatibility
        var controller = new AbortController();
        var fetchTimeout = setTimeout(() => controller.abort(), 25000);  // Reduced from 45s to 25s
        const response = await fetch(HUMBLE_ORDERS_API_URL, {
          signal: controller.signal,
          credentials: 'include'  // Include cookies for authentication
        });
        clearTimeout(fetchTimeout);
        console.log('[DEBUG] Orders list response status:', response.status);
        // Check for authentication errors
        if (response.status === 401 || response.status === 403) {
          return {error: 'auth_error', message: 'Authentication failed (HTTP ' + response.status + ') - session may have expired'};
        }
        if (!response.ok) {
          return {error: 'http_error', message: 'HTTP error ' + response.status + ' when fetching orders'};
        }
        
        // Try to parse JSON with better error handling
        try {
          orders = await response.json();
        } catch (jsonError) {
          console.error('[DEBUG] JSON parse error for orders list:', jsonError);
          const textPreview = await response.text().catch(() => 'Could not read response body');
          return {
            error: 'json_parse_error', 
            message: 'Humble Bundle returned invalid JSON: ' + jsonError.message,
            details: 'Response preview (first 500 chars): ' + textPreview.substring(0, 500)
          };
        }
      } catch (fetchError) {
        if (fetchError.name === 'AbortError' || fetchError.name === 'TimeoutError') {
          return {error: 'timeout', message: 'Request timed out while fetching orders list'};
        }
        return {error: 'network_error', message: 'Network error fetching orders: ' + fetchError.message + ' (This may indicate Cloudflare blocking or network issues)'};
      }
    }
    const orderDetailsPromises = orders.map(async (order) => {
      try {
        var controller = new AbortController();
        var fetchTimeout = setTimeout(() => controller.abort(), 25000);  // Reduced from 45s to 25s
        const orderDetailsUrl = `${HUMBLE_ORDER_DETAILS_API}${order['gamekey']}?all_tpkds=true`;
        const orderDetailsResponse = await fetch(orderDetailsUrl, {
          signal: controller.signal,
          credentials: 'include'  // Include cookies for authentication
        });
        clearTimeout(fetchTimeout);
        // Check for authentication errors
        if (orderDetailsResponse.status === 401 || orderDetailsResponse.status === 403) {
          return {error: 'auth_error', message: 'Authentication failed (HTTP ' + orderDetailsResponse.status + ') - session may have expired'};
        }
        if (!orderDetailsResponse.ok) {
          return {error: 'http_error', message: 'HTTP error ' + orderDetailsResponse.status + ' when fetching order details'};
        }
        
        // Try to parse JSON with better error handling
        try {
          const orderDetails = await orderDetailsResponse.json();
          return orderDetails;
        } catch (jsonError) {
          console.error('[DEBUG] JSON parse error for order', order['gamekey'], ':', jsonError);
          // Try to get response text for debugging
          const textPreview = await orderDetailsResponse.text().catch(() => 'Could not read response body');
          return {
            error: 'json_parse_error',
            message: 'Invalid JSON for order ' + order['gamekey'] + ': ' + jsonError.message,
            details: 'Response preview: ' + textPreview.substring(0, 200),
            gamekey: order['gamekey']
          };
        }
      } catch (fetchError) {
        if (fetchError.name === 'AbortError' || fetchError.name === 'TimeoutError') {
          return {error: 'timeout', message: 'Request timed out while fetching order details for ' + order['gamekey']};
        }
        return {error: 'network_error', message: 'Network error fetching order details: ' + fetchError.message};
      }
    });

    const orderDetailsArray = await Promise.all(orderDetailsPromises);
    
    // Separate successful orders from errors
    const successfulOrders = [];
    const failedOrders = [];
    
    for (var i = 0; i < orderDetailsArray.length; i++) {
      const order = orderDetailsArray[i];
      if (order && typeof order === 'object' && 'error' in order) {
        failedOrders.push(order);
        console.warn('[WARNING] Failed to fetch order:', order.gamekey || 'unknown', '-', order.message);
      } else {
        successfulOrders.push(order);
      }
    }
    
    // Only fail if ALL orders failed or if the main order list failed
    if (successfulOrders.length === 0) {
      console.error('[ERROR] All orders failed to fetch');
      return failedOrders[0] || {error: 'fetch_error', message: 'All orders failed to fetch'};
    }
    
    // Log summary if some orders failed
    if (failedOrders.length > 0) {
      console.warn('[WARNING] Successfully fetched', successfulOrders.length, 'orders,', failedOrders.length, 'failed');
      console.warn('[WARNING] Failed order IDs:', failedOrders.map(f => f.gamekey || 'unknown').join(', '));
    }
    
    return successfulOrders;
  } catch (error) {
    console.error('Error:', error);
    if (error.name === 'AbortError' || error.name === 'TimeoutError') {
      return {error: 'timeout', message: 'Request timed out'};
    }
    return {error: 'fetch_error', message: error.message};
  }
};

getHumbleOrderDetails(list).then(r => {
    safeCallback(r);
}).catch(err => {
    safeCallback({error: 'exception', message: err.message});
});
'''

# JavaScript fetch command - uses execute_async_script arguments for safe parameter passing
# This prevents JavaScript injection by passing data directly as arguments instead of string formatting
fetch_cmd = '''
var done = arguments[arguments.length - 1];
var url = arguments[0];
var csrf = arguments[1];
var formDataObj = arguments[2];

var formData = new FormData();
for (const key in formDataObj) {
    formData.append(key, formDataObj[key]);
}

fetch(url, {
    "headers": {
        "csrf-prevention-token": csrf
    },
    "body": formData,
    "method": "POST",
}).then(r => {
    r.json().then(v => {
        done([r.status, v]);
    }).catch(err => {
        done([r.status, {error: err.message}]);
    });
}).catch(err => {
    done([0, {error: err.message}]);
});
'''

def perform_post(driver: webdriver.Remote, url: str, payload: Dict[str, Any], max_retries: int = 3) -> Tuple[int, Dict[str, Any]]:
    """
    Perform a POST request via JavaScript fetch in the browser.
    Uses exponential backoff and session refresh on retries.
    
    Args:
        driver: Selenium WebDriver instance
        url: Target URL for the POST request
        payload: Dictionary of form data to send
        max_retries: Maximum number of retry attempts
    
    Returns:
        Tuple of (HTTP status code, JSON response dictionary)
    """
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            # Refresh session if needed before each attempt
            if not validate_session(driver):
                if attempt < max_retries - 1:
                    print(f"[DEBUG] Session invalid, refreshing... (attempt {attempt + 1}/{max_retries})")
                    refresh_page_if_needed(driver, "https://www.humblebundle.com/home/library")
                    time.sleep(DEFAULT_SLEEP_SECONDS)
                else:
                    raise InvalidSessionIdException("WebDriver session is invalid after retries")
            
            csrf = driver.get_cookie('csrf_cookie')
            csrf_value = csrf['value'] if csrf is not None else ''
            
            # Pass data directly as arguments to execute_async_script (prevents JavaScript injection)
            # This is safer than string formatting because arguments are serialized by Selenium
            result = driver.execute_async_script(fetch_cmd, url, csrf_value, payload)
            return result
            
        except TimeoutException as e:
            if attempt == max_retries - 1:
                print(f"[DEBUG] Timeout executing POST to {url} after {max_retries} attempts")
                raise
            # Exponential backoff
            delay = base_delay * (2 ** attempt)
            print(f"[DEBUG] Timeout executing POST to {url}, retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
            
        except (InvalidSessionIdException, NoSuchWindowException) as e:
            # Don't retry on session death - it's a permanent error
            print(f"[DEBUG] Invalid session while executing POST to {url}: {e}")
            raise
            
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"[DEBUG] Unexpected error executing POST to {url}: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[DEBUG] Error executing POST to {url}, retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)


def try_firefox_browser(name, binary_path, exceptions, headless=True):
    """Try to create a Firefox browser driver."""
    driver = None
    if HAS_WEBDRIVER_MANAGER:
        try:
            options = webdriver.FirefoxOptions()
            if headless:
                options.add_argument("-headless")
            if binary_path:
                options.binary_location = binary_path
            service = FirefoxService(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=service, options=options)
            driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)  # Set timeout immediately
            driver.set_page_load_timeout(30)
            process_quit(driver)
            return driver
        except Exception as e:
            exceptions.append((f'{name} (webdriver-manager):', str(e)[:200]))
    # Fallback without webdriver-manager
    try:
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        if binary_path:
            options.binary_location = binary_path
        driver = webdriver.Firefox(options=options)
        driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)  # Set timeout immediately
        driver.set_page_load_timeout(30)
        process_quit(driver)
        return driver
    except Exception as e:
        exceptions.append((f'{name} (fallback):', str(e)[:200]))
    return None


# Global driver reference for signal handling
_global_driver = None
_global_interrupt_event = None

def process_quit(driver, interrupt_event=None):
    """Register cleanup handlers to quit the driver on exit."""
    global _global_driver, _global_interrupt_event
    _global_driver = driver
    if interrupt_event:
        _global_interrupt_event = interrupt_event
    
    def quit_on_exit(signum, frame):
        print("\n\nInterrupted by user (Ctrl+C). Cleaning up...", file=sys.stderr, flush=True)
        # Set interrupt event if available (allows thread to exit gracefully)
        if _global_interrupt_event:
            _global_interrupt_event.set()
        
        # Try to quit driver gracefully
        driver_pid = None
        try:
            if _global_driver:
                try:
                    driver_pid = _global_driver.service.process.pid if hasattr(_global_driver, 'service') and hasattr(_global_driver.service, 'process') else None
                except:
                    pass
                _global_driver.quit()
        except:
            pass
        
        # Force kill browser process if driver.quit() didn't work
        if driver_pid:
            try:
                os.kill(driver_pid, signal.SIGTERM)
                time.sleep(0.5)
                os.kill(driver_pid, signal.SIGKILL)
            except:
                pass
        
        # Exit with code 130 for SIGINT (Ctrl+C), 143 for SIGTERM
        exit_code = 130 if signum == signal.SIGINT else 143
        sys.exit(exit_code)  # Use sys.exit to allow proper cleanup (finally blocks, atexit handlers)
    
    def quit_on_exit_atexit():
        try:
            if _global_driver:
                _global_driver.quit()
        except:
            pass

    atexit.register(quit_on_exit_atexit)
    signal.signal(signal.SIGTERM, quit_on_exit)
    signal.signal(signal.SIGINT, quit_on_exit)


# Browser detection configuration
# Each entry: (name, type, paths) where type is 'chromium' or 'firefox'
KNOWN_BROWSERS = [
    ("Chrome", "chromium", [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
        "/usr/bin/google-chrome",  # Linux
        "/usr/bin/google-chrome-stable",  # Linux alternate
        "C:/Program Files/Google/Chrome/Application/chrome.exe",  # Windows
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",  # Windows x86
    ]),
    ("Brave", "chromium", [
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",  # macOS
        "/usr/bin/brave-browser",  # Linux
        "/usr/bin/brave",  # Linux alternate
        "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe",  # Windows
    ]),
    ("Edge", "chromium", [
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",  # macOS
        "/usr/bin/microsoft-edge",  # Linux
        "/usr/bin/microsoft-edge-stable",  # Linux alternate
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",  # Windows
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",  # Windows
    ]),
    ("Chromium", "chromium", [
        "/Applications/Chromium.app/Contents/MacOS/Chromium",  # macOS
        "/usr/bin/chromium",  # Linux
        "/usr/bin/chromium-browser",  # Linux alternate
        "/snap/bin/chromium",  # Linux snap
        "C:/Program Files/Chromium/Application/chrome.exe",  # Windows
    ]),
    ("Opera", "chromium", [
        "/Applications/Opera.app/Contents/MacOS/Opera",  # macOS
        "/usr/bin/opera",  # Linux
        "C:/Program Files/Opera/launcher.exe",  # Windows
    ]),
    ("Vivaldi", "chromium", [
        "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",  # macOS
        "/usr/bin/vivaldi",  # Linux
        "/usr/bin/vivaldi-stable",  # Linux alternate
        "C:/Program Files/Vivaldi/Application/vivaldi.exe",  # Windows
    ]),
    ("Arc", "chromium", [
        "/Applications/Arc.app/Contents/MacOS/Arc",  # macOS
    ]),
    ("Firefox", "firefox", [
        "/Applications/Firefox.app/Contents/MacOS/firefox",  # macOS
        "/usr/bin/firefox",  # Linux
        "/snap/bin/firefox",  # Linux snap
        "C:/Program Files/Mozilla Firefox/firefox.exe",  # Windows
        "C:/Program Files (x86)/Mozilla Firefox/firefox.exe",  # Windows x86
    ]),
]


def detect_browsers():
    """Auto-detect installed browsers and return list of (name, type, path) tuples."""
    detected = []
    
    # Check for custom browser path via environment variable
    custom_path = os.environ.get("BROWSER_PATH")
    if custom_path and os.path.exists(custom_path):
        browser_type = os.environ.get("BROWSER_TYPE", "chromium")
        detected.append(("Custom", browser_type, custom_path))
    
    # Scan for known browsers
    for name, browser_type, paths in KNOWN_BROWSERS:
        for path in paths:
            if os.path.exists(path):
                detected.append((name, browser_type, path))
                break
    
    return detected


def try_chromium_browser(name, binary_path, exceptions, headless=True):
    """Try to create a Chromium-based browser driver."""
    driver = None

    if HAS_WEBDRIVER_MANAGER:
        try:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            
            # Enable logging for debugging
            options.set_capability('goog:loggingPrefs', {'browser': 'ALL', 'performance': 'ALL'})
            
            if binary_path:
                options.binary_location = binary_path
            
            # Use appropriate ChromeType for known browsers
            if "brave" in name.lower():
                chrome_type = ChromeType.BRAVE
            elif "chromium" in name.lower():
                chrome_type = ChromeType.CHROMIUM
            else:
                chrome_type = ChromeType.GOOGLE
            
            service = ChromeService(ChromeDriverManager(chrome_type=chrome_type).install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)
            driver.set_page_load_timeout(30)
            process_quit(driver)
            return driver
        except Exception as e:
            exceptions.append((f'{name} (webdriver-manager):', str(e)[:200]))
    
    # Fallback without webdriver-manager
    try:
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        
        # Enable logging
        options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        
        if binary_path:
            options.binary_location = binary_path
        driver = webdriver.Chrome(options=options)
        driver.set_script_timeout(SCRIPT_TIMEOUT_SECONDS)
        driver.set_page_load_timeout(30)
        process_quit(driver)
        return driver
    except Exception as e:
        exceptions.append((f'{name} (fallback):', str(e)[:200]))
    
    return None


def get_browser_driver(headless=True):
    """Get a browser driver, auto-detecting available browsers."""
    exceptions = []
    # Detect installed browsers
    detected_browsers = detect_browsers()
    if detected_browsers:
        print(f"Detected browsers: {', '.join(b[0] for b in detected_browsers)}")
    # Try each detected browser
    for name, browser_type, binary_path in detected_browsers:
        if browser_type == "chromium":
            driver = try_chromium_browser(name, binary_path, exceptions, headless)
        else:  # firefox
            driver = try_firefox_browser(name, binary_path, exceptions, headless)
        if driver:
            mode = "headless" if headless else "visible"
            print(f"Using {name} browser ({mode})")
            return driver
    # No detected browsers worked, try generic fallback (driver in PATH)
    print("No browsers detected, trying generic fallback...")
    driver = try_chromium_browser("Chrome (generic)", None, exceptions, headless)
    if driver:
        return driver
    driver = try_firefox_browser("Firefox (generic)", None, exceptions, headless)
    if driver:
        return driver
    # Nothing worked, show helpful error
    cls()
    print("=" * 60)
    print("BROWSER NOT FOUND")
    print("=" * 60)
    print()
    print("This script needs a browser to work. Supported browsers:")
    print()
    print("  Chromium-based (any of these):")
    print("    - Google Chrome")
    print("    - Brave")
    print("    - Microsoft Edge")
    print("    - Chromium")
    print("    - Opera")
    print("    - Vivaldi")
    print("    - Arc")
    print()
    print("  Or Firefox")
    print()
    print("Custom browser path:")
    print("  Set BROWSER_PATH environment variable to your browser executable")
    print("  Set BROWSER_TYPE to 'chromium' or 'firefox' (default: chromium)")
    print()
    print("  Example:")
    print("    export BROWSER_PATH='/path/to/my/browser'")
    print("    export BROWSER_TYPE='chromium'")
    print()
    if exceptions:
        print("Debug info:")
        for browser, exception in exceptions:
            print(f"  {browser} {exception}")

    time.sleep(VERY_LONG_SLEEP_SECONDS)
    sys.exit(1)

MODE_PROMPT = """Welcome to the Humble Exporter!
Which key export mode would you like to use?

[1] Auto-Redeem
[2] Export keys
[3] Humble Choice chooser
"""

def prompt_mode(order_details,humble_session):
    """Prompt user for operation mode."""
    global AUTO_MODE
    if AUTO_MODE:
        print(MODE_PROMPT)
        print("Choose 1, 2, or 3: 1 (auto-mode)")
        return "1"
    mode = None
    while mode not in ["1","2","3"]:
        print(MODE_PROMPT)
        mode = input("Choose 1, 2, or 3: ").strip()
        if mode in ["1","2","3"]:
            return mode
        print("Invalid mode")
    return mode


def valid_steam_key(key):
    """Validate Steam key format (XXXXX-XXXXX-XXXXX)."""
    # Steam keys are in the format of AAAAA-BBBBB-CCCCC
    if not isinstance(key, str):
        return False
    key_parts = key.split("-")
    return (
        len(key) == 17
        and len(key_parts) == 3
        and all(len(part) == 5 for part in key_parts)
    )


def is_friend_or_coop_key(key, confidence_threshold=0.8):
    """
    Detect if a key is a friend/co-op pass that should not be redeemed.
    Returns (is_friend_key, reason, confidence) tuple.
    Confidence: 1.0 = certain, 0.5-0.99 = likely, <0.5 = uncertain
    """
    import re
    
    # High confidence patterns (definitely friend keys)
    HIGH_CONFIDENCE_PATTERNS = [
        'friend pass', 'friends pass', 'friend\'s pass',
        'guest pass', 'guest key', 'guest access',
        'extra copy', 'bonus copy',
        'co-op pass', 'coop pass', 'co op pass',
    ]
    
    # Medium confidence patterns (probably friend keys)
    MEDIUM_CONFIDENCE_PATTERNS = [
        'friend key', 'friends key', 'friend\'s key',
        'multiplayer pass', 'multi-player pass',
        'companion pass',
        'invite key', 'invitation key', 'invite pass',
        'additional copy', 'additional key',
        '2-pack', '3-pack', '4-pack',  # Multi-packs often have extra copies
        '2 pack', '3 pack', '4 pack',
        'gift copy', 'giftable copy', 'gift key',
        'buddy pass', 'buddy key',
        'spare copy', 'spare key',
    ]
    
    # Low confidence patterns (might be friend keys)
    LOW_CONFIDENCE_PATTERNS = [
        'extra', 'bonus', 'additional',
    ]
    
    # Exact match patterns (must match exactly, not substring)
    EXACT_MATCH_PATTERNS = [
        'extra',  # Too generic as substring
        'bonus',  # Too generic as substring
    ]
    
    # Common suffixes indicating friend keys
    SUFFIX_PATTERNS = [
        ' - extra', ' (extra)', '[extra]',
        ' - friend', ' (friend)', '[friend]',
        ' - guest', ' (guest)', '[guest]',
        ' - gift', ' (gift)', '[gift]',
    ]
    
    # Specific known games with friend keys
    KNOWN_FRIEND_GAMES = [
        'minion masters',  # Known for friend keys
        'dont starve together',  # Has friend copies
        "don't starve together",  # Alternate spelling
        'portal 2',  # Has extra copy
        'serious sam',  # Multiple friend keys
        'dead island',  # Has guest passes
        'killing floor',  # Has guest passes
        'castle crashers',  # Has extra copies
        'battleblock theater',  # Has extra copies
        'counter-strike',  # Has guest passes
        'half-life 2',  # Has guest passes
        'dead by daylight - stranger things',  # Friend pass DLC
        'insurgency',  # Has extra copies in bundles
        'arma',  # Often includes friend passes
    ]
    
    # DLC/Content that shouldn't be auto-redeemed
    NON_GAME_CONTENT = [
        'soundtrack', 'ost', 'original soundtrack',
        'artbook', 'art book',
        'digital comic', 'comic book',
        'wallpaper', 'avatar', 'badge',
    ]
    
    # Load custom patterns with confidence levels
    try:
        with open("friend_key_exclusions.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    # Format: "pattern" or "HIGH:pattern" or "MEDIUM:pattern" or "LOW:pattern" or "EXACT:pattern"
                    if ":" in line:
                        prefix, pattern = line.split(":", 1)
                        prefix = prefix.strip().upper()
                        pattern = pattern.strip().lower()
                        if prefix == "HIGH":
                            HIGH_CONFIDENCE_PATTERNS.append(pattern)
                        elif prefix == "MEDIUM":
                            MEDIUM_CONFIDENCE_PATTERNS.append(pattern)
                        elif prefix == "LOW":
                            LOW_CONFIDENCE_PATTERNS.append(pattern)
                        elif prefix == "EXACT":
                            EXACT_MATCH_PATTERNS.append(pattern)
                        else:
                            # Default to medium confidence for custom patterns
                            MEDIUM_CONFIDENCE_PATTERNS.append(pattern)
                    else:
                        # Default to medium confidence for custom patterns
                        MEDIUM_CONFIDENCE_PATTERNS.append(line.lower())
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[DEBUG] Error loading friend_key_exclusions.txt: {e}")
    
    # Fields to check
    human_name = key.get('human_name', '').lower()
    machine_name = key.get('machine_name', '').lower()
    key_type = key.get('key_type_human_name', '').lower()
    
    # Check high confidence patterns first
    for pattern in HIGH_CONFIDENCE_PATTERNS:
        if pattern in human_name:
            return True, f"human_name contains '{pattern}'", 1.0
        if pattern in machine_name:
            return True, f"machine_name contains '{pattern}'", 1.0
        if pattern in key_type:
            return True, f"key_type contains '{pattern}'", 1.0
    
    # Check suffix patterns (high confidence)
    for pattern in SUFFIX_PATTERNS:
        if human_name.endswith(pattern):
            return True, f"human_name ends with '{pattern}'", 1.0
        if machine_name.endswith(pattern):
            return True, f"machine_name ends with '{pattern}'", 1.0
    
    # Check known friend games (medium-high confidence)
    for pattern in KNOWN_FRIEND_GAMES:
        if pattern in human_name:
            return True, f"known friend game: '{pattern}'", 0.85
        if pattern in machine_name:
            return True, f"known friend game: '{pattern}'", 0.85
    
    # Check medium confidence patterns
    for pattern in MEDIUM_CONFIDENCE_PATTERNS:
        if pattern in human_name:
            return True, f"human_name contains '{pattern}'", 0.75
        if pattern in machine_name:
            return True, f"machine_name contains '{pattern}'", 0.75
        if pattern in key_type:
            return True, f"key_type contains '{pattern}'", 0.75
    
    # Check non-game content (medium confidence)
    for pattern in NON_GAME_CONTENT:
        if pattern in human_name:
            return True, f"non-game content: '{pattern}'", 0.7
        if pattern in machine_name:
            return True, f"non-game content: '{pattern}'", 0.7
    
    # Check low confidence patterns with word boundaries
    for pattern in LOW_CONFIDENCE_PATTERNS:
        pattern_regex = r'\b' + re.escape(pattern) + r'\b'
        if re.search(pattern_regex, human_name):
            return True, f"human_name contains '{pattern}' (low confidence)", 0.5
        if re.search(pattern_regex, machine_name):
            return True, f"machine_name contains '{pattern}' (low confidence)", 0.5
        if re.search(pattern_regex, key_type):
            return True, f"key_type contains '{pattern}' (low confidence)", 0.5
    
    # Check exact match patterns (word boundaries)
    for pattern in EXACT_MATCH_PATTERNS:
        pattern_regex = r'\b' + re.escape(pattern) + r'\b'
        if re.search(pattern_regex, human_name):
            return True, f"human_name exactly matches '{pattern}'", 0.6
        if re.search(pattern_regex, machine_name):
            return True, f"machine_name exactly matches '{pattern}'", 0.6
        if re.search(pattern_regex, key_type):
            return True, f"key_type exactly matches '{pattern}'", 0.6
    
    return False, "", 0.0


def save_friend_key(key, reason="", confidence=1.0):
    """Save friend/co-op keys to a separate CSV for gifting with enhanced metadata."""
    filename = CSVFiles.FRIEND_KEYS
    
    # Check if we need to write header
    file_needs_header = not os.path.exists(filename) or os.path.getsize(filename) == 0
    
    # Check for duplicates before writing
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 4:
                        existing_gamekey = row[3].strip()
                        existing_name = row[0].strip().lower()
                        if existing_gamekey == key.get('gamekey', '') and existing_name == key.get('human_name', '').lower():
                            # Duplicate found - skip writing
                            return
        except Exception:
            pass
    
    with open(filename, "a", encoding="utf-8-sig", newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        if file_needs_header:
            writer.writerow(["human_name", "key_type", "redeemed_key_val", "gamekey", "steam_app_id", "reason", "confidence"])
        writer.writerow([
            key.get('human_name', ''),
            key.get('key_type_human_name', 'Unknown'),
            key.get('redeemed_key_val', 'NOT_REVEALED'),
            key.get('gamekey', ''),
            key.get('steam_app_id', ''),
            reason,
            f"{int(confidence * 100)}%"
        ])
        f.flush()


def review_uncertain_friend_keys(uncertain_keys):
    """
    Let users review keys flagged as friend keys with low confidence.
    Returns list of keys to skip (confirmed friend keys).
    """
    global AUTO_MODE
    
    if not uncertain_keys:
        return []
    
    if AUTO_MODE:
        # In auto mode, skip all uncertain keys (safer)
        print(f"(auto-mode: skipping {len(uncertain_keys)} uncertain friend/co-op keys)")
        return uncertain_keys
    
    print(f"\n{'='*60}")
    print(f"REVIEW: {len(uncertain_keys)} keys might be friend/co-op keys")
    print(f"{'='*60}")
    print("These keys have patterns suggesting they might be friend keys,")
    print("but we're not 100% certain. Please review:\n")
    
    confirmed_friend_keys = []
    
    for i, (key, reason, confidence) in enumerate(uncertain_keys, 1):
        print(f"\n[{i}/{len(uncertain_keys)}] {key['human_name']}")
        print(f"  Reason: {reason}")
        print(f"  Confidence: {int(confidence * 100)}%")
        print(f"  Type: {key.get('key_type_human_name', 'Unknown')}")
        
        is_friend = prompt_yes_no(f"  Is this a friend/co-op key that should be saved for gifting?", default_yes=True)
        if is_friend:
            confirmed_friend_keys.append(key)
    
    return confirmed_friend_keys


def create_sample_friend_exclusions():
    """Create a sample friend_key_exclusions.txt if it doesn't exist."""
    filename = "friend_key_exclusions.txt"
    if os.path.exists(filename):
        return  # Don't overwrite existing file
    
    sample_content = """# Friend Key Exclusions Configuration
# Add patterns here (one per line) to skip keys that should be gifted, not redeemed
# Lines starting with # are comments and will be ignored

# === SYNTAX ===
# Substring match (default): pattern
# Exact word match: EXACT:pattern
# High confidence: HIGH:pattern
# Medium confidence: MEDIUM:pattern
# Low confidence: LOW:pattern

# === EXAMPLES ===
# my custom pattern
# EXACT:bonus
# HIGH:special game name
# MEDIUM:maybe friend key
# LOW:uncertain pattern

# === COMMON ADDITIONS ===
# Uncomment (remove #) to enable:

# Game-specific friend passes
# payday 2
# rocket league
# terraria

# Content types you want to gift
# deluxe edition
# premium edition
# collector's edition

# Non-game items
# soundtrack
# artbook
# making of
"""
    
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(sample_content)
        print(f"[INFO] Created sample {filename} - customize it to add your own patterns")
    except Exception as e:
        print(f"[DEBUG] Could not create sample {filename}: {e}")


class SecureCookieManager:
    """
    Manages encrypted cookie storage with backward compatibility.
    
    Features:
    - Encrypts cookies using Fernet (AES-128)
    - Backward compatible with existing unencrypted cookies
    - Automatic migration from unencrypted to encrypted
    - Persistent key storage (for auto-mode)
    """
    
    def __init__(self):
        self.key_file = Path(".cookie_encryption_key")
        self.cipher = None
        self.encryption_enabled = HAS_ENCRYPTION
        
        if not HAS_ENCRYPTION:
            # Silent fallback - don't spam console in auto-mode
            return
        
        # Try to load existing key
        if self.key_file.exists():
            try:
                with self.key_file.open("rb") as f:
                    key = f.read()
                self.cipher = Fernet(key)
            except Exception as e:
                print(f"[WARNING] Could not load encryption key: {e}")
                print("          Generating new key. Old cookies will need to be re-created.")
                self._generate_key()
        else:
            self._generate_key()
    
    def _generate_key(self):
        """Generate and store a new encryption key."""
        if not HAS_ENCRYPTION:
            return
        
        key = Fernet.generate_key()
        try:
            with self.key_file.open("wb") as f:
                f.write(key)
            self.key_file.chmod(0o600)
            self.cipher = Fernet(key)
        except Exception as e:
            print(f"[WARNING] Could not save encryption key: {e}")
            print("          Cookies will be stored unencrypted.")
            self.encryption_enabled = False
    
    def save_cookies(self, cookie_file, cookies):
        """
        Save cookies with encryption if available.
        
        Args:
            cookie_file: Path to cookie file (str or Path)
            cookies: Cookies to save (dict or list)
        
        Returns:
            bool: True if successful
        """
        cookie_path = Path(cookie_file) if not isinstance(cookie_file, Path) else cookie_file
        
        try:
            pickled = pickle.dumps(cookies)
            
            if self.encryption_enabled and self.cipher:
                # Encrypt the cookies
                encrypted = self.cipher.encrypt(pickled)
                # Add a marker to indicate encrypted format
                data = b"ENCRYPTED_V1:" + encrypted
            else:
                # Fallback to unencrypted (backward compatible)
                data = pickled
            
            with cookie_path.open("wb") as f:
                f.write(data)
            
            # Set restrictive permissions
            try:
                cookie_path.chmod(0o600)
            except (OSError, AttributeError):
                pass  # chmod not available on Windows
            
            return True
        except Exception as e:
            print(f"[DEBUG] Failed to save cookies to {cookie_file}: {e}")
            return False
    
    def load_cookies(self, cookie_file):
        """
        Load cookies with automatic format detection (encrypted vs unencrypted).
        
        Args:
            cookie_file: Path to cookie file (str or Path)
        
        Returns:
            Cookies object or None if failed
        """
        cookie_path = Path(cookie_file) if not isinstance(cookie_file, Path) else cookie_file
        
        if not cookie_path.exists():
            return None
        
        try:
            with cookie_path.open("rb") as f:
                data = f.read()
            
            # Check if data is encrypted (has our marker)
            if data.startswith(b"ENCRYPTED_V1:"):
                if not self.encryption_enabled or not self.cipher:
                    print(f"[ERROR] Cookie file is encrypted but encryption is not available.")
                    print(f"        Install cryptography: pip install cryptography")
                    return None
                
                # Strip marker and decrypt
                encrypted_data = data[len(b"ENCRYPTED_V1:"):]
                try:
                    pickled = self.cipher.decrypt(encrypted_data)
                except Exception as e:
                    print(f"[ERROR] Failed to decrypt cookies: {e}")
                    print(f"        The encryption key may have changed.")
                    print(f"        Delete {cookie_file} and log in again.")
                    return None
            else:
                # Legacy unencrypted format
                pickled = data
                
                # Auto-migrate to encrypted format
                if self.encryption_enabled and self.cipher:
                    cookies = pickle.loads(pickled)
                    self.save_cookies(cookie_file, cookies)
                    return cookies
            
            return pickle.loads(pickled)
        except Exception as e:
            print(f"[DEBUG] Failed to load cookies from {cookie_file}: {e}")
            return None

# Global cookie manager instance
_cookie_manager = None

def get_cookie_manager():
    """Get or create the global cookie manager instance."""
    global _cookie_manager
    if _cookie_manager is None:
        _cookie_manager = SecureCookieManager()
    return _cookie_manager


def try_recover_cookies(cookie_file, session):
    """Try to load saved cookies from file using secure storage."""
    manager = get_cookie_manager()
    cookies = manager.load_cookies(cookie_file)
    
    if not cookies:
        return False
    
    try:
        if type(session) is requests.Session:
            # handle Steam session
            session.cookies.update(cookies)
        else:
            # handle WebDriver
            for cookie in cookies:
                try:
                    session.add_cookie(cookie)
                except Exception:
                    # Skip invalid cookies
                    pass
        return True
    except Exception as e:
        print(f"[DEBUG] Failed to apply cookies from {cookie_file}: {e}")
        return False


def export_cookies(cookie_file, session):
    """
    Save cookies to file with encryption.
    
    Cookies are encrypted using Fernet (AES-128) if the cryptography package is available.
    Falls back to unencrypted storage with restrictive permissions (600) if not.
    
    Install encryption support with: pip install cryptography
    """
    try:
        cookies = None
        if type(session) is requests.Session:
            # handle Steam session
            cookies = session.cookies
        else:
            # handle WebDriver
            cookies = session.get_cookies()
        
        manager = get_cookie_manager()
        return manager.save_cookies(cookie_file, cookies)
    except Exception as e:
        print(f"[DEBUG] Failed to export cookies to {cookie_file}: {e}")
        return False

is_logged_in = '''
var done = arguments[arguments.length-1];

fetch("https://www.humblebundle.com/home/library").then(r => {done(!r.redirected)})
'''

def verify_logins_session(session):
    """Verify login status for Humble and/or Steam. Returns [humble_status, steam_status]."""
    if type(session) is requests.Session:
        loggedin = session.get(STEAM_KEYS_PAGE, allow_redirects=False).status_code not in (301,302)
        return [False,loggedin]
    else:
        try:
            humble_logged_in = session.execute_async_script(is_logged_in)
            return [humble_logged_in, False]
        except TimeoutException:
            print("[DEBUG] Timeout verifying Humble login status")
            return [False, False]
        except Exception as e:
            print(f"[DEBUG] Error verifying login: {e}")
            return [False, False]

def do_login(driver: webdriver.Remote, payload: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    """
    Perform login POST request via browser.
    
    Args:
        driver: Selenium WebDriver instance
        payload: Login payload dictionary with username, password, etc.
    
    Returns:
        Tuple of (HTTP status code, JSON response dictionary)
    """
    auth,login_json = perform_post(driver,HUMBLE_LOGIN_API,payload)
    if auth not in (HTTPStatus.OK, HTTPStatus.UNAUTHORIZED):
        print(f"humblebundle.com has responded with an error (HTTP status code {auth}: {responses.get(auth, 'Unknown')}).")
        time.sleep(VERY_LONG_SLEEP_SECONDS)
        sys.exit(1)
    return auth,login_json

def humble_login(driver, is_headless=True):
    """Login to Humble. Returns (driver, success) - driver may be different if we switched to visible mode."""
    global AUTO_MODE
    cls()
    # First check if we have saved cookies - go to main site to load them
    cookie_file = Path(".humblecookies")
    cookies_exist = cookie_file.exists()
    
    if cookies_exist:
        try:
            driver.get("https://www.humblebundle.com/")
            time.sleep(DEFAULT_SLEEP_SECONDS)  # Let cookies load
            if try_recover_cookies(cookie_file, driver):
                time.sleep(SHORT_SLEEP_SECONDS)
                if verify_logins_session(driver)[0]:
                    print("Using saved Humble session.")
                    return driver, True
            print("Saved session expired, need to log in again.")
        except Exception as e:
            print(f"[DEBUG] Error loading saved session: {e}")
    
    # In AUTO_MODE, we require valid cookies - exit if they don't exist or are invalid
    if AUTO_MODE:
        print("")
        print("="*60)
        print("HUMBLE SESSION EXPIRED OR MISSING")
        print("="*60)
        if not cookies_exist:
            print("The Humble login cookies file (.humblecookies) is missing.")
        else:
            print("The Humble login cookies are stale or invalid.")
        print("")
        print("To fix this, run the script manually to re-login:")
        print("  python3 humblesteamkeysredeemer.py")
        print("")
        print("This will prompt for your credentials and 2FA code.")
        print("Once logged in, restart the daemon.")
        print("="*60)
        driver.quit()
        sys.exit(2)  # Exit code 2 = stale/missing cookies

    # Go to login page (only in non-auto mode - try API login first)
    try:
        driver.get(HUMBLE_LOGIN_PAGE)
        time.sleep(DEFAULT_SLEEP_SECONDS)  # Let page fully load
    except Exception as e:
        print(f"Error loading Humble login page: {e}")
        driver.quit()
        sys.exit(1)

    # Try automatic API login first (works in headless if Cloudflare allows)
    authorized = False
    while not authorized:
        username = input("Humble Email: ")
        password = pwinput()

        payload = {
            "access_token": "",
            "access_token_provider_id": "",
            "goto": "/",
            "qs": "",
            "username": username,
            "password": password,
        }

        try:
            auth, login_json = do_login(driver, payload)
        except TimeoutException as e:
            print(f"[DEBUG] Login request timed out: {e}")
            print("This may be due to Cloudflare blocking. Switching to visible browser for manual login...")
            # Only switch to visible browser if we're currently headless
            if is_headless:
                driver.quit()
                driver = get_browser_driver(headless=False)
            return humble_login_manual(driver), True
        except Exception as e:
            print(f"[DEBUG] Auto-login failed: {e}")
            print(f"[DEBUG] Exception type: {type(e).__name__}")
            # Only switch to visible browser if we're currently headless
            if is_headless:
                print("Switching to visible browser for manual login...")
                driver.quit()
                driver = get_browser_driver(headless=False)
            return humble_login_manual(driver), True

        # Debug: show what we got back
        if "two_factor_required" in login_json or "humble_guard_required" in login_json:
            print(f"[DEBUG] 2FA required. Response keys: {list(login_json.keys())}")
            if "errors" in login_json:
                print(f"[DEBUG] Errors in response: {login_json['errors']}")

        if "errors" in login_json and "username" in login_json["errors"]:
            # Unknown email OR mismatched password
            print(login_json["errors"]["username"][0])
            continue

        # Check if login succeeded without 2FA
        if auth == HTTPStatus.OK and "two_factor_required" not in login_json and "humble_guard_required" not in login_json:
            authorized = True
            break

        # Handle 2FA - simplified logic: if either flag is present, prompt for code
        while "humble_guard_required" in login_json or "two_factor_required" in login_json:
            # There may be differences for Humble's SMS 2FA, haven't tested.
            try:
                if "humble_guard_required" in login_json:
                    humble_guard_code = input("Please enter the Humble security code (check email): ")
                    payload["guard"] = humble_guard_code.upper()
                    # Humble security codes are case-sensitive via API, but luckily it's all uppercase!
                    auth, login_json = do_login(driver, payload)

                    if (
                        "user_terms_opt_in_data" in login_json
                        and login_json["user_terms_opt_in_data"]["needs_to_opt_in"]
                    ):
                        # Nope, not messing with this.
                        print(
                            "There's been an update to the TOS, please sign in to Humble on your browser."
                        )
                        sys.exit(1)
                elif "two_factor_required" in login_json:
                    # Simplified: if two_factor_required is present, prompt for code
                    # Don't require specific error structure
                    code = input("Please enter 2FA code: ")
                    payload["code"] = code
                    auth, login_json = do_login(driver, payload)
                else:
                    # Shouldn't reach here, but handle gracefully
                    print(f"[DEBUG] Unexpected 2FA state. login_json keys: {list(login_json.keys())}")
                    if "errors" in login_json:
                        print(f"[DEBUG] Errors: {login_json['errors']}")
                    break
                
                # Check for success
                if auth == HTTPStatus.OK and "two_factor_required" not in login_json and "humble_guard_required" not in login_json:
                    authorized = True
                    break
                    
            except TimeoutException as e:
                print(f"[DEBUG] 2FA submission timed out: {e}")
                # Only switch to visible browser if we're currently headless
                if is_headless:
                    print("Switching to visible browser for manual login...")
                    driver.quit()
                    driver = get_browser_driver(headless=False)
                return humble_login_manual(driver), True
            except Exception as e:
                print(f"[DEBUG] 2FA submission failed: {e}")
                print(f"[DEBUG] Exception type: {type(e).__name__}")
                import traceback
                traceback.print_exc()
                # Only switch to visible browser if we're currently headless
                if is_headless:
                    print("Switching to visible browser for manual login...")
                    driver.quit()
                    driver = get_browser_driver(headless=False)
                return humble_login_manual(driver), True

        export_cookies(".humblecookies", driver)
        return driver, True


def humble_login_manual(driver):
    """Manual login fallback when API is blocked by Cloudflare. Returns the driver."""
    global AUTO_MODE
    if AUTO_MODE:
        print("")
        print("="*60)
        print("HUMBLE SESSION EXPIRED")
        print("="*60)
        print("The Humble login cookies are stale or Cloudflare is blocking.")
        print("")
        print("To fix this, run the script manually to re-login:")
        print("  python3 humblesteamkeysredeemer.py")
        print("")
        print("Then restart the daemon.")
        print("="*60)
        sys.exit(2)  # Exit code 2 = stale cookies
    print("\n" + "="*60)
    print("MANUAL LOGIN REQUIRED")
    print("="*60)
    print("A browser window is open to the Humble Bundle login page.")
    print("Please log in manually (handle any CAPTCHAs or 2FA).")
    print("Once logged in and you see your library, press Enter here.")
    print("="*60 + "\n")
    driver.get(HUMBLE_LOGIN_PAGE)
    input("Press Enter after you've logged in successfully...")
    # Verify login worked
    driver.get("https://www.humblebundle.com/home/library")
    time.sleep(DEFAULT_SLEEP_SECONDS)
    if "login" in driver.current_url.lower():
        print("Login verification failed - still on login page. Please try again.")
        return humble_login_manual(driver)  # Retry
    export_cookies(".humblecookies", driver)
    return driver


def steam_login():
    """Login to Steam web. Returns authenticated session."""
    global AUTO_MODE
    # Sign into Steam web

    # Attempt to use saved session
    r = requests.Session()
    if try_recover_cookies(".steamcookies", r) and verify_logins_session(r)[1]:
        return r

    # Saved state doesn't work
    if AUTO_MODE:
        print("")
        print("="*60)
        print("STEAM SESSION EXPIRED")
        print("="*60)
        print("The Steam login cookies are stale or missing.")
        print("")
        print("To fix this, run the script manually to re-login:")
        print("  python3 humblesteamkeysredeemer.py")
        print("")
        print("Then restart the daemon.")
        print("="*60)
        sys.exit(2)  # Exit code 2 = stale cookies
    # Prompt user to sign in.
    s_username = input("Steam Username: ")
    user = wa.WebAuth(s_username)
    try:
        session = user.cli_login()
        export_cookies(".steamcookies", session)
        return session
    except KeyError as e:
        if "'client_id'" in str(e) or "client_id" in str(e):
            print(f"Error logging into Steam: Missing 'client_id' parameter")
            print("This may be due to a Steam API change or library issue.")
            print("")
            print("Possible solutions:")
            print("1. Update the steam library: pip install --upgrade 'steam @ git+https://github.com/FailSpy/steam-py-lib@master'")
            print("2. Check if Steam's login API has changed")
            print("3. Try logging in via browser and copying cookies manually")
        else:
            print(f"Error logging into Steam (KeyError): {e}")
        print("Please try again.")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"Error logging into Steam: {e}")
        print(f"Exception type: {type(e).__name__}")
        print("Please try again.")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def redeem_humble_key(sess: webdriver.Remote, tpk: Dict[str, Any], max_retries: int = 3) -> str:
    """
    Redeem a key on Humble Bundle to reveal the actual Steam key.
    
    Args:
        sess: Selenium WebDriver instance (browser session)
        tpk: Key dictionary containing gamekey, machine_name, human_name, etc.
        max_retries: Maximum number of retry attempts
    
    Returns:
        Revealed Steam key string, "EXPIRED" string for expired keys (converted to enum in write_key),
        or empty string on error
    """
    payload = {
        "keytype": tpk["machine_name"], 
        "key": tpk["gamekey"], 
        "keyindex": tpk.get("keyindex", 0)
    }
    
    for attempt in range(max_retries):
        try:
            # Validate session before attempting
            if not validate_session(sess):
                print(f"  -> Invalid session detected, attempting to recover...")
                if not refresh_page_if_needed(sess, "https://www.humblebundle.com/home/library"):
                    if attempt < max_retries - 1:
                        print(f"  -> Recovery failed, retrying... (attempt {attempt + 2}/{max_retries})")
                        time.sleep(DEFAULT_SLEEP_SECONDS)
                        continue
                    print(f"  -> Failed to recover session for {tpk['human_name']}")
                    return ""
                time.sleep(DEFAULT_SLEEP_SECONDS)
            
            status, respjson = perform_post(sess, HUMBLE_REDEEM_API, payload)
            
            if status != 200:
                print(f"  -> HTTP {status} while redeeming {tpk['human_name']}")
                if attempt < max_retries - 1:
                    print(f"  -> Retrying... (attempt {attempt + 2}/{max_retries})")
                    time.sleep(DEFAULT_SLEEP_SECONDS)
                    continue
                return ""
            
            if "error_msg" in respjson or not respjson.get("success", False):
                error_msg = respjson.get("error_msg", "Unknown error")
                print(f"  -> Error redeeming key: {error_msg}")
                
                # Check for expired key - return as string, will be converted to enum in write_key
                if "expired" in error_msg.lower():
                    return "EXPIRED"  # String value, converted to SteamErrorCode.EXPIRED in write_key()
                
                # Don't retry on explicit errors from Humble
                return ""
            
            try:
                return respjson["key"]
            except KeyError:
                print(f"  -> Warning: Unexpected response format for {tpk['human_name']}")
                return str(respjson)
                
        except TimeoutException:
            print(f"  -> Timeout (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(LONG_SLEEP_SECONDS)
                continue
            return ""
            
        except (InvalidSessionIdException, NoSuchWindowException):
            print(f"  -> Session invalid (attempt {attempt + 1}/{max_retries})")
            # Don't try to recover here - let the caller handle it
            # This exception will propagate up to redeem_steam_keys() which has better recovery logic
            if attempt < max_retries - 1:
                # Try simple refresh as last resort
                print(f"  -> Attempting to recover session...")
                try:
                    sess.get("https://www.humblebundle.com/home/library")
                    time.sleep(LONG_SLEEP_SECONDS)
                except:
                    pass
                continue
            # Return empty string to indicate failure - caller will handle recovery
            return ""
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)[:100]
            print(f"  -> {error_type}: {error_msg}")
            if attempt < max_retries - 1:
                print(f"  -> Retrying... (attempt {attempt + 2}/{max_retries})")
                time.sleep(DEFAULT_SLEEP_SECONDS)
                continue
            return ""
    
    return ""

def get_month_data(humble_session, month, timeout=10):
    """Fetch Humble Choice month data. Needs a requests session, not WebDriver."""
    if type(humble_session) is not requests.Session:
        raise Exception("get_month_data needs a configured requests session")
    # Add timeout to prevent hanging
    r = humble_session.get(HUMBLE_SUB_PAGE + month["product"]["choice_url"], timeout=timeout)

    data_indicator = f'<script id="webpack-monthly-product-data" type="application/json">'
    jsondata = r.text.split(data_indicator)[1].split("</script>")[0].strip()
    jsondata = json.loads(jsondata)
    return jsondata["contentChoiceOptions"]


def get_choices(humble_session,order_details):
    """Generator that yields months with available choices."""
    months = [
        month for month in order_details 
        if "choice_url" in month.get("product", {})
    ]

    # Oldest to Newest order
    months = sorted(months,key=lambda m: m.get("created", 0))
    request_session = requests.Session()
    for cookie in humble_session.get_cookies():
        # convert cookies to requests
        request_session.cookies.set(cookie['name'],cookie['value'],domain=cookie['domain'].replace('www.',''),path=cookie['path'])

    choices = []
    for month in months:
        if month.get("choices_remaining", 0) > 0 or month.get("product", {}).get("is_subs_v3_product",False):
            chosen_games = set(find_dict_keys(month.get("tpkd_dict", {}),"machine_name"))

            month["choice_data"] = get_month_data(request_session,month)
            if not month["choice_data"].get('canRedeemGames',True):
                month["available_choices"] = []
                continue

            v3 = not month["choice_data"].get("usesChoices",True)
            # Needed for choosing
            if v3:
                identifier = "initial"
                choice_options = month["choice_data"]["contentChoiceData"]["game_data"]
            else:
                identifier = "initial" if "initial" in month["choice_data"]["contentChoiceData"] else "initial-classic"
                if identifier not in month["choice_data"]["contentChoiceData"]:
                    for key in month["choice_data"]["contentChoiceData"].keys():
                        if "content_choices" in month["choice_data"]["contentChoiceData"][key]:
                            identifier = key

                choice_options = month["choice_data"]["contentChoiceData"][identifier]["content_choices"]

            # Exclude games that have already been chosen:
            month["available_choices"] = [
                    game[1]
                    for game in choice_options.items()
                    if set(find_dict_keys(game[1],"machine_name")).isdisjoint(chosen_games)
            ]
            month["parent_identifier"] = identifier
            if len(month["available_choices"]):
                yield month


def _redeem_steam(session, key, quiet=False):
    """
    Redeem a Steam key. Returns error code (0 = success).
    Based on https://gist.github.com/snipplets/2156576c2754f8a4c9b43ccb674d5a5d
    """
    if key == "":
        return 0
    cookies_dict = session.cookies.get_dict()
    if "sessionid" not in cookies_dict:
        if not quiet:
            print("Error: Steam sessionid cookie missing. Please re-login to Steam.")
        return 53  # Return error code
    session_id = cookies_dict["sessionid"]
    try:
        r = session.post(
            STEAM_REDEEM_API,
            data={"product_key": key, "sessionid": session_id},
            timeout=30
        )
    except requests.exceptions.Timeout:
        if not quiet:
            print("  -> Timeout while redeeming on Steam. This may be rate limiting or network issues.")
        return 53
    except requests.exceptions.RequestException as e:
        if not quiet:
            print(f"  -> Network error while redeeming on Steam: {e}")
        return 53
    if r.status_code == 403:
        if not quiet:
            print(
                "  -> Steam responded with 403 Forbidden while redeeming. "
                "This is likely rate limiting - Steam limits ~50 keys per hour."
            )
        return 53  # Return rate limit error code
    try:
        blob = r.json()
    except ValueError:
        # Steam occasionally returns HTML or empty responses; treat as transient failure
        body_preview = r.text[:200].replace("\n", " ")
        if not quiet:
            print(f"  -> Error: Steam redemption response was not JSON (status {r.status_code}). Body preview: {body_preview}")
        return 53

    if blob.get("success") == 1:
        for item in blob.get("purchase_receipt_info", {}).get("line_items", []):
            print(f"  ✓ Redeemed {item.get('line_item_description', 'Unknown game')}")
        return 0
    else:
        error_code = blob.get("purchase_result_details")
        if error_code == None:
            # Sometimes purchase_result_details isn't there for some reason, try alt method
            error_code = blob.get("purchase_receipt_info")
            if error_code != None:
                error_code = error_code.get("result_detail")
        error_code = error_code or 53

        error_messages = {
            14: "The product code you've entered is not valid. Please double check to see if you've mistyped your key.",
            15: "The product code you've entered has already been activated by a different Steam account.",
            53: "There have been too many recent activation attempts. Rate limited - wait and try again later.",
            13: "Sorry, but this product is not available for purchase in this country.",
            9: "This Steam account already owns the product(s) contained in this offer.",
            24: "The product code you've entered requires ownership of another product before activation (DLC/expansion).",
            36: "The product code requires that you first play this game on PlayStation®3.",
            50: "The code you have entered is from a Steam Gift Card or Steam Wallet Code. Redeem at: https://store.steampowered.com/account/redeemwalletcode",
        }
        error_message = error_messages.get(
            error_code,
            f"An unexpected error has occurred (code {error_code}). Your product code has not been redeemed."
        )
        if error_code != 53 or not quiet:
            print(f"  -> {error_message}")
        return error_code


# Global dict for file handles
# Removed global files dict - now using context managers for proper file handling


def remove_from_errored_csv(gamekey, human_name):
    """Remove a successfully redeemed key from errored.csv to prevent re-retrying."""
    errored_file = CSVFiles.ERRORED
    if not os.path.exists(errored_file):
        return
    
    try:
        # Read all entries except the one to remove
        remaining_entries = []
        with open(errored_file, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            
            for row in reader:
                if len(row) >= 2:
                    row_gamekey = row[0].strip()
                    row_name = row[1].strip().lower()
                    # Keep entry if it doesn't match
                    if not (row_gamekey == gamekey and row_name == human_name.lower()):
                        remaining_entries.append(row)
        
        # Rewrite file without the removed entry
        with open(errored_file, "w", encoding="utf-8-sig", newline='') as f:
            writer = csv.writer(f)
            if header:
                writer.writerow(header)
            writer.writerows(remaining_entries)
    except Exception as e:
        print(f"[DEBUG] Failed to remove entry from errored.csv: {e}", file=sys.stderr, flush=True)


def wait_for_rate_limit_clear(
    steam_session,
    key_val: str,
    remaining: int,
    keepalive=None,
    retry_interval: int = RATE_LIMIT_RETRY_INTERVAL_SECONDS,
    check_interval: int = RATE_LIMIT_CHECK_INTERVAL_SECONDS
) -> int:
    """
    Handle Steam rate limiting with progress feedback and session keep-alive.
    
    Waits for Steam's rate limit to clear (~50 keys/hour) with automatic retries.
    Displays progress and keeps the Humble session alive during the wait.
    
    Args:
        steam_session: Authenticated Steam session for redemption attempts
        key_val: Steam key to redeem
        remaining: Number of keys remaining to process
        keepalive: Optional SessionKeepAlive instance to keep Humble session alive
        retry_interval: Seconds between retry attempts (default: 300 = 5 minutes)
        check_interval: Seconds between status checks (default: 10)
    
    Returns:
        Final redemption status code (53 = still rate limited, other = success/failure)
    """
    seconds_waited = 0
    
    while True:
        minutes_waited = seconds_waited // 60
        next_retry = (retry_interval - (seconds_waited % retry_interval)) // 60
        print(
            f"Rate limited. Waited {minutes_waited}m, "
            f"retrying in {next_retry}m (limit clears in ~1hr) - "
            f"{remaining} keys remaining   ",
            end="\r",
            flush=True
        )
        
        time.sleep(check_interval)
        seconds_waited += check_interval
        
        # Keep session alive periodically
        if keepalive and seconds_waited % 60 == 0:  # Every minute
            keepalive.check()
        
        # Retry after retry_interval
        if seconds_waited % retry_interval == 0:
            print(f"\nRetrying after {seconds_waited // 60} minutes... ({remaining} keys remaining)")
            code = _redeem_steam(steam_session, key_val, quiet=True)
            if code != 53:
                print(f"\n✓ Rate limit cleared! Continuing with {remaining} keys remaining...\n")
                return code
            print("Still rate limited.")
    
    # Note: This function loops until the rate limit clears (code != 53).
    # It will return when Steam accepts the key or another error occurs.


@contextmanager
def get_csv_writer(code: Union[SteamErrorCode, int, str]):
    """
    Context manager for CSV file writing with file locking.
    
    Ensures files are properly closed and prevents corruption when multiple
    processes write to the same file concurrently. Uses fcntl (Unix) or 
    msvcrt (Windows) for file locking.
    
    Note: This protects against multi-process races. For multi-threading
    within a single process, Python's GIL provides thread safety for the
    Python-level operations (cache checks, dict updates).
    
    Args:
        code: Redemption status code (SteamErrorCode enum, int, or "EXPIRED" string for backward compatibility)
    
    Yields:
        File handle for CSV writing
    """
    # Normalize code to ensure consistent handling
    code = normalize_error_code(code)
    
    # Determine filename using mapping (cleaner than if/elif chain)
    filename = CODE_TO_FILE_MAP.get(code, CSVFiles.ERRORED)
    
    # Check if we need to write header
    file_needs_header = not os.path.exists(filename) or os.path.getsize(filename) == 0
    
    f = open(filename, "a", encoding=CSV_ENCODING, newline='')
    lock_acquired = False
    
    try:
        # Acquire exclusive lock for writing
        if HAS_FCNTL:
            # Unix: flock locks entire file
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            lock_acquired = True
        elif HAS_MSVCRT:
            # Windows: byte-range locking - lock 1 byte at offset 0 (standard practice)
            # This is sufficient for preventing concurrent access and avoids wasting address space
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, WINDOWS_LOCK_SIZE)
                    lock_acquired = True
                    break
                except IOError as e:
                    if attempt == max_retries - 1:
                        # Last attempt failed - log but continue (better than failing completely)
                        logging.warning(f"Could not acquire file lock for {filename}: {e}")
                        break
                    time.sleep(0.1)  # Wait 100ms before retry
        
        if file_needs_header:
            f.write("gamekey,human_name,redeemed_key_val\n")
        
        yield f
        f.flush()
        
    finally:
        # Always release lock and close file
        if lock_acquired:
            try:
                if HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                elif HAS_MSVCRT:
                    # Unlock using same size as lock (1 byte)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, WINDOWS_LOCK_SIZE)
            except (OSError, IOError):
                pass  # Ignore unlock errors (file may already be closed)
        
        try:
            f.close()
        except:
            pass  # Ignore close errors


# Global cache for existing keys to avoid O(n²) duplicate checking
# Loaded once at startup and updated as keys are written
# Thread-safe with locking to prevent race conditions in multi-threaded scenarios
_EXISTING_KEYS_CACHE = {}
_CACHE_INITIALIZED = False
_CACHE_LOCK = threading.Lock()  # Thread lock for cache operations

def _initialize_keys_cache():
    """Initialize the existing keys cache by loading all CSV files once."""
    global _CACHE_INITIALIZED, _EXISTING_KEYS_CACHE
    with _CACHE_LOCK:
        if _CACHE_INITIALIZED:
            return
        
        _EXISTING_KEYS_CACHE[CSVFiles.REDEEMED] = get_existing_keys(CSVFiles.REDEEMED)
        _EXISTING_KEYS_CACHE[CSVFiles.ALREADY_OWNED] = get_existing_keys(CSVFiles.ALREADY_OWNED)
        _EXISTING_KEYS_CACHE[CSVFiles.EXPIRED] = get_existing_keys(CSVFiles.EXPIRED)
        _EXISTING_KEYS_CACHE[CSVFiles.ERRORED] = get_existing_keys(CSVFiles.ERRORED)
        _CACHE_INITIALIZED = True

def _get_cached_keys(filename):
    """
    Get cached keys for a filename, initializing cache if needed.
    
    Returns a copy of the cached set to prevent external modifications
    from affecting the cache. This ensures thread-safety and prevents
    accidental cache corruption.
    
    Args:
        filename: CSV file path to get cached keys for
        
    Returns:
        Set of (gamekey, name_lower) tuples (copy of cached set)
    """
    # Ensure cache is initialized (with lock protection)
    if not _CACHE_INITIALIZED:
        _initialize_keys_cache()
    
    # Return copy to prevent external modification
    with _CACHE_LOCK:
        return _EXISTING_KEYS_CACHE.get(filename, set()).copy()

def _update_keys_cache(filename, gamekey, human_name):
    """Update the cache after writing a new key. Thread-safe."""
    with _CACHE_LOCK:
        if filename in _EXISTING_KEYS_CACHE and _EXISTING_KEYS_CACHE[filename] is not None:
            _EXISTING_KEYS_CACHE[filename].add((gamekey, human_name.lower()))

def get_existing_keys(filename):
    """
    Return set of (gamekey, name_lower) tuples from CSV file.
    
    Args:
        filename: Path to CSV file
        
    Returns:
        Set of (gamekey, name_lower) tuples representing existing keys
    """
    if not os.path.exists(filename):
        return set()
    
    keys = set()
    try:
        with open(filename, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 2:
                    gamekey = row[0].strip()
                    name = row[1].strip().lower()
                    if gamekey and name:
                        keys.add((gamekey, name))
    except Exception as e:
        logging.error(f"Error reading {filename} for deduplication: {e}")
    
    return keys


def is_duplicate(gamekey, human_name, existing_keys):
    """
    Check if key already exists in the set of existing keys.
    
    Args:
        gamekey: Game key identifier
        human_name: Human-readable game name
        existing_keys: Set of (gamekey, name_lower) tuples
        
    Returns:
        True if duplicate found, False otherwise
    """
    return (gamekey, human_name.lower()) in existing_keys


def write_key(code: Union[SteamErrorCode, int, str], key: Dict[str, Any]) -> None:
    """
    Write key to appropriate CSV file with proper CSV escaping and duplicate prevention.
    
    Args:
        code: Redemption status code (SteamErrorCode enum, int, or "EXPIRED" string for backward compatibility)
        key: Dictionary containing key data with keys: gamekey, human_name, redeemed_key_val
    
    Example:
        >>> write_key(SteamErrorCode.SUCCESS, {"gamekey": "abc123", "human_name": "Test Game", "redeemed_key_val": "XXXXX-XXXXX-XXXXX"})
        >>> write_key("EXPIRED", {"gamekey": "xyz789", "human_name": "Expired Game"})  # String automatically converted
    """
    # Normalize code to ensure consistent handling
    code = normalize_error_code(code)
    
    gamekey = key.get('gamekey', '')
    human_name = key.get('human_name', '')
    redeemed_key_val = key.get("redeemed_key_val", '')
    
    # Determine filename using mapping (cleaner than if/elif chain)
    filename = CODE_TO_FILE_MAP.get(code, CSVFiles.ERRORED)
    
    # Use csv.writer for proper escaping of special characters
    # CRITICAL: Check for duplicates INSIDE the lock to prevent race conditions
    # Use cached keys for O(1) lookup instead of reading file each time (O(n²) -> O(n))
    with get_csv_writer(code) as f:
        # Check cache first (fast O(1) lookup)
        cached_keys = _get_cached_keys(filename)
        if is_duplicate(gamekey, human_name, cached_keys):
            # Duplicate found - skip writing
            # If successfully redeemed but was in errored.csv, remove it
            if code in SUCCESS_CODES:
                remove_from_errored_csv(gamekey, human_name)
            return
        
        # Double-check by reading file while holding lock (prevents race condition with other processes)
        # This is still O(n) but only happens once per write, and we have the cache for fast checks
        existing_keys = get_existing_keys(filename)
        if is_duplicate(gamekey, human_name, existing_keys):
            # Duplicate found by another process - update cache and skip
            # Use lock to ensure thread-safe cache update
            with _CACHE_LOCK:
                _EXISTING_KEYS_CACHE[filename] = existing_keys
            if code in SUCCESS_CODES:
                remove_from_errored_csv(gamekey, human_name)
            return
        
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([gamekey, human_name, redeemed_key_val])
        f.flush()
        
        # Update cache after successful write
        _update_keys_cache(filename, gamekey, human_name)
    
    # If successfully redeemed, remove from errored.csv
    if code in SUCCESS_CODES:  # Success codes (redeemed, already owned, already activated)
        remove_from_errored_csv(gamekey, human_name)


def prompt_skipped(skipped_games):
    """Allow user to review and filter skipped games."""
    global AUTO_MODE
    user_filtered = []
    with open("skipped.txt", "w", encoding="utf-8-sig") as file:
        for skipped_game in skipped_games.keys():
            file.write(skipped_game + "\n")

    print(
        f"Inside skipped.txt is a list of {len(skipped_games)} games that we think you already own, but aren't "
        f"completely sure "
    )
    if AUTO_MODE:
        print("(auto-mode: skipping all uncertain games)")
        # In auto mode, skip all uncertain games (safer)
        if os.path.exists("skipped.txt"):
            os.remove("skipped.txt")
        return []
    try:
        input(
            "Feel free to REMOVE from that list any games that you would like to try anyways, and when done press "
            "Enter to confirm. "
        )
    except (KeyboardInterrupt, EOFError):
        pass
    if os.path.exists("skipped.txt"):
        with open("skipped.txt", "r", encoding="utf-8-sig") as file:
            user_filtered = [line.strip() for line in file]
        os.remove("skipped.txt")
    # Choose only the games that appear to be missing from user's skipped.txt file
    user_requested = [
        skip_game
        for skip_name, skip_game in skipped_games.items()
        if skip_name not in user_filtered
    ]
    return user_requested


def prompt_yes_no(question, default_yes=True):
    """Prompt user for yes/no answer. Returns True for yes, False for no."""
    global AUTO_MODE
    if AUTO_MODE:
        answer = "y" if default_yes else "n"
        print(f"{question} [{answer}] (auto-mode)")
        return default_yes
    ans = None
    default_char = "Y" if default_yes else "N"
    answers = ["y","n"]
    while ans not in answers:
        prompt = f"{question} [{default_char.lower()}/{answers[1 if default_yes else 0]}] "
        if default_yes:
            prompt = f"{question} [Y/n] "
        else:
            prompt = f"{question} [y/N] "

        ans = input(prompt).strip().lower()
        # Empty input means use default
        if ans == "":
            return default_yes
        if ans not in answers:
            print(f"{ans} is not a valid answer")
            continue
        else:
            return True if ans == "y" else False


def _load_cache(cache_key: str, max_age_hours: int = 24) -> Tuple[Optional[Any], bool]:
    """
    Load cached data if it exists, is not expired, and version matches.
    
    Args:
        cache_key: Cache key identifier
        max_age_hours: Maximum age in hours before cache is considered expired
        
    Returns:
        Tuple of (cached_data, is_valid). Returns (None, False) if cache is invalid/expired.
    """
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if not cache_file.exists():
        return None, False
    
    try:
        with cache_file.open("r", encoding="utf-8") as f:
            cache_data = json.load(f)
        
        # Version check - invalidate cache if version mismatch
        cache_version = cache_data.get("version", 1)
        if cache_version != CACHE_VERSION:
            logging.info(f"Cache version mismatch for {cache_key} (got {cache_version}, expected {CACHE_VERSION}), invalidating")
            return None, False
        
        # Check expiration
        cached_time = datetime.fromisoformat(cache_data.get("cached_at", ""))
        age = datetime.now() - cached_time
        if age > timedelta(hours=max_age_hours):
            return None, False
        
        return cache_data.get("data"), True
    except (json.JSONDecodeError, ValueError, KeyError, OSError) as e:
        logging.debug(f"Cache load error for {cache_key}: {e}")
        return None, False


def _save_cache(cache_key: str, data: Any) -> bool:
    """
    Save data to cache with version tracking and timestamp.
    
    Args:
        cache_key: Cache key identifier
        data: Data to cache (must be JSON-serializable)
        
    Returns:
        True if cache was saved successfully, False otherwise
    """
    cache_file = CACHE_DIR / f"{cache_key}.json"
    try:
        cache_data = {
            "version": CACHE_VERSION,
            "cached_at": datetime.now().isoformat(),
            "data": data
        }
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2)
        return True
    except (OSError, TypeError) as e:
        logging.debug(f"Cache save error for {cache_key}: {e}")
        return False


def _load_steam_api_key(path: str = "steam_api_key.txt") -> str:
    """
    Load Steam API key from file or prompt user.
    
    Note: Currently stores key in plaintext. Consider encrypting for production use.
    
    Args:
        path: Path to the Steam API key file
        
    Returns:
        Steam API key string
    """
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key:
                    return key
        except OSError:
            print(f"Warning: unable to read {path}; will prompt for Steam API key.")

    while True:
        key = input("Enter your Steam Web API key: ").strip()
        if key:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(key)
            except OSError:
                print(f"Warning: failed to save Steam API key to {path}; using it for this run only.")
            return key

        print("Steam API key cannot be empty. Please try again.")


def _fetch_all_apps(steam_session):
    """Fetch complete Steam app list via API. Returns list of app dicts. Uses cache (7 days)."""
    # Try to load from cache first (cache for 7 days - Steam app list changes rarely)
    cached_data, is_valid = _load_cache("steam_app_list", max_age_hours=24*7)
    if is_valid:
        print(f"Using cached Steam app list ({len(cached_data)} apps)")
        return cached_data
    
    api_key = _load_steam_api_key()
    url = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
    params = {
        "key": api_key,
        "max_results": 50000,
        "last_appid": 0,
        "include_dlc": True,
        "include_software": True,
        "include_hardware": True
    }

    print("Fetching Steam app list... (this may take a few moments)")

    apps = []
    while True:
        try:
            resp = steam_session.get(url, params=params, timeout=30)
        except requests.exceptions.Timeout:
            print("Timeout while fetching Steam app list. Retrying...")
            time.sleep(EXTENDED_SLEEP_SECONDS)
            continue
        except requests.exceptions.RequestException as e:
            print(f"Network error while fetching Steam app list: {e}")
            break
        if resp.status_code == 403:
            print(
                "Steam responded with 403 Forbidden while fetching the app list. "
                "Please delete .steamcookies and try again. If the issue persists, wait an hour and retry."
            )
            sys.exit(1)

        try:
            body = resp.json().get("response", {})
        except ValueError:
            print("Error: Steam app list response was not JSON. Stopping fetch.")
            break
        page = body.get("apps", [])
        apps.extend(page)

        if not body.get("have_more_results") or not page:
            break

        params["last_appid"] = body.get("last_appid", params.get("last_appid", 0))
    print(f"Fetched {len(apps)} total apps available on Steam Store.")
    
    # Save to cache
    _save_cache("steam_app_list", apps)
    print("Cached Steam app list for future use.")

    return apps


def _fetch_missing_app_details(steam_session, app_ids):
    """Fetch app details for apps not in main catalog. Returns dict of {appid: name}. Uses cache (7 days)."""
    if not app_ids:
        return {}
    
    # Try to load from cache first
    cache_key = f"missing_app_details_{hash(tuple(sorted(app_ids)))}"
    cached_data, is_valid = _load_cache(cache_key, max_age_hours=24*7)
    if is_valid:
        print(f"Using cached app details for {len(cached_data)} apps")
        return cached_data
    
    # Also check individual app caches
    cached_apps = {}
    uncached_app_ids = []
    for appid in app_ids:
        app_cache, is_valid = _load_cache(f"app_detail_{appid}", max_age_hours=24*7)
        if is_valid and app_cache:
            cached_apps[appid] = app_cache
        else:
            uncached_app_ids.append(appid)
    
    if not uncached_app_ids:
        return cached_apps

    def fetch_app(appid):
        try:
            resp = steam_session.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": appid},
                timeout=10
            ).json()
            app_data = resp.get(str(appid), {})
            if app_data.get("success") and app_data.get("data"):
                name = app_data["data"].get("name")
                if name:
                    return appid, name
        except Exception:
            return None
        return None

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(uncached_app_ids)))) as executor:
        results = list(executor.map(fetch_app, uncached_app_ids))

    resolved = dict(result for result in results if result is not None)
    # Merge with cached apps
    resolved.update(cached_apps)
    
    # Cache individual app details
    for appid, name in resolved.items():
        if appid not in cached_apps:
            _save_cache(f"app_detail_{appid}", name)
    
    unresolved = [appid for appid in app_ids if appid not in resolved]

    if unresolved:
        sample = ", ".join(str(appid) for appid in unresolved[:10])
        more = f" ... (+{len(unresolved) - 10} more)" if len(unresolved) > 10 else ""
        print(
            f"Warning: Unable to fetch details for {len(unresolved)} owned apps (examples: {sample}{more})"
        )
        try:
            with open("missing_app_ids.txt", "w", encoding="utf-8") as f:
                for appid in unresolved:
                    f.write(f"{appid}\n")
        except OSError:
            print("Warning: failed to write missing_app_ids.txt with unresolved app ids.")

    return resolved


def get_owned_apps(steam_session):
    """Get dict of owned Steam apps: {appid: name}. Uses cache (1 hour)."""
    # Try to load from cache first (cache for 1 hour - owned apps change when user buys games)
    cached_data, is_valid = _load_cache("owned_apps", max_age_hours=1)
    if is_valid:
        print(f"Using cached owned apps list ({len(cached_data)} apps)")
        return cached_data
    
    try:
        resp = steam_session.get(STEAM_USERDATA_API, timeout=30)
    except requests.exceptions.Timeout:
        print("Timeout while fetching owned apps from Steam.")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"Network error while fetching owned apps: {e}")
        return {}
    try:
        owned_content = resp.json()
    except ValueError:
        preview = resp.text[:200].replace("\n", " ")
        print(
            f"Error: Steam user data response was not JSON (status {resp.status_code}). "
            f"Body preview: {preview}"
        )
        return {}
    owned_app_ids = owned_content.get("rgOwnedPackages", []) + owned_content.get("rgOwnedApps", [])
    all_app_ids = _fetch_all_apps(steam_session)

    # Index known apps from the catalog
    app_index = {app["appid"]: app["name"] for app in all_app_ids}

    # Fallback: the new catalog endpoint omits store-disabled apps, so look them up directly.
    unindexed_app_ids = [
        appid
        for appid in owned_content.get("rgOwnedApps", [])
        if appid not in app_index
    ]

    if unindexed_app_ids:
        app_index.update(_fetch_missing_app_details(steam_session, unindexed_app_ids))

    owned_app_details = {
        appid: app_index[appid]
        for appid in owned_content.get("rgOwnedApps", [])
        if appid in app_index
    }
    
    # Save to cache
    _save_cache("owned_apps", owned_app_details)
    print(f"Cached owned apps list ({len(owned_app_details)} apps) for future use.")

    return owned_app_details


def _strip_platform_suffixes(name):
    """
    Strip Steam platform suffix from game names (e.g., "(Steam)").
    Returns the name without the Steam suffix.
    
    IMPORTANT: 
    - Only strips "(Steam)" suffix in parentheses at the END of the name
    - This preserves game names that contain "Steam" as part of the actual title
      (e.g., "SteamWorld Dig" remains unchanged, but "SteamWorld Dig (Steam)" becomes "SteamWorld Dig")
    - We only strip "(Steam)" because this script only processes Steam keys.
      Other platform suffixes (Epic Games, GOG, etc.) are not stripped because:
      a) Keys with those suffixes won't have steam_app_id and won't be processed
      b) If they somehow do have steam_app_id, the suffix might be meaningful
    """
    # Only strip "(Steam)" suffix - we only process Steam keys, so other platform suffixes
    # shouldn't appear in our processing pipeline. If they do, we preserve them.
    # Compile regex once at module level for better performance
    return PLATFORM_SUFFIX_PATTERN.sub('', name).strip()


def _extract_version_numbers(name):
    """
    Extract version numbers (both Arabic and Roman numerals) from a game name.
    Returns a tuple of (name_without_version, version_numbers_list).
    """
    # Pattern for Arabic numerals (1, 2, 3, etc.) and Roman numerals (I, II, III, IV, etc.)
    # Match at word boundaries to avoid matching years (e.g., "2024")
    version_pattern = r'\b([IVX]+|\d+)\b'
    
    # Find all potential version numbers
    versions = re.findall(version_pattern, name, re.IGNORECASE)
    
    # Filter out common false positives (years, single digits that are likely not versions)
    # Keep Roman numerals and numbers that are likely versions (2+ digits or Roman)
    filtered_versions = []
    for v in versions:
        v_upper = v.upper()
        # Keep Roman numerals (I, II, III, IV, V, etc.)
        if re.match(r'^[IVX]+$', v_upper):
            filtered_versions.append(v_upper)
        # Keep Arabic numerals that are likely versions (not years, not single digits in common contexts)
        elif v.isdigit():
            num = int(v)
            # Exclude years (1900-2100) and very small numbers that might be part of titles
            if not (1900 <= num <= 2100) and (num >= 2 or len(v) >= 2):
                filtered_versions.append(v)
    
    # Remove version numbers from name for comparison
    name_clean = name
    for version in filtered_versions:
        # Remove version with word boundaries
        name_clean = re.sub(r'\b' + re.escape(version) + r'\b', '', name_clean, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    
    return name_clean, filtered_versions


def match_ownership(owned_app_details, game, filter_live):
    """
    Check if a game matches any owned Steam apps.
    Returns (match_score, appid) tuple.
    
    Special handling:
    - Steam platform suffix: stripped before comparison (e.g., "Balatro (Steam)" matches "Balatro")
    - Version numbers: if games differ only by version number, they are NOT considered matches
      (to avoid false positives like "Warhammer II" vs "Warhammer III")
    """
    threshold = 70
    best_match = (0, None)
    game_name = game['human_name']
    
    # Strip Steam platform suffix from game name (e.g., "(Steam)")
    # Note: We only strip "(Steam)" since we only process Steam keys
    game_name_clean = _strip_platform_suffixes(game_name)
    
    # Do a string search based on product names.
    # Also strip Steam platform suffix from owned app names for fair comparison
    matches = [
        (fuzz.token_set_ratio(_strip_platform_suffixes(appname), game_name_clean), appid)
        for appid, appname in owned_app_details.items()
    ]
    refined_matches = [
        (fuzz.token_sort_ratio(_strip_platform_suffixes(owned_app_details[appid]), game_name_clean), appid)
        for score, appid in matches
        if score > threshold
    ]
    if filter_live and len(refined_matches) > 0:
        cls()
        best_match = max(refined_matches, key=lambda item: item[0])
        if best_match[0] == 100:
            return best_match
        print(f"Steam games you own that might match '{game_name}':")
        for match in refined_matches:
            print(f"     {owned_app_details[match[1]]}: {match[0]}")
        if prompt_yes_no(f"Is \"{game_name}\" in the above list?", default_yes=False):
            return refined_matches[0]
        else:
            return (0, None)
    else:
        # Non-interactive mode: use stricter threshold and version-aware matching
        # game_name_clean already has Steam platform suffix stripped above
        
        # Extract version numbers from the game name (after platform stripping)
        game_name_for_version, game_versions = _extract_version_numbers(game_name_clean)
        
        if len(refined_matches) > 0:
            best_match = max(refined_matches, key=lambda item: item[0])
        elif len(refined_matches) == 1:
            best_match = refined_matches[0]
        
        # Special handling: if games differ only by version number, don't match
        if best_match[1] is not None and game_versions:
            owned_name = owned_app_details[best_match[1]]
            # Strip Steam platform suffix before version extraction
            owned_name_no_platform = _strip_platform_suffixes(owned_name)
            owned_name_clean, owned_versions = _extract_version_numbers(owned_name_no_platform)
            
            # If the base names (without versions) match very closely, but versions differ
            # This is likely a different version of the same game - don't match
            base_name_similarity = fuzz.token_sort_ratio(game_name_for_version, owned_name_clean)
            if base_name_similarity >= 85:  # Base names are very similar
                if game_versions != owned_versions:  # But versions differ
                    # Different version - don't match (unless it's a 100% exact match)
                    if best_match[0] < 100:
                        return (0, None)
        
        # Use 90% threshold for non-interactive mode (was 35% - too low, then 70%)
        # Only mark as owned if we're very confident (>90% match)
        if best_match[0] < 90:
            best_match = (0, None)
    return best_match


def prompt_filter_live():
    """Ask user if they want to interactively filter owned games."""
    global AUTO_MODE
    if AUTO_MODE:
        print("You can either see a list of games we think you already own later in a file, or filter them now. Would you like to see them now? [n] (auto-mode)")
        return "n"
    mode = None
    while mode not in ["y","n"]:
        user_input = input("You can either see a list of games we think you already own later in a file, or filter them now. Would you like to see them now? [y/N] ").strip().lower()
        # Empty input means use default (no)
        if user_input == "":
            return "n"
        if user_input in ["y","n"]:
            return user_input
        else:
            print("Enter y or n")
    return mode


def retry_errored_keys(humble_session, steam_session, order_details):
    """Retry keys that previously errored (especially rate-limited ones)."""
    if order_details is None:
        return  # Can't retry without order details
    errored_file = CSVFiles.ERRORED
    if not os.path.exists(errored_file):
        return
    # Read errored keys with deduplication - prefer valid keys over empty/invalid ones
    # IMPORTANT: Deduplicate by (gamekey, name) to prevent processing the same game multiple times
    errored_dict = {}  # (gamekey, name) -> best entry
    try:
        with open(errored_file, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            # Skip header if present
            first_row = next(reader, None)
            if first_row and first_row[0].lower() != "gamekey":
                # First row is data, not header
                if len(first_row) >= 3:
                    gamekey = first_row[0].strip()
                    human_name = first_row[1].strip()
                    redeemed_key_val = first_row[2].strip()
                    key_id = (gamekey, human_name.lower())
                    # Only keep if we don't have a better (valid) key already
                    if key_id not in errored_dict or (
                        not valid_steam_key(errored_dict[key_id]["redeemed_key_val"]) and 
                        valid_steam_key(redeemed_key_val)
                    ):
                        errored_dict[key_id] = {
                            "gamekey": gamekey,
                            'human_name': human_name,
                            "redeemed_key_val": redeemed_key_val
                        }
            # Read remaining rows using the same deduplication logic
            for row in reader:
                if len(row) >= 3:
                    gamekey = row[0].strip()
                    human_name = row[1].strip()
                    redeemed_key_val = row[2].strip()
                    key_id = (gamekey, human_name.lower())
                    # Only keep if we don't have a better (valid) key already
                    if key_id not in errored_dict or (
                        not valid_steam_key(errored_dict[key_id]["redeemed_key_val"]) and 
                        valid_steam_key(redeemed_key_val)
                    ):
                        errored_dict[key_id] = {
                            "gamekey": gamekey,
                            'human_name': human_name,
                            "redeemed_key_val": redeemed_key_val
                        }
    except Exception as e:
        print(f"Error reading {errored_file}: {e}")
        return
    
    # Convert to list and filter out invalid keys BEFORE matching
    errored_keys = []
    for entry in errored_dict.values():
        key_val = entry["redeemed_key_val"]
        # Skip empty, expired, or invalid keys - don't even try to match them
        if not key_val or key_val == "" or key_val == "EXPIRED":
            continue
        if not valid_steam_key(key_val):
            continue
        errored_keys.append(entry)
    
    if not errored_keys:
        print(f"\n{'='*60}")
        print(f"No valid keys found in errored.csv to retry (all are empty/invalid/expired)")
        print(f"{'='*60}\n")
        return
    
    print(f"\n{'='*60}")
    print(f"Retrying {len(errored_keys)} previously errored keys (after deduplication and filtering)...")
    print(f"{'='*60}\n")
    
    # Match errored keys back to order_details
    # IMPORTANT: Match by both gamekey AND name to avoid issues with shared gamekeys (Choice months)
    all_steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
    keys_to_retry = []
    seen_retry_keys = set()  # Track (gamekey, name) to avoid duplicates
    
    for errored in errored_keys:
        errored_gamekey = errored["gamekey"]
        errored_name = errored["human_name"].strip().lower()
        errored_key_val = errored["redeemed_key_val"]
        
        # Skip if already processed (deduplication by gamekey + name)
        retry_id = (errored_gamekey, errored_name)
        if retry_id in seen_retry_keys:
            continue  # Already processed this exact game
        seen_retry_keys.add(retry_id)
        
        # Try to find matching key in order_details - prefer exact name match
        matched = False
        for key in all_steam_keys:
            key_gamekey = key.get("gamekey", "")
            key_name = key.get("human_name", "").strip().lower()
            
            # Match by both gamekey AND name for accuracy
            if key_gamekey == errored_gamekey and key_name == errored_name:
                # Update with the redeemed_key_val from errored.csv
                key["redeemed_key_val"] = errored_key_val
                keys_to_retry.append(key)
                matched = True
                break
        
        # Fallback: if no exact match, try matching by gamekey only (for backward compatibility)
        # But only if we haven't already added this gamekey
        if not matched:
            for key in all_steam_keys:
                if key.get("gamekey") == errored_gamekey:
                    # Check if we've already added this gamekey
                    if not any(k.get("gamekey") == errored_gamekey for k in keys_to_retry):
                        key["redeemed_key_val"] = errored_key_val
                        keys_to_retry.append(key)
                        break
    
    if not keys_to_retry:
        print("No matching keys found in order details to retry.")
        return
    print(f"Found {len(keys_to_retry)} keys to retry out of {len(errored_keys)} errored (after deduplication).\n")
    # Retry the keys
    total_retry = len(keys_to_retry)
    for idx, key in enumerate(keys_to_retry, 1):
        remaining = total_retry - idx + 1
        print(f"[RETRY {idx}/{total_retry}] {key['human_name']} ({remaining} remaining)")
        if not valid_steam_key(key["redeemed_key_val"]):
            print(f"  -> Invalid key format, skipping")
            continue
        code = _redeem_steam(steam_session, key["redeemed_key_val"])
        if code == SteamErrorCode.RATE_LIMITED:
            # Use reusable rate limit handler
            code = wait_for_rate_limit_clear(
                steam_session,
                key["redeemed_key_val"],
                remaining,
                keepalive=None,  # No keepalive in retry context
                retry_interval=RATE_LIMIT_RETRY_INTERVAL_SECONDS,
                check_interval=RATE_LIMIT_CHECK_INTERVAL_SECONDS
            )
        write_key(code, key)
    print(f"\n{'='*60}")
    print(f"Completed retry pass: {total_retry} keys processed")
    print(f"{'='*60}\n")



# Add a session keep-alive mechanism
class SessionKeepAlive:
    """Periodically performs lightweight operations to keep the session alive."""
    def __init__(self, driver, interval=300):
        self.driver = driver
        self.interval = interval
        self.last_keepalive = time.time()
        self.enabled = True
    def check(self):
        """Check if keep-alive is needed and perform it."""
        if not self.enabled:
            return
        current_time = time.time()
        if current_time - self.last_keepalive >= self.interval:
            try:
                if validate_session(self.driver):
                    _ = self.driver.title  # Lightweight operation
                    self.last_keepalive = current_time
                else:
                    print(f"[DEBUG] Session validation failed during keep-alive")
                    self.enabled = False
            except Exception:
                self.enabled = False
    def disable(self):
        """Disable keep-alive."""
        self.enabled = False


def _reinitialize_browser_session(humble_session, remaining_keys, current_idx, total_keys):
    """
    Attempt to reinitialize the browser session when it has died.
    Returns (new_driver, keepalive) on success, or None on failure.
    On failure, marks remaining keys as errored and exits.
    """
    print(f"\n{'='*60}")
    print("CRITICAL: Browser session has died and cannot be recovered")
    print(f"{'='*60}")
    print(f"\nThe browser session became invalid after multiple consecutive failures.")
    print("Attempting to reinitialize the browser...")
    
    try:
        # Try to quit the old driver gracefully
        try:
            humble_session.quit()
        except:
            pass
        
        # Create new browser and login
        print("Creating new browser session...", end=" ", flush=True)
        new_driver = get_browser_driver(headless=AUTO_MODE)
        print("OK")
        
        print("Re-authenticating with Humble...", end=" ", flush=True)
        new_driver, login_success = humble_login(new_driver, is_headless=AUTO_MODE)
        
        if not login_success:
            raise Exception("Login failed")
        
        # Verify the new session
        is_valid = verify_logins_session(new_driver)[0]
        if not is_valid:
            raise Exception("Session verification failed")
        
        print("OK")
        print(f"\n✓ Browser session successfully reinitialized!")
        print(f"Continuing with {remaining_keys} keys remaining...\n")
        
        # Create new keep-alive
        new_keepalive = SessionKeepAlive(new_driver, interval=300)
        
        return new_driver, new_keepalive
        
    except Exception as e:
        print("FAILED")
        print(f"\nError reinitializing browser: {e}")
        print(f"\n{'='*60}")
        print("CANNOT CONTINUE - Browser session recovery failed")
        print(f"{'='*60}")
        print(f"\nProcessed {current_idx - 1} of {total_keys} keys before session failure.")
        print(f"Remaining keys have been marked as errored and will be retried on next run.")
        print(f"\nPossible causes:")
        print("  1. Browser crashed or was killed")
        print("  2. Network connectivity issues")
        print("  3. Humble Bundle website is blocking automated access")
        print("  4. Cookies expired and re-login failed")
        
        if AUTO_MODE:
            print(f"\nIn AUTO_MODE, manual intervention is required:")
            print("  1. Run: python3 humblesteamkeysredeemer.py")
            print("  2. Complete the login process")
            print("  3. Restart the daemon")
        else:
            print(f"\nPlease check your connection and try running the script again.")
        
        # Mark remaining keys as errored (we need to get them from the caller)
        # This will be handled by the caller
        
        # Clean up
        try:
            humble_session.quit()
        except:
            pass
        
        return None, None


def redeem_steam_keys(humble_session, humble_keys, order_details=None):
    """Main function to redeem Steam keys. Returns Steam session for retries."""
    session = steam_login()

    print("Successfully signed in on Steam.")
    print("Getting your owned content to avoid attempting to register keys already owned...")

    # Query owned App IDs according to Steam
    owned_app_details = get_owned_apps(session)

    # Ask user if they want to skip friend/co-op keys
    skip_friend_keys = prompt_yes_no(
        "Would you like to automatically skip friend/co-op keys? "
        "(These will be saved to friend_keys.csv for gifting)",
        default_yes=True
    )

    skipped_games = {}
    unownedgames = []
    friend_keys_skipped = []  # Track skipped friend keys (high confidence)
    uncertain_friend_keys = []  # Track uncertain friend keys (low confidence)

    # Some Steam keys come back with no Steam AppID from Humble
    # So we do our best to look up from AppIDs (no packages, because can't find an API for it)

    filter_live = prompt_filter_live() == "y"

    # Process ALL keys in a single unified loop
    for key in humble_keys:
        # Check if it's a friend/co-op key FIRST (works on both revealed and unrevealed)
        if skip_friend_keys:
            is_friend, reason, confidence = is_friend_or_coop_key(key)
            if is_friend:
                # High confidence (>= 0.8) - automatically skip
                if confidence >= FRIEND_KEY_HIGH_CONFIDENCE_THRESHOLD:
                    friend_keys_skipped.append((key, reason, confidence))
                    continue  # Skip this key entirely
                else:
                    # Low confidence - mark for review
                    uncertain_friend_keys.append((key, reason, confidence))
                    # Don't skip yet - will review later
        
        # Check if revealed and owned
        is_revealed = "redeemed_key_val" in key
        steam_app_id = key.get("steam_app_id")
        
        if is_revealed and steam_app_id in owned_app_details.keys():
            # Definitely owned (exact AppID match)
            skipped_games[key['human_name'].strip()] = key
        elif is_revealed and steam_app_id not in owned_app_details.keys():
            # Revealed but not in owned list - do fuzzy matching
            best_match = match_ownership(owned_app_details, key, filter_live)
            if best_match[1] is not None and best_match[1] in owned_app_details.keys():
                skipped_games[key['human_name'].strip()] = key
            else:
                unownedgames.append(key)
        else:
            # Unrevealed - can't check ownership yet, add to process list
            unownedgames.append(key)
    
    # Review uncertain friend keys
    if uncertain_friend_keys:
        print(f"\nFound {len(uncertain_friend_keys)} keys that might be friend/co-op keys...")
        confirmed = review_uncertain_friend_keys(uncertain_friend_keys)
        
        # Move confirmed friend keys from unownedgames to friend_keys_skipped
        for key in confirmed:
            if key in unownedgames:
                unownedgames.remove(key)
            # Find the full entry with reason/confidence
            for uncertain_key, reason, confidence in uncertain_friend_keys:
                if uncertain_key == key:
                    friend_keys_skipped.append((key, reason, confidence))
                    break
    
    # Count revealed vs unrevealed
    revealed_count = sum(1 for key in unownedgames if "redeemed_key_val" in key)
    unrevealed_count = len(unownedgames) - revealed_count
    
    print(
        f"\nFiltered out game keys that you already own on Steam; {len(unownedgames)} keys unowned "
        f"({revealed_count} revealed, {unrevealed_count} unrevealed)."
    )
    
    # Report on friend keys with examples
    if friend_keys_skipped:
        print(f"\nSkipped {len(friend_keys_skipped)} friend/co-op keys (saved to friend_keys.csv):")
        # Show first 3 examples
        for i, (key, reason, confidence) in enumerate(friend_keys_skipped[:3]):
            conf_emoji = "🔒" if confidence >= FRIEND_KEY_HIGH_CONFIDENCE_THRESHOLD else "❓"
            print(f"  {conf_emoji} {key['human_name']} ({reason})")
        if len(friend_keys_skipped) > 3:
            print(f"  ... and {len(friend_keys_skipped) - 3} more (see friend_keys.csv)")
        
        # Save friend keys for later gifting
        for key, reason, confidence in friend_keys_skipped:
            save_friend_key(key, reason, confidence)

    if len(skipped_games):
        # Skipped games uncertain to be owned by user. Let user choose
        unownedgames = unownedgames + prompt_skipped(skipped_games)
        print("{} keys will be attempted.".format(len(unownedgames)))
        # Preserve original order
        unownedgames = sorted(unownedgames,key=lambda g: humble_keys.index(g))
    total_to_redeem = len(unownedgames)
    print(f"\n{'='*60}")
    print(f"Starting redemption: {total_to_redeem} keys to process")
    print(f"{'='*60}\n")
    # Initialize keep-alive for Humble session
    keepalive = SessionKeepAlive(humble_session, interval=300)  # 5 minutes
    redeemed = []
    
    # Track rate limiting statistics
    rate_limit_count = 0
    rate_limit_total_wait_time = 0
    
    # Track consecutive session failures for recovery
    consecutive_session_failures = 0
    MAX_CONSECUTIVE_SESSION_FAILURES = 3  # After 3 failures, try full reinitialization
    MAX_TOTAL_SESSION_RECOVERIES = 10  # Global limit to prevent infinite recovery loops
    total_recovery_attempts = 0  # Track total recovery attempts across all keys

    for idx, key in enumerate(unownedgames, 1):
        # Check keep-alive periodically
        keepalive.check()
        remaining = total_to_redeem - idx + 1
        print(f"[{idx}/{total_to_redeem}] {key['human_name']} ({remaining} remaining)")

        if key['human_name'] in redeemed or (key.get("steam_app_id") != None and key["steam_app_id"] in redeemed):
            # We've bumped into a repeat of the same game!
            write_key(9,key)
            continue
        else:
            if key.get("steam_app_id") != None:
                redeemed.append(key["steam_app_id"])
            redeemed.append(key['human_name'])

        if "redeemed_key_val" not in key:
            # Validate session before redemption
            if not validate_session(humble_session):
                consecutive_session_failures += 1
                print(f"  -> Session invalid, attempting recovery... (failure {consecutive_session_failures}/{MAX_CONSECUTIVE_SESSION_FAILURES})")
                
                # Try simple page refresh first
                if refresh_page_if_needed(humble_session, "https://www.humblebundle.com/home/library"):
                    # Success - reset failure counter
                    consecutive_session_failures = 0
                else:
                    # Simple refresh failed - try full reinitialization if we've had multiple failures
                    if consecutive_session_failures >= MAX_CONSECUTIVE_SESSION_FAILURES:
                        new_driver, new_keepalive = _reinitialize_browser_session(
                            humble_session, remaining, idx, total_to_redeem
                        )
                        
                        if new_driver is None:
                            # Recovery failed - mark remaining keys and exit
                            for remaining_key in unownedgames[idx - 1:]:
                                write_key(1, remaining_key)
                            keepalive.disable()
                            sys.exit(2)  # Exit code 2 = session recovery failed
                        
                        # Update references
                        humble_session = new_driver
                        keepalive = new_keepalive
                        consecutive_session_failures = 0  # Reset counter
                    else:
                        # Not enough failures yet - mark this key as errored and continue
                        print(f"  -> Failed to recover session, marking as errored")
                        write_key(1, key)
                        continue
            
            redeemed_key = redeem_humble_key(humble_session, key)
            key["redeemed_key_val"] = redeemed_key
            # Worth noting this will only persist for this loop -- does not get saved to unownedgames' obj
            
            # Check if reveal failed - provide better error messages
            if not redeemed_key:
                # Check if it's a session issue
                if not validate_session(humble_session):
                    # Session died during redemption - increment failure counter
                    consecutive_session_failures += 1
                    if consecutive_session_failures >= MAX_CONSECUTIVE_SESSION_FAILURES:
                        # Check global recovery limit to prevent infinite loops
                        total_recovery_attempts += 1
                        if total_recovery_attempts > MAX_TOTAL_SESSION_RECOVERIES:
                            print(f"\n⚠️  Maximum session recovery attempts ({MAX_TOTAL_SESSION_RECOVERIES}) exceeded.")
                            print("   Session appears to be permanently invalid. Exiting to prevent infinite loop.")
                            for remaining_key in unownedgames[idx - 1:]:
                                write_key(1, remaining_key)
                            keepalive.disable()
                            sys.exit(2)  # Exit code 2 = session recovery failed
                        
                        new_driver, new_keepalive = _reinitialize_browser_session(
                            humble_session, remaining, idx, total_to_redeem
                        )
                        
                        if new_driver is None:
                            # Recovery failed - mark remaining keys and exit
                            for remaining_key in unownedgames[idx - 1:]:
                                write_key(1, remaining_key)
                            keepalive.disable()
                            sys.exit(2)
                        
                        # Update references
                        humble_session = new_driver
                        keepalive = new_keepalive
                        consecutive_session_failures = 0
                    else:
                        # Mark as errored and continue
                        print(f"  -> Session died during redemption, marking as errored")
                        write_key(1, key)
                        continue
                else:
                    # Reveal failed for non-session reasons - check if it's a Choice game
                    # For Humble Choice games, they must be SELECTED before revealing
                    is_choice_game = False
                    if order_details:
                        for order in order_details:
                            if order.get("gamekey") == key.get("gamekey"):
                                if "choice_url" in order.get("product", {}):
                                    is_choice_game = True
                                    break
                    
                    if is_choice_game:
                        print(f"  -> ⚠️  Reveal failed - game may not be SELECTED in Humble Choice")
                        print(f"     → Go to Humble Choice and ensure this game is selected")
                        print(f"     → Then run the script again")
                    else:
                        print(f"  -> ⚠️  Reveal failed - check error message above")
                    
                    # Mark as errored so it can be retried later
                    write_key(1, key)
                    continue
            
            # Reset failure counter on successful redemption
            if redeemed_key and redeemed_key != "EXPIRED" and valid_steam_key(redeemed_key):
                consecutive_session_failures = 0

        # Handle expired keys - skip without retry
        if key["redeemed_key_val"] == "EXPIRED":
            print(f"  -> Key expired, skipping")
            write_key("EXPIRED", key)
            continue

        if not valid_steam_key(key["redeemed_key_val"]):
            # Most likely humble gift link or reveal failed
            if not key["redeemed_key_val"]:
                print(f"  -> ⚠️  Key reveal returned empty - may need to be selected in Humble Choice")
            else:
                print(f"  -> Invalid key format (likely gift link or reveal error)")
            write_key(1, key)
            continue

        code = _redeem_steam(session, key["redeemed_key_val"])
        rate_limited_this_key = False
        if code == SteamErrorCode.RATE_LIMITED:
            """NOTE
            Steam seems to limit to about 50 keys/hr -- even if all 50 keys are legitimate *sigh*
            Even worse: 10 *failed* keys/hr
            Duplication counts towards Steam's _failure rate limit_,
            hence why we've worked so hard above to figure out what we already own
            """
            rate_limited_this_key = True
            rate_limit_count += 1
            # Track initial wait time for statistics
            wait_start_time = time.time()
            
            # Use reusable rate limit handler
            code = wait_for_rate_limit_clear(
                session,
                key["redeemed_key_val"],
                remaining,
                keepalive=keepalive,
                retry_interval=RATE_LIMIT_RETRY_INTERVAL_SECONDS,
                check_interval=RATE_LIMIT_CHECK_INTERVAL_SECONDS
            )
            
            # Update statistics
            if code != 53:
                wait_duration = int(time.time() - wait_start_time)
                rate_limit_total_wait_time += wait_duration
                total_wait_minutes = wait_duration // 60
                if total_wait_minutes > 0:
                    print(f"\n✓ Rate limit cleared after {total_wait_minutes}m! Continuing with {remaining} keys remaining...\n")

        write_key(code, key)
    keepalive.disable()
    print(f"\n{'='*60}")
    print(f"Completed initial pass: {total_to_redeem} keys processed")
    if rate_limit_count > 0:
        total_wait_hours = rate_limit_total_wait_time // 3600
        total_wait_minutes = (rate_limit_total_wait_time % 3600) // 60
        print(f"Rate limiting encountered: {rate_limit_count} key(s) hit rate limit")
        print(f"Total wait time: {total_wait_hours}h {total_wait_minutes}m")
    # Report friend keys if they were skipped
    if friend_keys_skipped:
        print(f"Friend/co-op keys saved: {len(friend_keys_skipped)} (see friend_keys.csv)")
    print(f"{'='*60}\n")
    
    # After successful redemption, check if any Choice months are now complete
    if order_details:
        completed_choice_months = load_completed_choice_months()
        newly_completed = []
        for month in order_details:
            if "choice_url" in month.get("product", {}):
                month_gamekey = month.get('gamekey')
                if month_gamekey and month_gamekey not in completed_choice_months:
                    if is_choice_month_complete(month_gamekey, order_details):
                        mark_choice_month_complete(month_gamekey)
                        month_name = month.get("product", {}).get("human_name", "Unknown")
                        newly_completed.append(month_name)
                        logging.info(f"Marked Choice month as complete: {month_name} (gamekey: {month_gamekey})")
        
        if newly_completed:
            print(f"\n✓ Marked {len(newly_completed)} Choice month(s) as complete (will skip in future runs):")
            for name in newly_completed:
                print(f"  • {name}")
    
    return session


def export_mode(humble_session,order_details):
    """Export mode - export keys to CSV."""
    cls()

    export_key_headers = [
        'human_name',
        'redeemed_key_val',
        'is_gift',
        'key_type_human_name',
        'is_expired',
        'steam_ownership',
        'humble_steam_app_id',
        'humble_expired_at'
    ]

    steam_session = None
    reveal_unrevealed = False
    confirm_reveal = False

    owned_app_details = None

    keys = []
    print("Please configure your export:")
    export_steam_only = prompt_yes_no("Export only Steam keys?", default_yes=False)
    export_revealed = prompt_yes_no("Export revealed keys?", default_yes=True)
    export_unrevealed = prompt_yes_no("Export unrevealed keys?", default_yes=True)
    if(not export_revealed and not export_unrevealed):
        print("That leaves 0 keys...")
        sys.exit(1)
    if(export_unrevealed):
        reveal_unrevealed = prompt_yes_no("Reveal all unrevealed keys? (This will remove your ability to claim gift links on these)", default_yes=False)
        if(reveal_unrevealed):
            extra = "Steam " if export_steam_only else ""
            confirm_reveal = prompt_yes_no(f"Please CONFIRM that you would like ALL {extra}keys on Humble to be revealed, this can't be undone.", default_yes=False)
    steam_config = prompt_yes_no("Would you like to sign into Steam to detect ownership on the export data?", default_yes=True)
    if(steam_config):
        steam_session = steam_login()
        if(verify_logins_session(steam_session)[1]):
            owned_app_details = get_owned_apps(steam_session)
    desired_keys = "steam_app_id" if export_steam_only else "key_type_human_name"
    keylist = list(find_dict_keys(order_details,desired_keys,True))

    for idx,tpk in enumerate(keylist):
        revealed = "redeemed_key_val" in tpk
        export = (export_revealed and revealed) or (export_unrevealed and not revealed)

        if(export):
            if(export_unrevealed and confirm_reveal and not revealed):
                # Redeem key if user requests all keys to be revealed
                tpk["redeemed_key_val"] = redeem_humble_key(humble_session,tpk)
            if(owned_app_details != None and "steam_app_id" in tpk):
                # User requested Steam Ownership info
                owned = tpk.get("steam_app_id") in owned_app_details.keys()
                if(not owned):
                    # Do a search to see if user owns it
                    best_match = match_ownership(owned_app_details,tpk,False)
                    owned = best_match[1] is not None and best_match[1] in owned_app_details.keys()
                tpk["steam_ownership"] = owned

            # Surface IDs and expiry information for auditing mismatches
            tpk["humble_steam_app_id"] = tpk.get("steam_app_id")
            tpk["humble_expired_at"] = tpk.get("expiry_date")
            keys.append(tpk)
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"humble_export_{ts}.csv"
    with open(filename, 'w', encoding="utf-8-sig") as f:
        f.write(','.join(export_key_headers)+"\n")
        for key in keys:
            row = []
            for col in export_key_headers:
                if col in key:
                    row.append("\"" + str(key[col]).replace('"', '""') + "\"")  # Escape quotes
                else:
                    row.append("")
            f.write(','.join(row)+"\n")
    print(f"Exported to {filename}")


def choose_games(humble_session,choice_month_name,identifier,chosen):
    """Choose games from Humble Choice month."""
    for choice in chosen:
        display_name = choice["display_item_machine_name"]
        if "tpkds" not in choice:
            webbrowser.open(f"{HUMBLE_SUB_PAGE}{choice_month_name}/{display_name}")
        else:
            payload = {
                "gamekey":choice['tpkds'][0]['gamekey'],    
                "parent_identifier":identifier,
                "chosen_identifiers[]":display_name,
                "is_multikey_and_from_choice_modal":"false"
            }
            status,res = perform_post(humble_session,HUMBLE_CHOOSE_CONTENT,payload)
            if not ("success" in res and res["success"]):
                print("Error choosing " + choice["title"])
                print(res)
            else:
                print("Chose game " + choice["title"])


def humble_chooser_mode(humble_session,order_details):
    """Humble Choice chooser mode - select games from Humble Choice months."""
    try_redeem_keys = []
    months = get_choices(humble_session,order_details)
    count = 0
    first = True
    redeem_keys = False
    for month in months:
        redeem_all = None
        if(first):
            redeem_keys = prompt_yes_no("Would you like to auto-redeem these keys after? (Will require Steam login)", default_yes=False)
            first = False
        ready = False
        while not ready:
            cls()
            if month["choice_data"].get("usesChoices", True):
                remaining = month.get("choices_remaining", 0)
                print()
                print(month.get("product", {}).get('human_name', 'Unknown Month'))
                print(f"Choices remaining: {remaining}")
            else:
                remaining = len(month.get("available_choices", []))
            print("Available Games:\n")
            choices = month.get("available_choices", [])
            for idx,choice in enumerate(choices):
                title = choice.get("title", "Unknown")
                rating_text = ""
                if "user_rating" in choice and "review_text" in choice["user_rating"] and "steam_percent|decimal" in choice["user_rating"]:
                    rating = choice["user_rating"]["review_text"].replace('_',' ')
                    percentage = str(int(choice["user_rating"]["steam_percent|decimal"]*100)) + "%"
                    rating_text = f" - {rating}({percentage})"
                exception = ""
                if "tpkds" not in choice:
                    # These are weird cases that should be handled by Humble directly.
                    exception = " (Must be redeemed through Humble directly)"
                print(f"{idx+1}. {title}{rating_text}{exception}")
            if(redeem_all == None and remaining == len(choices)):
                redeem_all = prompt_yes_no("Would you like to redeem all?", default_yes=False)
            else:
                redeem_all = False
            if(redeem_all):
                user_input = [str(i+1) for i in range(0,len(choices))]
            else:
                if(redeem_keys):
                    auto_redeem_note = "(We'll auto-redeem any keys activated via the webpage if you continue after!)"
                else:
                    auto_redeem_note = ""
                print("\nOPTIONS:")
                print("To choose games, list the indexes separated by commas (e.g. '1' or '1,2,3')")
                print(f"Or type just 'link' to go to the webpage for this month {auto_redeem_note}")
                print("Or just press Enter to move on.")

                try:
                    user_input = [uinput.strip() for uinput in input().split(',') if uinput.strip() != ""]
                except (KeyboardInterrupt, EOFError):
                    user_input = []

            if(len(user_input) == 0):
                ready = True
            elif(user_input[0].lower() == 'link'):
                webbrowser.open(HUMBLE_SUB_PAGE + month.get("product", {}).get("choice_url", ""))
                if redeem_keys:
                    # May have redeemed keys on the webpage.
                    try_redeem_keys.append(month.get("gamekey", ""))
                ready = True
            else:
                invalid_option = lambda option: (
                    not option.isnumeric()
                    or option == "0" 
                    or int(option) > len(choices)
                )
                invalid = [option for option in user_input if invalid_option(option)]

                if(len(invalid) > 0):
                    print("Error interpreting options: " + ','.join(invalid))
                    time.sleep(DEFAULT_SLEEP_SECONDS)
                else:
                    user_input = set(int(opt) for opt in user_input) # Uniques
                    chosen = [choice for idx,choice in enumerate(choices) if idx+1 in user_input]
                    # This weird enumeration is to keep it in original display order

                    if len(chosen) > remaining:
                        print(f"Too many games chosen, you have only {remaining} choices left")
                        time.sleep(DEFAULT_SLEEP_SECONDS)
                    else:
                        print("\nGames selected:")
                        for choice in chosen:
                            print(choice.get("title", "Unknown"))
                        confirmed = prompt_yes_no("Please type 'y' to confirm your selection", default_yes=False)
                        if confirmed:
                            choice_month_name = month.get("product", {}).get("choice_url", "")
                            identifier = month.get("parent_identifier", "")
                            choose_games(humble_session,choice_month_name,identifier,chosen)
                            if redeem_keys:
                                try_redeem_keys.append(month.get("gamekey", ""))
                            ready = True
    if(first):
        print("No Humble Choices need choosing! Look at you all up-to-date!")
    else:
        print("No more unchosen Humble Choices")
        if(redeem_keys and len(try_redeem_keys) > 0):
            print("Redeeming keys now!")
            try:
                # Pass list as proper argument instead of string replacement (prevents injection)
                updated_monthlies = humble_session.execute_async_script(getHumbleOrders, try_redeem_keys or [])
                if isinstance(updated_monthlies, dict) and 'error' in updated_monthlies:
                    print(f"Error fetching updated monthly data: {updated_monthlies.get('message', 'Unknown error')}")
                else:
                    chosen_keys = list(find_dict_keys(updated_monthlies,"steam_app_id",True))
                    steam_session = redeem_steam_keys(humble_session, chosen_keys, updated_monthlies)
                    retry_errored_keys(humble_session, steam_session, updated_monthlies)
            except Exception as e:
                print(f"Error during key redemption: {e}")


def cls() -> None:
    """Clear screen (unless in auto mode to preserve logs)."""
    # Don't clear screen in auto mode - we want to preserve the log
    if not AUTO_MODE:
        os.system('cls' if os.name=='nt' else 'clear')
    print_main_header()


def print_main_header() -> None:
    """Print script header."""
    if not AUTO_MODE:
        print("-=frimodig's Humble Bundle Helper!=- (Based on original script by FailSpy)")
    print("--------------------------------------")


if __name__=="__main__":
    driver = None
    try:
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Humble Bundle Steam Key Redeemer')
        parser.add_argument('--auto', action='store_true', 
                            help='Auto mode: automatically answer prompts (requires existing login cookies)')
        args = parser.parse_args()
        if args.auto:
            AUTO_MODE = True
            print("="*50)
            print("RUNNING IN AUTO MODE")
            print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("="*50)
        
        # Create sample friend_key_exclusions.txt if it doesn't exist
        create_sample_friend_exclusions()
            
            # Always start headless - only switch to visible if manual login is needed
        print("Starting browser...", end=" ", flush=True)
        driver = get_browser_driver(headless=True)
        print("OK")
        print("Logging in to Humble...", end=" ", flush=True)
        driver, _ = humble_login(driver, is_headless=True)
        print("OK")
        # Verify session is still valid before fetching order details
        print("Verifying session...", end=" ", flush=True)
        try:
            is_valid = verify_logins_session(driver)[0]
            if not is_valid:
                print("FAILED")
                print("\nError: Humble session has expired or is invalid.")
                if AUTO_MODE:
                    print("The login cookies are stale. Please run the script manually to re-login:")
                    print("  python3 humblesteamkeysredeemer.py")
                    print("Then restart the daemon.")
                    driver.quit()
                    sys.exit(2)  # Exit code 2 = stale cookies
                else:
                    print("Please log in again.")
                    driver.quit()
                    sys.exit(1)
            print("OK")
        except Exception as e:
            print("FAILED")
            print(f"\nError verifying session: {e}")
            driver.quit()
            sys.exit(1)

        # Navigate to Humble Bundle page first to ensure we're in the right context for API calls
        print("Loading Humble Bundle page...", end=" ", flush=True)
        try:
            driver.get("https://www.humblebundle.com/home/library")
            time.sleep(DEFAULT_SLEEP_SECONDS)  # Let page load
            
            # Check if page loaded properly
            try:
                page_title = driver.title
                print(f"OK (page title: {page_title[:30]}...)")
                
                # Check for Cloudflare challenge
                page_source_preview = driver.page_source[:1000].lower()
                if "challenge" in page_title.lower() or "cloudflare" in page_source_preview:
                    print("WARNING: Possible Cloudflare challenge detected!")
                    print("The page may be blocking automated access.")
            except:
                print("OK")
        except Exception as e:
            print("FAILED")
            print(f"\nError loading Humble Bundle page: {e}")
            driver.quit()
            sys.exit(1)
        # Try to load order details from cache first (cache for 1 hour)
        order_details = None
        cached_order_details, is_valid = _load_cache("humble_order_details", max_age_hours=1)
        if is_valid:
            print("Using cached order details")
            order_details = cached_order_details
        else:
            print("Fetching order details...", end=" ", flush=True)
            try:
                # Create interrupt event for Ctrl+C handling
                interrupt_event = threading.Event()
                # Store driver PID for force-kill if needed
                driver_pid = None
                try:
                    driver_pid = driver.service.process.pid if hasattr(driver, 'service') and hasattr(driver.service, 'process') else None
                except:
                    pass
                
                # Update signal handler to use this event
                process_quit(driver, interrupt_event)
                
                result = [None]
                exception = [None]
                thread_started = threading.Event()
                
                def execute_script():
                    try:
                        thread_started.set()  # Signal that thread has started
                        logging.debug("Thread started, executing async script")
                        # Pass empty list as proper argument instead of string replacement
                        result[0] = driver.execute_async_script(getHumbleOrders, [])
                        logging.debug("Script execution completed")
                    except KeyboardInterrupt:
                        interrupt_event.set()
                        exception[0] = KeyboardInterrupt("Interrupted by user")
                    except Exception as e:
                        print(f"[DEBUG] Exception in script thread: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                        exception[0] = e
                
                script_thread = threading.Thread(target=execute_script, name="HumbleOrderFetcher")
                script_thread.daemon = True
                script_thread.start()
                
                # Wait for thread to actually start
                thread_started.wait(timeout=5)
                if not thread_started.is_set():
                    print(" FAILED")
                    print("\nError: Thread failed to start")
                    driver.quit()
                    sys.exit(1)
                
                # Wait with progress indicator and interruptible joins
                timeout_seconds = SCRIPT_TIMEOUT_SECONDS + 5  # Wait up to {timeout_seconds} seconds total
                waited = 0
                check_interval = 1  # Check every 1 second
                last_dot = 0
                
                # Use a more aggressive approach - check interrupt event frequently
                # Also use shorter check interval for better Ctrl+C responsiveness
                check_interval = 0.5  # Check every 0.5 seconds
                
                while script_thread.is_alive() and waited < timeout_seconds:
                    # Check interrupt event FIRST before joining
                    if interrupt_event.is_set():
                        print("\n[DEBUG] Interrupt detected, breaking wait loop", file=sys.stderr, flush=True)
                        break
                        
                    script_thread.join(timeout=check_interval)
                    waited += check_interval
                    
                    # Check interrupt again after join
                    if interrupt_event.is_set():
                        print("\n[DEBUG] Interrupt detected after join", file=sys.stderr, flush=True)
                        break
                    
                    # Show progress dots every 5 seconds
                    if waited - last_dot >= 5 and script_thread.is_alive():
                        print(".", end="", flush=True)
                        last_dot = waited
                        print(f"[DEBUG] Still waiting... ({waited}s elapsed)", file=sys.stderr, flush=True)
                
                # Check results
                if interrupt_event.is_set() or isinstance(exception[0], KeyboardInterrupt):
                    print("\n\nInterrupted by user (Ctrl+C). Exiting...")
                    # Force kill browser process if driver.quit() doesn't work
                    try:
                        driver.quit()
                    except:
                        pass
                    # If driver PID is available, try to kill it
                    if driver_pid:
                        try:
                            os.kill(driver_pid, signal.SIGTERM)
                            time.sleep(SHORT_SLEEP_SECONDS)
                            os.kill(driver_pid, signal.SIGKILL)
                        except:
                            pass
                    sys.exit(130)
                
                if script_thread.is_alive():
                    # Thread is STILL running after timeout - this is the hang!
                    print(" TIMEOUT!")
                    print(f"\nError: Script execution hung for {waited} seconds.")
                    print("This is likely due to:")
                    print("  1. Cloudflare blocking the headless browser")
                    print("  2. Network issues preventing API calls")
                    print("  3. Browser/WebDriver malfunction")
                    
                    # Try to get browser logs for debugging
                    try:
                        print("\n[DEBUG] Attempting to retrieve browser console logs...", file=sys.stderr, flush=True)
                        logs = driver.get_log('browser')
                        if logs:
                            print("[DEBUG] Recent browser console messages:")
                            for entry in logs[-10:]:  # Last 10 entries
                                print(f"  [{entry['level']}] {entry['message'][:100]}")
                    except Exception as log_err:
                        print(f"[DEBUG] Could not retrieve browser logs: {log_err}", file=sys.stderr, flush=True)
                    
                    # Check if session is still valid
                    try:
                        if not validate_session(driver):
                            logging.debug("Session is INVALID - browser crashed or disconnected")
                        else:
                            logging.debug("Session is still valid - JavaScript execution is stuck")
                    except:
                        print("[DEBUG] Could not validate session", file=sys.stderr, flush=True)
                    
                    # Force quit - try multiple methods
                    print("\n[DEBUG] Forcefully terminating browser...", file=sys.stderr, flush=True)
                    try:
                        driver.quit()
                    except:
                        pass
                    
                    # Force kill browser process if driver.quit() doesn't work
                    if driver_pid:
                        try:
                            print(f"[DEBUG] Killing browser process {driver_pid}...", file=sys.stderr, flush=True)
                            os.kill(driver_pid, signal.SIGTERM)
                            time.sleep(SHORT_SLEEP_SECONDS)
                            # If still alive, force kill
                            try:
                                os.kill(driver_pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass  # Already dead
                        except Exception as kill_err:
                            print(f"[DEBUG] Could not kill process: {kill_err}", file=sys.stderr, flush=True)
                    
                    time.sleep(DEFAULT_SLEEP_SECONDS)
                    
                    if AUTO_MODE:
                        print("\nThis may require running manually to establish a fresh session:")
                        print("  python3 humblesteamkeysredeemer.py")
                        sys.exit(2)
                    else:
                        sys.exit(1)
                
                # Clear progress dots if any were shown
                if waited > 5:
                    print()
                
                # Check for exceptions
                if exception[0]:
                    if isinstance(exception[0], (InvalidSessionIdException, NoSuchWindowException)):
                        print("FAILED")
                        print("\nError: WebDriver session became invalid during fetch.")
                        driver.quit()
                        sys.exit(1)
                    raise exception[0]
                
                order_details = result[0]
                
                # Validate result
                if order_details is None:
                    print("FAILED")
                    print("\nError: No data returned from order details fetch")
                    print("The JavaScript execution completed but returned None")
                    driver.quit()
                    sys.exit(1)
                
                # Check if JavaScript returned an error object
                if isinstance(order_details, dict) and 'error' in order_details:
                    print("FAILED" if waited <= 5 else "")
                    error_msg = order_details.get('message', 'Unknown error')
                    error_type = order_details.get('error', '')
                    print(f"\nError: {error_msg}")
                    
                    # User-friendly error messages with helpful guidance
                    ERROR_HELP = {
                        'timeout': """
╔══════════════════════════════════════════════════════════════╗
║ ⏱️  REQUEST TIMED OUT                                         ║
╚══════════════════════════════════════════════════════════════╝

Possible causes:
  • Slow network connection
  • Humble Bundle servers overloaded
  • Cloudflare blocking automated requests

Try:
  1. Check your internet connection
  2. Run in manual mode (without --auto flag)
  3. Wait a few minutes and try again
  4. Visit humblebundle.com in your browser to check accessibility
""",
                        'auth_error': """
╔══════════════════════════════════════════════════════════════╗
║ 🔒 AUTHENTICATION FAILED                                     ║
╚══════════════════════════════════════════════════════════════╝

Your session has expired or is invalid.

To fix:
  1. Delete cookie files:
     rm .humblecookies .steamcookies
  
  2. Run manual login:
     python3 humblesteamkeysredeemer.py
  
  3. Complete 2FA if prompted
  
  4. Restart in auto mode if desired:
     python3 humblesteamkeysredeemer.py --auto
""",
                        'network_error': """
╔══════════════════════════════════════════════════════════════╗
║ 🌐 NETWORK ERROR                                             ║
╚══════════════════════════════════════════════════════════════╝

Could not connect to Humble Bundle.

Possible causes:
  • Internet connection lost
  • Cloudflare challenge (run without --auto)
  • Humble Bundle servers down

Check:
  • Network connectivity: ping google.com
  • Humble status: visit humblebundle.com in browser
  • Try again in 5-10 minutes
""",
                        'json_parse_error': """
╔══════════════════════════════════════════════════════════════╗
║ 📄 HUMBLE BUNDLE API ERROR (Malformed JSON)                 ║
╚══════════════════════════════════════════════════════════════╝

Humble Bundle's API returned invalid JSON data.

This is a TEMPORARY Humble Bundle server issue (not your fault).

What this means:
  • Humble Bundle's servers returned corrupted/malformed data
  • This usually resolves itself within a few minutes
  • It's not related to your internet or login

What to do:
  1. Wait 5-10 minutes and try again
  2. Check Humble Bundle status: https://status.humblebundle.com/
  3. If it persists for >1 hour, report to Humble Bundle support
  
The error details have been logged for debugging.
"""
                    }
                    
                    if error_type in ERROR_HELP:
                        print(ERROR_HELP[error_type])
                    else:
                        print(f"\n❌ Error: {error_msg}")
                    
                    # Show additional details if available (for json_parse_error)
                    if error_type == 'json_parse_error' and 'details' in order_details:
                        print(f"\n[DEBUG] {order_details.get('details', '')}")
                    
                    if error_type == 'auth_error':
                        if AUTO_MODE:
                            print("Please run the script manually to re-login.")
                            driver.quit()
                            sys.exit(2)
                    elif error_type in ('network_error', 'json_parse_error'):
                        # These are server/network issues, not auth issues
                        # In auto mode, we can retry later (don't exit with code 2)
                        if AUTO_MODE:
                            print("\nThis is a temporary server issue. The daemon will retry automatically.")
                            driver.quit()
                            sys.exit(1)  # Exit code 1 = retryable error
                    
                    driver.quit()
                    sys.exit(1)
                
                # Success!
                print("OK" if waited <= 5 else " OK")
                
                # Check if any orders failed (look for warnings in browser console)
                failed_order_count = 0
                failed_order_ids = []
                try:
                    logs = driver.get_log('browser')
                    for entry in logs:
                        if 'WARNING' in entry.get('message', '') and 'Failed to fetch order:' in entry.get('message', ''):
                            failed_order_count += 1
                            # Extract order ID from message like "[WARNING] Failed to fetch order: k4ydvFTB8zWUyRZY"
                            msg = entry['message']
                            if ' order:' in msg:
                                order_id = msg.split(' order:')[1].split(' -')[0].strip()
                                if order_id not in failed_order_ids:
                                    failed_order_ids.append(order_id)
                except Exception:
                    pass  # Couldn't get browser logs, that's okay
                
                if isinstance(order_details, list):
                    total_fetched = len(order_details)
                    if failed_order_count > 0:
                        print(f"⚠️  Fetched {total_fetched} orders successfully, {failed_order_count} failed (skipped)")
                        print(f"    Failed order IDs: {', '.join(failed_order_ids[:5])}")
                        if len(failed_order_ids) > 5:
                            print(f"    ... and {len(failed_order_ids) - 5} more")
                        print(f"    (These orders have corrupted data on Humble's side - not your fault)")
                        
                        # Save failed orders to file for debugging (only in non-auto mode)
                        if not AUTO_MODE:
                            try:
                                with open("failed_orders.txt", "w", encoding="utf-8") as f:
                                    f.write("# Orders that failed to fetch (corrupted data on Humble's side)\n")
                                    f.write("# These orders are skipped and won't be processed\n\n")
                                    for order_id in failed_order_ids:
                                        f.write(f"{order_id}\n")
                                print(f"    Full list saved to: failed_orders.txt")
                            except Exception:
                                pass
                    else:
                        print(f"Successfully fetched {total_fetched} orders")
                else:
                    print(f"[DEBUG] Successfully fetched {len(order_details) if isinstance(order_details, list) else 'unknown'} orders", file=sys.stderr, flush=True)
                
                # Save to cache
                _save_cache("humble_order_details", order_details)
                print(f"[DEBUG] Cached order details for future use", file=sys.stderr, flush=True)
            except KeyboardInterrupt:
                raise  # Let outer handler deal with it
            except TimeoutException:
                print("FAILED")
                print("\nError: Selenium TimeoutException while fetching order details.")
                print("The browser's script timeout was exceeded.")
                driver.quit()
                sys.exit(1)
            except Exception as e:
                print("FAILED")
                print(f"\nError fetching order details: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                driver.quit()
                sys.exit(1)

        desired_mode = prompt_mode(order_details,driver)
        if(desired_mode == "2"):
            export_mode(driver,order_details)
            driver.quit()
            sys.exit(0)
        if(desired_mode == "3"):
            humble_chooser_mode(driver,order_details)
            driver.quit()
            sys.exit(0)

        # Auto-Redeem mode
        cls()
        
        # Initialize duplicate detection cache early for better UX
        # This prevents a noticeable pause on the first write operation
        print("Initializing duplicate detection cache...", end=" ", flush=True)
        _initialize_keys_cache()
        print("OK")
        
        unrevealed_keys = []
        revealed_keys = []
        steam_keys = list(find_dict_keys(order_details,"steam_app_id",True))
        total_steam_keys = len(steam_keys)

        # Filter out friend/co-op keys before processing (optional pre-filter)
        friend_keys_prefiltered = []
        if prompt_yes_no("Pre-filter friend/co-op keys before processing? (Recommended)", default_yes=True):
            non_friend_keys = []
            for key in steam_keys:
                is_friend, reason, confidence = is_friend_or_coop_key(key)
                if is_friend:
                    friend_keys_prefiltered.append((key, reason, confidence))
                else:
                    non_friend_keys.append(key)
            
            if friend_keys_prefiltered:
                print(f"Pre-filtered {len(friend_keys_prefiltered)} friend/co-op keys")
                # Save them to friend_keys.csv
                for key, reason, confidence in friend_keys_prefiltered:
                    save_friend_key(key, reason, confidence)
            
            steam_keys = non_friend_keys

        # Load keys that should be excluded (already processed successfully)
        exclude_filters = CSVFiles.get_exclusion_filters()
        original_length = len(steam_keys)
        for filter_file in exclude_filters:
            try:
                with open(filter_file, "r", encoding="utf-8-sig") as f:
                    keycols = f.read()
                filtered_keys = [keycol.strip() for keycol in keycols.replace("\n", ",").split(",")]
                steam_keys = [key for key in steam_keys if key.get("redeemed_key_val",False) not in filtered_keys]
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"Warning: Error reading {filter_file}: {e}")
        
        # Load problematic keys (from errored.csv) - these will be tried LAST
        # IMPORTANT: Match by BOTH gamekey AND name to avoid issues with shared gamekeys (Choice months)
        problematic_keys = []
        problematic_by_name = set()  # Track by (gamekey, name) for exact matching
        errored_file = CSVFiles.ERRORED
        if os.path.exists(errored_file):
            try:
                with open(errored_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.reader(f)
                    # Skip header if present
                    first_row = next(reader, None)
                    if first_row and first_row[0].lower() != "gamekey":
                        # First row is data, not header
                        if len(first_row) >= 2:
                            gamekey = first_row[0].strip()
                            name = first_row[1].strip().lower()
                            problematic_by_name.add((gamekey, name))
                    # Read remaining rows
                    for row in reader:
                        if len(row) >= 2:
                            gamekey = row[0].strip()
                            name = row[1].strip().lower()
                            problematic_by_name.add((gamekey, name))
            except Exception as e:
                print(f"Warning: Error reading {errored_file}: {e}")
        
        # Separate keys into normal and problematic (match by gamekey AND name)
        # IMPORTANT: Deduplicate problematic_keys to avoid processing the same game multiple times
        normal_keys = []
        problematic_seen = set()  # Track (gamekey, name) combinations already added
        for key in steam_keys:
            gamekey = key.get("gamekey", "")
            key_name = key.get("human_name", "").strip().lower()
            
            # Only mark as problematic if there's an exact match (gamekey + name) in errored.csv
            # This prevents games with shared gamekeys from being incorrectly marked as problematic
            if gamekey and (gamekey, key_name) in problematic_by_name:
                # Deduplicate - only add each (gamekey, name) combination once
                key_id = (gamekey, key_name)
                if key_id not in problematic_seen:
                    problematic_seen.add(key_id)
                    problematic_keys.append(key)
                # else: silently skip duplicate
            else:
                normal_keys.append(key)
        
        # Use normal keys for main processing, problematic keys will be retried at the end
        steam_keys = normal_keys
        filtered_count = original_length - len(steam_keys) - len(problematic_keys)
        unredeemed_count = len(steam_keys)
        if filtered_count > 0 or len(problematic_keys) > 0:
            msg = f"Found {total_steam_keys} Steam keys, {filtered_count} already processed"
            if len(problematic_keys) > 0:
                msg += f", {len(problematic_keys)} problematic (will retry last)"
            msg += f", {unredeemed_count} unredeemed"
            print(msg)
        else:
            print(f"Found {total_steam_keys} Steam keys, {unredeemed_count} unredeemed")

        for key in steam_keys:
            if "redeemed_key_val" in key:
                revealed_keys.append(key)
            else:
                # Has not been revealed via Humble yet
                unrevealed_keys.append(key)

        print(
            f"{len(steam_keys)} Steam keys total -- {len(revealed_keys)} revealed, {len(unrevealed_keys)} unrevealed"
        )
        
        # Check for unrevealed Choice games that need to be selected first
        unrevealed_choice_games = []
        if unrevealed_keys and order_details:
            # Create a requests session for Choice API calls
            request_session = requests.Session()
            for cookie in driver.get_cookies():
                request_session.cookies.set(
                    cookie['name'],
                    cookie['value'],
                    domain=cookie['domain'].replace('www.', ''),
                    path=cookie['path']
                )
            
            # Find Choice months with unselected games
            choice_months = [
                month for month in order_details 
                if "choice_url" in month.get("product", {})
            ]
            
            # Load completed Choice months to skip already-processed ones
            completed_choice_months = load_completed_choice_months()
            
            # Filter out completed months
            incomplete_months = [
                month for month in choice_months
                if month.get('gamekey') not in completed_choice_months
            ]
            
            skipped_count = len(choice_months) - len(incomplete_months)
            if skipped_count > 0:
                print(f"Skipping {skipped_count} already-completed Choice month(s)")
            
            # Process Choice months with timeout protection
            print(f"Checking {len(incomplete_months)} Choice months for unselected games...")
            for idx, month in enumerate(incomplete_months, 1):
                month_name = month.get("product", {}).get("human_name", f"Month {idx}")
                try:
                    # Add timeout protection - get_month_data can hang
                    print(f"  [{idx}/{len(incomplete_months)}] Checking {month_name}...", end=" ", flush=True)
                    try:
                        month["choice_data"] = get_month_data(request_session, month)
                        print("✓")
                    except Exception as data_err:
                        print(f"✗ (skipped: {str(data_err)[:50]})")
                        logging.debug(f"Error getting month data for {month_name}: {data_err}")
                        continue
                    
                    if not month["choice_data"].get('canRedeemGames', True):
                        continue
                    
                    chosen_games = set(find_dict_keys(month.get("tpkd_dict", {}), "machine_name"))
                    v3 = not month["choice_data"].get("usesChoices", True)
                    
                    if v3:
                        choice_options = month["choice_data"]["contentChoiceData"]["game_data"]
                    else:
                        identifier = "initial" if "initial" in month["choice_data"]["contentChoiceData"] else "initial-classic"
                        if identifier not in month["choice_data"]["contentChoiceData"]:
                            for key in month["choice_data"]["contentChoiceData"].keys():
                                if "content_choices" in month["choice_data"]["contentChoiceData"][key]:
                                    identifier = key
                                    break
                        choice_options = month["choice_data"]["contentChoiceData"][identifier]["content_choices"]
                    
                    # Find unrevealed Choice games that match unrevealed keys
                    for game_key in unrevealed_keys:
                        gamekey = game_key.get("gamekey", "")
                        if gamekey == month.get("gamekey", ""):
                            # This is a Choice month key
                            machine_name = game_key.get("machine_name", "")
                            if machine_name:
                                # Check if game is already selected (in tpkd_dict)
                                is_selected = machine_name in chosen_games
                                
                                if not is_selected:
                                    # Game is NOT selected - needs selection first
                                    # Check if this game is available in choices
                                    for choice_key, choice_data in choice_options.items():
                                        choice_machine_names = set(find_dict_keys(choice_data, "machine_name"))
                                        if machine_name in choice_machine_names:
                                            unrevealed_choice_games.append({
                                                'month': month,
                                                'game': game_key,
                                                'choice_to_select': choice_data,
                                                'identifier': identifier if not v3 else "initial",
                                                'needs_selection': True
                                            })
                                            break
                                # If is_selected is True, the game is already selected and just needs reveal
                                # (will be handled normally by redeem_steam_keys)
                except Exception as e:
                    # Skip months that fail to load
                    print(f"✗ Error: {str(e)[:50]}")
                    logging.debug(f"Error checking Choice month {month.get('product', {}).get('human_name', 'Unknown')}: {e}")
                    continue
            
            if unrevealed_choice_games:
                print(f"\n✓ Found {len(unrevealed_choice_games)} games that need selection")
            else:
                print("\n✓ No unselected Choice games found")
        
        # Auto-select unrevealed Choice games if found
        if unrevealed_choice_games:
            print(f"\n⚠️  Found {len(unrevealed_choice_games)} unrevealed Humble Choice games that need to be SELECTED first")
            auto_select = prompt_yes_no("Would you like to automatically select these games? (Recommended)", default_yes=True)
            if auto_select:
                print("\nAuto-selecting unrevealed Choice games...")
                for item in unrevealed_choice_games:
                    month = item['month']
                    game = item['game']
                    choice_to_select = item['choice_to_select']
                    identifier = item['identifier']
                    
                    try:
                        choice_month_name = month.get("product", {}).get("choice_url", "")
                        choose_games(driver, choice_month_name, identifier, [choice_to_select])
                        print(f"  ✓ Selected: {game.get('human_name', 'Unknown')}")
                        time.sleep(1)  # Brief pause between selections
                    except Exception as e:
                        print(f"  ✗ Failed to select {game.get('human_name', 'Unknown')}: {e}")
                        logging.debug(f"Error selecting Choice game: {e}", exc_info=True)
                
                # Refresh order details after selections
                print("\nRefreshing order details after selections...")
                try:
                    # Pass empty list as proper argument instead of string replacement
                    order_details = driver.execute_async_script(getHumbleOrders, [])
                    if isinstance(order_details, dict) and 'error' in order_details:
                        print(f"Warning: Error refreshing orders: {order_details.get('message', 'Unknown error')}")
                    else:
                        # Re-filter unrevealed keys with updated data
                        steam_keys = list(find_dict_keys(order_details, "steam_app_id", True))
                        unrevealed_keys = [key for key in steam_keys if "redeemed_key_val" not in key]
                        revealed_keys = [key for key in steam_keys if "redeemed_key_val" in key]
                        print(f"✓ Updated: {len(revealed_keys)} revealed, {len(unrevealed_keys)} unrevealed")
                except Exception as e:
                    print(f"Warning: Could not refresh order details: {e}")
                    logging.debug(f"Error refreshing orders: {e}", exc_info=True)

        will_reveal_keys = prompt_yes_no("Would you like to redeem on Humble as-yet un-revealed Steam keys?"
                                    " (Revealing keys removes your ability to generate gift links for them)", default_yes=True)
        if will_reveal_keys:
            try_already_revealed = prompt_yes_no("Would you like to attempt redeeming already-revealed keys as well?", default_yes=True)
            # User has chosen to either redeem all keys or just the 'unrevealed' ones.
            steam_session = redeem_steam_keys(driver, steam_keys if try_already_revealed else unrevealed_keys, order_details)
        else:
            # User has excluded unrevealed keys.
            steam_session = redeem_steam_keys(driver, revealed_keys, order_details)
        # Retry problematic keys after main redemption (these were marked as problematic on previous runs)
        # These keys already have redeemed_key_val from errored.csv, so we can retry them directly
        if problematic_keys:
            print(f"\n{'='*60}")
            print(f"Retrying {len(problematic_keys)} previously problematic keys (trying last)...")
            print(f"{'='*60}\n")
            # Load the redeemed_key_val from errored.csv for these keys
            # IMPORTANT: Match by both gamekey AND name to avoid issues with shared gamekeys (Choice months)
            # IMPORTANT: Deduplicate entries - prefer valid keys over empty/invalid ones
            errored_dict = {}  # gamekey -> key_val (fallback for games without name match)
            errored_by_name = {}  # (gamekey, name) -> key_val (preferred - exact match)
            if os.path.exists(CSVFiles.ERRORED):
                try:
                    with open(CSVFiles.ERRORED, "r", encoding=CSV_ENCODING) as f:
                        reader = csv.reader(f)
                        first_row = next(reader, None)
                        if first_row and first_row[0].lower() != "gamekey":
                            if len(first_row) >= 3:
                                gamekey = first_row[0].strip()
                                name = first_row[1].strip().lower() if len(first_row) > 1 else ""
                                key_val = first_row[2].strip()
                                # Only store if we don't have a better (valid) key already
                                if name:
                                    if (gamekey, name) not in errored_by_name or (
                                        not valid_steam_key(errored_by_name.get((gamekey, name), "")) and 
                                        valid_steam_key(key_val)
                                    ):
                                        errored_by_name[(gamekey, name)] = key_val
                                if gamekey not in errored_dict or (
                                    not valid_steam_key(errored_dict.get(gamekey, "")) and 
                                    valid_steam_key(key_val)
                                ):
                                    errored_dict[gamekey] = key_val
                        for row in reader:
                            if len(row) >= 3:
                                gamekey = row[0].strip()
                                name = row[1].strip().lower() if len(row) > 1 else ""
                                key_val = row[2].strip()
                                # Only store if we don't have a better (valid) key already
                                if name:
                                    if (gamekey, name) not in errored_by_name or (
                                        not valid_steam_key(errored_by_name.get((gamekey, name), "")) and 
                                        valid_steam_key(key_val)
                                    ):
                                        errored_by_name[(gamekey, name)] = key_val
                                if gamekey not in errored_dict or (
                                    not valid_steam_key(errored_dict.get(gamekey, "")) and 
                                    valid_steam_key(key_val)
                                ):
                                    errored_dict[gamekey] = key_val
                except Exception as e:
                    print(f"Warning: Error reading errored.csv: {e}")
            
                # Update problematic keys with their redeemed_key_val from errored.csv
                # IMPORTANT: Match by both gamekey AND name to avoid issues with shared gamekeys (Choice months)
                keys_to_retry = []
                seen_keys = set()  # Track by (gamekey, name) to avoid duplicates
                friend_keys_in_problematic = []  # Track friend keys found in problematic keys
                skip_friend_keys = True  # Use same setting as main flow
                
                for key in problematic_keys:
                    gamekey = key.get("gamekey", "")
                    key_name = key.get("human_name", "").strip().lower()
                    
                    # Skip duplicates (same gamekey + name combination)
                    key_id = (gamekey, key_name)
                    if key_id in seen_keys:
                        continue  # Already processed this exact game
                    seen_keys.add(key_id)
                    
                    # Check if this is a friend key (shouldn't retry friend keys!)
                    if skip_friend_keys:
                        is_friend, reason, confidence = is_friend_or_coop_key(key)
                        if is_friend and confidence >= 0.8:
                            # Move to friend_keys.csv instead of retrying
                            friend_keys_in_problematic.append((key, reason, confidence))
                            continue
                    
                    # Try to find matching key_val - prefer exact name match
                    key_val = None
                    if (gamekey, key_name) in errored_by_name:
                        key_val = errored_by_name[(gamekey, key_name)]
                    elif gamekey in errored_dict:
                        key_val = errored_dict[gamekey]
                    
                    if key_val:
                        # Validate BEFORE adding to retry list
                        if not key_val or key_val == "" or key_val == "EXPIRED":
                            # Empty or expired - skip silently, will be handled by normal flow
                            continue
                        elif not valid_steam_key(key_val):
                            # Invalid key format - skip silently to avoid spam
                            continue
                        else:
                            # Valid key - set it and add to retry list
                            key["redeemed_key_val"] = key_val
                            keys_to_retry.append(key)
                    else:
                        # No entry in errored.csv for this specific game - skip silently
                        # No need to retry if there's no key value in errored.csv
                        continue
            
            # Save friend keys found in problematic list
            if friend_keys_in_problematic:
                print(f"Found {len(friend_keys_in_problematic)} friend keys in problematic list - moved to friend_keys.csv")
                for key, reason, confidence in friend_keys_in_problematic:
                    save_friend_key(key, f"from errored.csv: {reason}", confidence)
                    # Remove from errored.csv
                    remove_from_errored_csv(key.get("gamekey", ""), key.get("human_name", ""))
            
            if keys_to_retry:
                # Retry these keys directly (they already have redeemed_key_val)
                total_retry = len(keys_to_retry)
                for idx, key in enumerate(keys_to_retry, 1):
                    remaining = total_retry - idx + 1
                    print(f"[RETRY {idx}/{total_retry}] {key['human_name']} ({remaining} remaining)")
                    
                    # Double-check key validity before attempting
                    if not valid_steam_key(key["redeemed_key_val"]):
                        print(f"  -> Invalid key format, skipping")
                        continue
                    
                    code = _redeem_steam(steam_session, key["redeemed_key_val"])
                    if code == SteamErrorCode.RATE_LIMITED:
                        # Use reusable rate limit handler
                        code = wait_for_rate_limit_clear(
                            steam_session,
                            key["redeemed_key_val"],
                            remaining,
                            keepalive=None,  # No keepalive in retry context
                            retry_interval=RATE_LIMIT_RETRY_INTERVAL_SECONDS,
                            check_interval=RATE_LIMIT_CHECK_INTERVAL_SECONDS
                        )
                    
                    # Write key INSIDE the for loop
                    write_key(code, key)
            else:
                print("No valid keys found to retry from problematic keys list.")
        
        # Also retry any keys that errored during THIS run
        retry_errored_keys(driver, steam_session, order_details)

        # Cleanup (files are automatically closed via context managers)
        if driver:
            driver.quit()
        print("\n" + "="*60)
        print("Script completed successfully!")
        print(f"Ended at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C). Exiting...")
        try:
            if driver:
                driver.quit()
        except:
            pass
        # Files are automatically closed via context managers
        sys.exit(130)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        try:
            if driver:
                driver.quit()
        except:
            pass
        # Files are automatically closed via context managers
        sys.exit(1)
    finally:
        # Files are automatically closed via context managers
        pass