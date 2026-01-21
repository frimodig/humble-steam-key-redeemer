#!/bin/bash
# Humble Steam Key Redeemer Daemon
# Automatically restarts the script if it crashes/times out

set -euo pipefail  # Exit on error, undefined variables, pipe failures

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
LOG_FILE="daemon.log"
PID_FILE="daemon.pid"
LOCK_FILE="daemon.lock"
MAX_RETRIES=100      # Max restarts before giving up
RETRY_DELAY=30       # Seconds to wait between restarts
HEALTH_CHECK_INTERVAL=300  # Check if process is alive every 5 minutes
MAX_LOG_SIZE=10485760  # 10MB - rotate log if larger

# Allow timeout override via environment variable
SCRIPT_TIMEOUT="${HUMBLE_DAEMON_TIMEOUT:-7200}"  # Default 2 hours (configurable via env)

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Cleanup function
cleanup() {
    local exit_code=$?
    if [ -f "$LOCK_FILE" ]; then
        rm -f "$LOCK_FILE"
    fi
    exit $exit_code
}

# Set trap for cleanup
trap cleanup EXIT INT TERM

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_no_tee() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
    log "ERROR: $*"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $*" >&2
    log "WARNING: $*"
}

info() {
    echo -e "${CYAN}[INFO]${NC} $*"
    log "INFO: $*"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
    log "SUCCESS: $*"
}

usage() {
    cat << EOF
Humble Steam Key Redeemer Daemon

Usage: $0 [options]

Options:
  -h, --help        Show this help message
  -b, --background  Run in background (detached from terminal)
  -s, --stats       Show current statistics
  -t, --status      Show daemon status
  -k, --stop        Stop the running daemon
  -r, --restart     Restart the daemon
  -l, --log [N]     Show last N log entries (default: 50)
  --internal        (Internal use only - runs the actual daemon loop)

IMPORTANT: Run the script manually FIRST to log in:
  python3 humblesteamkeysredeemer.py

Once logged in, run the daemon:
  ./run_daemon.sh

To run in background (survives terminal close):
  ./run_daemon.sh --background

To check status:
  ./run_daemon.sh --status

To check progress:
  ./run_daemon.sh --stats

To stop the daemon:
  ./run_daemon.sh --stop

To restart the daemon:
  ./run_daemon.sh --restart

To monitor logs:
  tail -f daemon.log
  # Or use the built-in log viewer:
  ./run_daemon.sh --log 100

Exit Codes:
  0   - Success / daemon completed
  1   - General error
  2   - Stale cookies (manual login required)
  3   - Already running
  4   - Not running (when trying to stop)
  130 - User interrupt (Ctrl+C)

EOF
    exit 0
}

# Check if Python script exists
check_prerequisites() {
    if [ ! -f "humblesteamkeysredeemer.py" ]; then
        error "humblesteamkeysredeemer.py not found in $SCRIPT_DIR"
        exit 1
    fi
    
    if ! command -v python3 &> /dev/null; then
        error "python3 not found. Please install Python 3."
        exit 1
    fi
    
    # Check if timeout command is available
    if ! command -v timeout &> /dev/null; then
        warning "timeout command not found. Process will not have time limits."
    fi
}

# Get file modification time (cross-platform)
get_file_age() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "0"
        return
    fi
    
    local current_time=$(date +%s)
    local file_time
    
    # Try BSD stat first (macOS)
    file_time=$(stat -f %m "$file" 2>/dev/null || true)
    
    # Try GNU stat (Linux)
    if [ -z "$file_time" ]; then
        file_time=$(stat -c %Y "$file" 2>/dev/null || true)
    fi
    
    # Fallback to ls-based method
    if [ -z "$file_time" ]; then
        # This is less accurate but works everywhere
        file_time=$(date -r "$file" +%s 2>/dev/null || echo "$current_time")
    fi
    
    echo $((current_time - file_time))
}

# Get file size (cross-platform)
get_file_size() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "0"
        return
    fi
    
    # Try BSD stat first (macOS)
    local size=$(stat -f %z "$file" 2>/dev/null || true)
    
    # Try GNU stat (Linux)
    if [ -z "$size" ]; then
        size=$(stat -c %s "$file" 2>/dev/null || true)
    fi
    
    # Fallback to wc (less efficient but universal)
    if [ -z "$size" ]; then
        size=$(wc -c < "$file" 2>/dev/null || echo "0")
    fi
    
    echo "$size"
}

# Show recent log entries
show_log() {
    local lines="${1:-50}"  # Default to 50 lines
    
    if [ ! -f "$LOG_FILE" ]; then
        warning "Log file not found"
        return 1
    fi
    
    echo ""
    echo "╔═══════════════════════════════════════╗"
    echo "║        RECENT LOG ENTRIES             ║"
    echo "╚═══════════════════════════════════════╝"
    echo ""
    tail -n "$lines" "$LOG_FILE"
    echo ""
}

# Rotate log if too large
rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        local size=$(get_file_size "$LOG_FILE")
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            log "Rotating log file (size: $size bytes)"
            mv "$LOG_FILE" "${LOG_FILE}.old"
            # Keep only last rotation
            [ -f "${LOG_FILE}.old.1" ] && rm -f "${LOG_FILE}.old.1"
            [ -f "${LOG_FILE}.old" ] && mv "${LOG_FILE}.old" "${LOG_FILE}.old.1"
        fi
    fi
}

# Count lines in a file (0 if doesn't exist)
count_file() {
    if [ -f "$1" ]; then
        # Count non-empty lines, skip header if present
        local count=$(tail -n +2 "$1" 2>/dev/null | grep -c . 2>/dev/null || echo "0")
        echo "$count"
    else
        echo "0"
    fi
}

# Show statistics
show_stats() {
    local redeemed=$(count_file "redeemed.csv")
    local errored=$(count_file "errored.csv")
    local expired=$(count_file "expired.csv")
    local already_owned=$(count_file "already_owned.csv")
    local total=$((redeemed + errored + expired + already_owned))
    
    echo ""
    echo "╔═══════════════════════════════════════╗"
    echo "║   HUMBLE KEY REDEEMER STATISTICS      ║"
    echo "╠═══════════════════════════════════════╣"
    echo -e "║  ${GREEN}✓ Redeemed:${NC}        $(printf '%6d' $redeemed)          ║"
    echo -e "║  ${BLUE}○ Already Owned:${NC}   $(printf '%6d' $already_owned)          ║"
    echo -e "║  ${YELLOW}⚠ Expired:${NC}         $(printf '%6d' $expired)          ║"
    echo -e "║  ${RED}✗ Errored:${NC}         $(printf '%6d' $errored)          ║"
    echo "╠═══════════════════════════════════════╣"
    echo "║  Total Processed:  $(printf '%6d' $total)          ║"
    echo "╚═══════════════════════════════════════╝"
    echo ""
}

# Show stats without colors (for log file)
show_stats_plain() {
    local redeemed=$(count_file "redeemed.csv")
    local errored=$(count_file "errored.csv")
    local expired=$(count_file "expired.csv")
    local already_owned=$(count_file "already_owned.csv")
    local total=$((redeemed + errored + expired + already_owned))
    
    echo ""
    echo "========== STATISTICS =========="
    printf "  Redeemed:      %6d\n" "$redeemed"
    printf "  Already Owned: %6d\n" "$already_owned"
    printf "  Expired:       %6d\n" "$expired"
    printf "  Errored:       %6d\n" "$errored"
    echo "  ─────────────────────────────"
    printf "  Total:         %6d\n" "$total"
    echo "================================"
    echo ""
}

# Check if daemon is running
is_running() {
    if [ ! -f "$PID_FILE" ]; then
        return 1
    fi
    
    local pid=$(cat "$PID_FILE" 2>/dev/null)
    if [ -z "$pid" ]; then
        return 1
    fi
    
    # Check if process exists and is our script
    if ps -p "$pid" > /dev/null 2>&1; then
        # Verify it's actually our daemon (check for both scripts)
        if ps -p "$pid" -o command= 2>/dev/null | grep -q "humblesteamkeysredeemer.py\|run_daemon.sh"; then
            return 0
        fi
    fi
    
    # PID file exists but process doesn't - clean up stale PID file
    rm -f "$PID_FILE"
    return 1
}

# Show daemon status
show_status() {
    echo ""
    echo "╔═══════════════════════════════════════╗"
    echo "║          DAEMON STATUS                ║"
    echo "╠═══════════════════════════════════════╣"
    
    if is_running; then
        local pid=$(cat "$PID_FILE")
        local uptime=$(ps -p "$pid" -o etime= 2>/dev/null | xargs)
        echo -e "║  Status:    ${GREEN}RUNNING${NC}                  ║"
        echo "║  PID:       $(printf '%-24s' "$pid") ║"
        echo "║  Uptime:    $(printf '%-24s' "$uptime") ║"
        
        # Show last log line
        if [ -f "$LOG_FILE" ]; then
            local last_log=$(tail -n 1 "$LOG_FILE" 2>/dev/null | cut -c1-35)
            if [ -n "$last_log" ]; then
                echo "╠═══════════════════════════════════════╣"
                echo "║  Last Log:                            ║"
                echo "║  $(printf '%-37s' "$last_log") ║"
            fi
        fi
    else
        echo -e "║  Status:    ${RED}NOT RUNNING${NC}              ║"
    fi
    
    echo "╠═══════════════════════════════════════╣"
    echo "║  Configuration:                       ║"
    local timeout_hours=$((SCRIPT_TIMEOUT / 3600))
    local timeout_minutes=$((SCRIPT_TIMEOUT % 3600 / 60))
    if [ $timeout_hours -gt 0 ]; then
        echo "║  Timeout:   $(printf '%-24s' "${timeout_hours}h ${timeout_minutes}m") ║"
    else
        echo "║  Timeout:   $(printf '%-24s' "${timeout_minutes}m") ║"
    fi
    echo "╠═══════════════════════════════════════╣"
    echo "║  Files:                               ║"
    
    # Check for session files
    if [ -f ".humblecookies" ]; then
        local age=$(get_file_age ".humblecookies")
        local days=$((age / 86400))
        echo -e "║  Humble:    ${GREEN}✓${NC} (${days}d old)               ║"
    else
        echo -e "║  Humble:    ${RED}✗ Missing${NC}                 ║"
    fi
    
    if [ -f ".steamcookies" ]; then
        local age=$(get_file_age ".steamcookies")
        local days=$((age / 86400))
        echo -e "║  Steam:     ${GREEN}✓${NC} (${days}d old)               ║"
    else
        echo -e "║  Steam:     ${RED}✗ Missing${NC}                 ║"
    fi
    
    echo "╚═══════════════════════════════════════╝"
    echo ""
    
    # Show stats
    show_stats
}

# Stop the daemon
stop_daemon() {
    if ! is_running; then
        warning "Daemon is not running"
        return 4
    fi
    
    local pid=$(cat "$PID_FILE")
    info "Stopping daemon (PID: $pid)..."
    
    # Try graceful shutdown first
    kill -TERM "$pid" 2>/dev/null || true
    
    # Wait up to 10 seconds for graceful shutdown
    for i in {1..10}; do
        if ! ps -p "$pid" > /dev/null 2>&1; then
            success "Daemon stopped successfully"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    
    # Force kill if still running
    warning "Daemon did not stop gracefully, forcing..."
    kill -KILL "$pid" 2>/dev/null || true
    sleep 1
    
    if ! ps -p "$pid" > /dev/null 2>&1; then
        success "Daemon stopped (forced)"
        rm -f "$PID_FILE"
        return 0
    else
        error "Failed to stop daemon"
        return 1
    fi
}

# Check for existing sessions
check_sessions() {
    local missing=false
    
    if [ ! -f ".humblecookies" ]; then
        warning "No Humble session found (.humblecookies missing)"
        missing=true
    else
        # Check if cookies are stale (older than 30 days)
        local age=$(get_file_age ".humblecookies")
        if [ "$age" -gt 2592000 ]; then  # 30 days
            warning "Humble session is quite old ($(($age / 86400)) days)"
        fi
    fi
    
    if [ ! -f ".steamcookies" ]; then
        warning "No Steam session found (.steamcookies missing)"
        missing=true
    else
        # Check if cookies are stale (older than 30 days)
        local age=$(get_file_age ".steamcookies")
        if [ "$age" -gt 2592000 ]; then  # 30 days
            warning "Steam session is quite old ($(($age / 86400)) days)"
        fi
    fi
    
    if [ "$missing" = true ]; then
        echo ""
        error "Missing login sessions!"
        echo "Please run the script manually first to establish sessions:"
        echo "  python3 humblesteamkeysredeemer.py"
        echo ""
        
        # In non-interactive mode, just exit
        if [ ! -t 0 ]; then
            exit 1
        fi
        
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Acquire lock to prevent multiple instances
acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid=$(cat "$LOCK_FILE" 2>/dev/null)
        if [ -n "$lock_pid" ] && ps -p "$lock_pid" > /dev/null 2>&1; then
            error "Daemon already running (PID: $lock_pid)"
            exit 3
        else
            # Stale lock file
            warning "Removing stale lock file"
            rm -f "$LOCK_FILE"
        fi
    fi
    
    echo $$ > "$LOCK_FILE"
}

# Release lock
release_lock() {
    rm -f "$LOCK_FILE"
}

# Monitor process health
monitor_health() {
    local pid=$1
    local last_size=0
    
    log_no_tee "Health monitor started for PID $pid"
    
    while ps -p "$pid" > /dev/null 2>&1; do
        sleep "$HEALTH_CHECK_INTERVAL"
        
        # Check if log file is growing (sign of activity)
        if [ -f "$LOG_FILE" ]; then
            local current_size=$(get_file_size "$LOG_FILE")
            if [ "$current_size" -eq "$last_size" ]; then
                log_no_tee "Health check: No log activity in last ${HEALTH_CHECK_INTERVAL}s (may be normal)"
            else
                log_no_tee "Health check: Process active (log growing)"
            fi
            last_size=$current_size
        fi
        
        # Rotate log if needed
        rotate_log
    done
    
    log_no_tee "Health monitor stopped (process $pid ended)"
}

# Main daemon loop
run_daemon() {
    log "========================================"
    log "Humble Redeemer Daemon Started"
    log "PID: $$"
    log "========================================"
    
    # Save PID
    echo $$ > "$PID_FILE"
    
    # Start health monitor in background
    monitor_health $$ &
    local health_pid=$!
    
    # Record starting stats
    local start_redeemed=$(count_file "redeemed.csv")
    local start_time=$(date +%s)
    local retry_count=0
    local consecutive_failures=0
    local max_consecutive_failures=3

    while [ $retry_count -lt $MAX_RETRIES ]; do
        log ""
        log "Starting redeemer (attempt $((retry_count + 1))/$MAX_RETRIES)..."
        
        # Run the script in auto mode with timeout (if available)
        set +e  # Temporarily disable exit on error
        
        if command -v timeout &> /dev/null; then
            # Use timeout if available (configurable via env var)
            timeout $SCRIPT_TIMEOUT python3 humblesteamkeysredeemer.py --auto 2>&1 | tee -a "$LOG_FILE"
            exit_code=${PIPESTATUS[0]}
        else
            # No timeout available - run without limit
            python3 humblesteamkeysredeemer.py --auto 2>&1 | tee -a "$LOG_FILE"
            exit_code=${PIPESTATUS[0]}
        fi
        
        set -e
        
        log ""
        log "Script exited with code: $exit_code"
        
        # Show session stats
        local current_redeemed=$(count_file "redeemed.csv")
        local session_redeemed=$((current_redeemed - start_redeemed))
        log "Session progress: +$session_redeemed redeemed this session"
        
        # Check exit codes
        case $exit_code in
            0)
                log ""
                log "✓ Script completed successfully! All keys processed."
                consecutive_failures=0
                break
                ;;
            124)
                # Timeout
                local timeout_hours=$((SCRIPT_TIMEOUT / 3600))
                local timeout_minutes=$((SCRIPT_TIMEOUT % 3600 / 60))
                if [ $timeout_hours -gt 0 ]; then
                    warning "Script timed out after ${timeout_hours}h ${timeout_minutes}m"
                else
                    warning "Script timed out after ${timeout_minutes}m"
                fi
                consecutive_failures=$((consecutive_failures + 1))
                ;;
            130|143)
                # SIGINT (130) or SIGTERM (143)
                log "Script stopped by signal (code $exit_code)"
                break
                ;;
            2)
                # Stale cookies - DO NOT RETRY, need manual intervention
                log ""
                log "✗ STALE COOKIES - Manual login required!"
                log ""
                log "The login session has expired. To fix:"
                log "  1. Run: python3 humblesteamkeysredeemer.py"
                log "  2. Complete the login process"
                log "  3. Restart the daemon: ./run_daemon.sh --restart"
                log ""
                
                # Stop health monitor gracefully
                if ps -p $health_pid > /dev/null 2>&1; then
                    kill -TERM $health_pid 2>/dev/null || true
                    # Give it 2 seconds to exit gracefully
                    local timeout=20
                    while ps -p $health_pid > /dev/null 2>&1 && [ $timeout -gt 0 ]; do
                        sleep 0.1
                        timeout=$((timeout - 1))
                    done
                    # Force kill if still alive
                    if ps -p $health_pid > /dev/null 2>&1; then
                        kill -KILL $health_pid 2>/dev/null || true
                    fi
                fi
                wait $health_pid 2>/dev/null || true
                
                # Clean up and exit with code 2
                rm -f "$PID_FILE"
                release_lock
                exit 2
                ;;
            *)
                # Other error - retry after delay
                warning "Unexpected exit (code $exit_code)"
                consecutive_failures=$((consecutive_failures + 1))
                
                # If too many consecutive failures, give up
                if [ $consecutive_failures -ge $max_consecutive_failures ]; then
                    error "Too many consecutive failures ($consecutive_failures). Giving up."
                    break
                fi
                ;;
        esac
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $MAX_RETRIES ] && [ $exit_code -ne 0 ]; then
            log "Restarting in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    done

    # Stop health monitor gracefully
    if ps -p $health_pid > /dev/null 2>&1; then
        kill -TERM $health_pid 2>/dev/null || true
        # Give it 2 seconds to exit gracefully
        local timeout=20
        while ps -p $health_pid > /dev/null 2>&1 && [ $timeout -gt 0 ]; do
            sleep 0.1
            timeout=$((timeout - 1))
        done
        # Force kill if still alive
        if ps -p $health_pid > /dev/null 2>&1; then
            kill -KILL $health_pid 2>/dev/null || true
        fi
    fi
    wait $health_pid 2>/dev/null || true

    if [ $retry_count -ge $MAX_RETRIES ]; then
        error "Max retries ($MAX_RETRIES) reached. Giving up."
    fi

    # Final statistics
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local hours=$((duration / 3600))
    local minutes=$(((duration % 3600) / 60))
    local seconds=$((duration % 60))
    
    local final_redeemed=$(count_file "redeemed.csv")
    local total_session_redeemed=$((final_redeemed - start_redeemed))
    
    log ""
    log "╔═══════════════════════════════════════╗"
    log "║         SESSION SUMMARY               ║"
    log "╠═══════════════════════════════════════╣"
    log "$(printf '║  Duration:  %02d:%02d:%02d                  ║' "$hours" "$minutes" "$seconds")"
    log "$(printf '║  Redeemed:  +%-5d (this session)     ║' "$total_session_redeemed")"
    log "╚═══════════════════════════════════════╝"
    
    # Show full stats to terminal (with colors)
    if [ -t 1 ]; then  # Only show colored output if stdout is a terminal
        show_stats
    fi
    
    # Log plain version
    show_stats_plain >> "$LOG_FILE"
    
    log ""
    log "Daemon stopped."
    
    # Clean up
    rm -f "$PID_FILE"
    release_lock
}

# Parse arguments
BACKGROUND=false
INTERNAL=false
SHOW_STATS=false
SHOW_STATUS=false
STOP_DAEMON=false
RESTART_DAEMON=false
SHOW_LOG=false
LOG_LINES=50

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -b|--background)
            BACKGROUND=true
            shift
            ;;
        -s|--stats)
            SHOW_STATS=true
            shift
            ;;
        -t|--status)
            SHOW_STATUS=true
            shift
            ;;
        -k|--stop)
            STOP_DAEMON=true
            shift
            ;;
        -r|--restart)
            RESTART_DAEMON=true
            shift
            ;;
        -l|--log)
            SHOW_LOG=true
            if [[ $# -gt 1 && "$2" =~ ^[0-9]+$ ]]; then
                LOG_LINES="$2"
                shift
            fi
            shift
            ;;
        --internal)
            INTERNAL=true
            shift
            ;;
        *)
            error "Unknown option: $1"
            usage
            ;;
    esac
done

# Check prerequisites
check_prerequisites

# Status mode - show status and exit
if [ "$SHOW_STATUS" = true ]; then
    show_status
    exit 0
fi

# Stats mode - just show stats and exit
if [ "$SHOW_STATS" = true ]; then
    show_stats
    exit 0
fi

# Log mode - show recent log entries
if [ "$SHOW_LOG" = true ]; then
    show_log "$LOG_LINES"
    exit 0
fi

# Stop mode
if [ "$STOP_DAEMON" = true ]; then
    stop_daemon
    exit $?
fi

# Restart mode
if [ "$RESTART_DAEMON" = true ]; then
    info "Restarting daemon..."
    if is_running; then
        stop_daemon
        sleep 2
    fi
    # Fall through to start daemon
    BACKGROUND=true
fi

# Internal mode - just run the daemon (used by background mode)
if [ "$INTERNAL" = true ]; then
    acquire_lock
    rotate_log
    run_daemon
    exit 0
fi

# Main execution path
check_sessions

if [ "$BACKGROUND" = true ]; then
    # Check if already running
    if is_running; then
        error "Daemon is already running!"
        show_status
        exit 3
    fi
    
    info "Starting daemon in background..."
    echo "Logs will be written to: $SCRIPT_DIR/$LOG_FILE"
    echo ""
    echo "Useful commands:"
    echo "  Check status:  ./run_daemon.sh --status"
    echo "  View stats:    ./run_daemon.sh --stats"
    echo "  Monitor logs:  tail -f $LOG_FILE"
    echo "  Stop daemon:   ./run_daemon.sh --stop"
    echo "  Restart:       ./run_daemon.sh --restart"
    echo ""
    
    # Start in background using nohup and properly detach
    # Use separate startup log to avoid double-logging conflicts
    nohup "$SCRIPT_DIR/$(basename "$0")" --internal </dev/null >daemon.startup.log 2>&1 &
    local daemon_pid=$!
    disown $daemon_pid 2>/dev/null || true
    
    # Wait a moment to see if it starts successfully
    sleep 2
    
    if ps -p $daemon_pid > /dev/null 2>&1; then
        success "Daemon started! (PID: $daemon_pid)"
        
        # Check startup log for immediate errors
        if [ -f "daemon.startup.log" ] && grep -qi "error\|failed\|traceback" daemon.startup.log; then
            warning "Startup log contains errors - check daemon.startup.log"
        fi
        
        show_stats
    else
        error "Daemon failed to start. Check logs for details."
        echo ""
        echo "=== Startup Log ==="
        [ -f "daemon.startup.log" ] && tail -20 "daemon.startup.log" || echo "(No startup log found)"
        echo ""
        echo "=== Main Log ==="
        [ -f "$LOG_FILE" ] && tail -20 "$LOG_FILE" || echo "(No main log found)"
        exit 1
    fi
    
    exit 0
fi

# Run in foreground
info "Running in foreground mode (Ctrl+C to stop)"
info "For background mode, use: $0 --background"
echo ""

acquire_lock
rotate_log
run_daemon
