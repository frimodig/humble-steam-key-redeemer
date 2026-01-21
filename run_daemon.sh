#!/bin/bash
# Humble Steam Key Redeemer Daemon
# Automatically restarts the script if it crashes/times out

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="daemon.log"
MAX_RETRIES=100  # Max restarts before giving up
RETRY_DELAY=30   # Seconds to wait between restarts

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Humble Steam Key Redeemer Daemon"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -h, --help        Show this help message"
    echo "  -b, --background  Run in background (detached from terminal)"
    echo "  -s, --stats       Show current statistics and exit"
    echo "  --internal        (Internal use only)"
    echo ""
    echo "IMPORTANT: Run the script manually FIRST to log in:"
    echo "  python3 humblesteamkeysredeemer.py"
    echo ""
    echo "Once logged in, run the daemon:"
    echo "  ./run_daemon.sh"
    echo ""
    echo "To run in background (survives terminal close):"
    echo "  ./run_daemon.sh --background"
    echo ""
    echo "To check progress:"
    echo "  ./run_daemon.sh --stats"
    echo ""
    echo "To stop the daemon:"
    echo "  pkill -f 'humblesteamkeysredeemer.py'"
    echo ""
    echo "To monitor logs:"
    echo "  tail -f daemon.log"
    exit 0
}

# Count lines in a file (0 if doesn't exist)
count_file() {
    if [ -f "$1" ]; then
        # Count non-empty lines
        grep -c . "$1" 2>/dev/null || echo "0"
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

# Check for existing sessions
check_sessions() {
    local missing=false
    
    if [ ! -f ".humblecookies" ]; then
        echo "WARNING: No Humble session found (.humblecookies missing)"
        missing=true
    fi
    
    if [ ! -f ".steamcookies" ]; then
        echo "WARNING: No Steam session found (.steamcookies missing)"
        missing=true
    fi
    
    if [ "$missing" = true ]; then
        echo ""
        echo "Please run the script manually first to establish sessions:"
        echo "  python3 humblesteamkeysredeemer.py"
        echo ""
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

run_daemon() {
    echo "========================================" | tee -a "$LOG_FILE"
    echo "Humble Redeemer Daemon Started: $(date)" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    
    # Record starting stats
    local start_redeemed=$(count_file "redeemed.csv")
    local start_time=$(date +%s)

    retry_count=0

    while [ $retry_count -lt $MAX_RETRIES ]; do
        echo "" | tee -a "$LOG_FILE"
        echo "[$(date)] Starting redeemer (attempt $((retry_count + 1))/$MAX_RETRIES)..." | tee -a "$LOG_FILE"
        
        # Run the script in auto mode
        python3 humblesteamkeysredeemer.py --auto 2>&1 | tee -a "$LOG_FILE"
        exit_code=${PIPESTATUS[0]}
        
        echo "" | tee -a "$LOG_FILE"
        echo "[$(date)] Script exited with code: $exit_code" | tee -a "$LOG_FILE"
        
        # Show session stats
        local current_redeemed=$(count_file "redeemed.csv")
        local session_redeemed=$((current_redeemed - start_redeemed))
        echo "[$(date)] Session progress: +$session_redeemed redeemed this session" | tee -a "$LOG_FILE"
        
        # Check exit codes
        case $exit_code in
            0)
                echo "" | tee -a "$LOG_FILE"
                echo "[$(date)] ✓ Script completed successfully! All keys processed." | tee -a "$LOG_FILE"
                break
                ;;
            130)
                echo "[$(date)] Script stopped by user (Ctrl+C)" | tee -a "$LOG_FILE"
                break
                ;;
            2)
                # Stale cookies - DO NOT RETRY, need manual intervention
                echo "" | tee -a "$LOG_FILE"
                echo "[$(date)] ✗ STALE COOKIES - Manual login required!" | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                echo "The login session has expired. To fix:" | tee -a "$LOG_FILE"
                echo "  1. Run: python3 humblesteamkeysredeemer.py" | tee -a "$LOG_FILE"
                echo "  2. Complete the login process" | tee -a "$LOG_FILE"
                echo "  3. Restart the daemon: ./run_daemon.sh" | tee -a "$LOG_FILE"
                echo "" | tee -a "$LOG_FILE"
                break
                ;;
            *)
                # Other error - retry after delay
                retry_count=$((retry_count + 1))
                if [ $retry_count -lt $MAX_RETRIES ]; then
                    echo "[$(date)] Unexpected exit (code $exit_code). Restarting in ${RETRY_DELAY}s..." | tee -a "$LOG_FILE"
                    sleep $RETRY_DELAY
                fi
                ;;
        esac
    done

    if [ $retry_count -ge $MAX_RETRIES ]; then
        echo "[$(date)] Max retries ($MAX_RETRIES) reached. Giving up." | tee -a "$LOG_FILE"
    fi

    # Final statistics
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    local hours=$((duration / 3600))
    local minutes=$(((duration % 3600) / 60))
    local seconds=$((duration % 60))
    
    local final_redeemed=$(count_file "redeemed.csv")
    local total_session_redeemed=$((final_redeemed - start_redeemed))
    
    echo "" | tee -a "$LOG_FILE"
    echo "╔═══════════════════════════════════════╗" | tee -a "$LOG_FILE"
    echo "║         SESSION SUMMARY               ║" | tee -a "$LOG_FILE"
    echo "╠═══════════════════════════════════════╣" | tee -a "$LOG_FILE"
    printf "║  Duration:  %02d:%02d:%02d                  ║\n" "$hours" "$minutes" "$seconds" | tee -a "$LOG_FILE"
    printf "║  Redeemed:  +%-5d (this session)     ║\n" "$total_session_redeemed" | tee -a "$LOG_FILE"
    echo "╚═══════════════════════════════════════╝" | tee -a "$LOG_FILE"
    
    # Show full stats to terminal (with colors)
    show_stats
    # Log plain version
    show_stats_plain >> "$LOG_FILE"
    
    echo "" | tee -a "$LOG_FILE"
    echo "[$(date)] Daemon stopped." | tee -a "$LOG_FILE"
}

# Parse arguments
BACKGROUND=false
INTERNAL=false
SHOW_STATS=false

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
        --internal)
            INTERNAL=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Stats mode - just show stats and exit
if [ "$SHOW_STATS" = true ]; then
    show_stats
    exit 0
fi

# Internal mode - just run the daemon (used by background mode)
if [ "$INTERNAL" = true ]; then
    run_daemon
    exit 0
fi

# Main
check_sessions

if [ "$BACKGROUND" = true ]; then
    echo "Starting daemon in background..."
    echo "Logs will be written to: $SCRIPT_DIR/$LOG_FILE"
    echo "To monitor: tail -f $LOG_FILE"
    echo "To check stats: ./run_daemon.sh --stats"
    echo "To stop: pkill -f 'humblesteamkeysredeemer.py'"
    
    # Start in background using nohup
    nohup "$SCRIPT_DIR/run_daemon.sh" --internal > /dev/null 2>&1 &
    disown
    
    echo "Daemon started!"
    show_stats
    exit 0
fi

# Run in foreground
run_daemon
