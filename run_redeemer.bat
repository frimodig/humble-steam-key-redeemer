@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Humble Steam Key Redeemer - Windows Launcher
REM ============================================================================
set "VERSION=1.3.0"

REM ============================================================================
REM Configuration
REM ============================================================================
set "VENV_DIR=venv"
set "REQUIREMENTS=requirements.txt"
set "SCRIPT=humblesteamkeysredeemer.py"
set "VENV_MARKER=%VENV_DIR%\.dependencies_installed"
set "LOCK_FILE=.run.lock"

REM Cookie files
set "HUMBLE_COOKIES=.humblecookies"
set "STEAM_COOKIES=.steamcookies"

REM CSV output files
set "REDEEMED_CSV=redeemed.csv"
set "ERRORED_CSV=errored.csv"
set "EXPIRED_CSV=expired.csv"
set "ALREADY_OWNED_CSV=already_owned.csv"
set "LOG_FILE=daemon.log"

REM ============================================================================
REM Enable ANSI colors (Windows 10+)
REM ============================================================================
REM Try to enable ANSI color support
reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1

REM Test if colors work
echo|set /p="[31m" 2>nul | findstr /r "\[31m" >nul 2>&1
if errorlevel 1 (
    REM Colors don't work, disable them
    set "RED="
    set "GREEN="
    set "YELLOW="
    set "CYAN="
    set "BLUE="
    set "RESET="
) else (
    REM Colors work, set them up
    set "RED=[91m"
    set "GREEN=[92m"
    set "YELLOW=[93m"
    set "CYAN=[96m"
    set "BLUE=[94m"
    set "RESET=[0m"
)

REM ============================================================================
REM Parse Command Line Arguments
REM ============================================================================
set "REINSTALL="
set "SHOW_HELP="
set "SHOW_VERSION="
set "CHECK_UPDATES="
set "CLEAN="
set "SHOW_STATS="
set "SHOW_LOG="
set "LOG_LINES=50"
set "SCRIPT_ARGS="

:parse_args
if "%~1"=="" goto :args_done

REM Launcher-specific arguments (these are consumed)
if /i "%~1"=="--help" (set SHOW_HELP=1) & shift & goto :parse_args
if /i "%~1"=="-h" (set SHOW_HELP=1) & shift & goto :parse_args
if /i "%~1"=="--version" (set SHOW_VERSION=1) & shift & goto :parse_args
if /i "%~1"=="-v" (set SHOW_VERSION=1) & shift & goto :parse_args
if /i "%~1"=="--reinstall" (set REINSTALL=1) & shift & goto :parse_args
if /i "%~1"=="--check-updates" (set CHECK_UPDATES=1) & shift & goto :parse_args
if /i "%~1"=="--clean" (set CLEAN=1) & shift & goto :parse_args
if /i "%~1"=="--stats" (set SHOW_STATS=1) & shift & goto :parse_args
if /i "%~1"=="-s" (set SHOW_STATS=1) & shift & goto :parse_args

if /i "%~1"=="--log" (
    set SHOW_LOG=1
    if "%~2" neq "" (
        set /a TEST_LINES=%~2 2>nul
        if !TEST_LINES! GTR 0 if !TEST_LINES! LEQ 10000 (
            set LOG_LINES=%~2
            shift
        )
    )
    shift
    goto :parse_args
)
if /i "%~1"=="-l" (
    set SHOW_LOG=1
    if "%~2" neq "" (
        set /a TEST_LINES=%~2 2>nul
        if !TEST_LINES! GTR 0 if !TEST_LINES! LEQ 10000 (
            set LOG_LINES=%~2
            shift
        )
    )
    shift
    goto :parse_args
)

REM All other arguments go to the Python script (preserve quotes)
if "!SCRIPT_ARGS!"=="" (
    set "SCRIPT_ARGS=%1"
) else (
    set "SCRIPT_ARGS=!SCRIPT_ARGS! %1"
)
shift
goto :parse_args

:args_done

REM ============================================================================
REM Handle Special Flags
REM ============================================================================

REM Show help
if defined SHOW_HELP (
    echo.
    echo Humble Steam Key Redeemer - Windows Launcher v%VERSION%
    echo.
    echo Usage: %~nx0 [launcher-options] [script-options]
    echo.
    echo Launcher Options:
    echo   -h, --help          Show this help message
    echo   -v, --version       Show version information
    echo   -s, --stats         Show statistics from CSV files
    echo   -l, --log [N]       Show last N log entries (default: 50)
    echo   --reinstall         Force reinstall of dependencies
    echo   --check-updates     Check for dependency updates
    echo   --clean             Remove virtual environment
    echo.
    echo Script Options:
    echo   All other arguments are passed to %SCRIPT%
    echo.
    echo Examples:
    echo   %~nx0                     # Run interactively
    echo   %~nx0 --auto              # Run in automatic mode
    echo   %~nx0 --stats             # Show statistics
    echo   %~nx0 --log 100           # Show last 100 log lines
    echo   %~nx0 --reinstall         # Reinstall dependencies
    echo   %~nx0 --clean             # Clean virtual environment
    echo.
    echo Note: ANSI colors require Windows 10 build 10586 or later
    echo.
    exit /b 0
)

REM Show version
if defined SHOW_VERSION (
    echo Humble Steam Key Redeemer - Windows Launcher v%VERSION%
    exit /b 0
)

REM Show statistics
if defined SHOW_STATS (
    call :show_statistics
    pause
    exit /b 0
)

REM Show log
if defined SHOW_LOG (
    call :show_log %LOG_LINES%
    pause
    exit /b 0
)

REM Clean environment
if defined CLEAN (
    if exist "%VENV_DIR%" (
        echo %YELLOW%[WARNING]%RESET% This will delete the virtual environment
        set /p "CONFIRM=Are you sure? (y/N): "
        if /i "!CONFIRM!"=="y" (
            echo %CYAN%[INFO]%RESET% Removing virtual environment...
            rmdir /s /q "%VENV_DIR%" 2>nul
            if errorlevel 1 (
                echo %RED%[ERROR]%RESET% Failed to remove virtual environment
                echo Try closing any programs using files in the venv directory
                pause
                exit /b 1
            )
            echo %GREEN%[SUCCESS]%RESET% Virtual environment removed
        ) else (
            echo Cancelled
        )
    ) else (
        echo %CYAN%[INFO]%RESET% Virtual environment does not exist
    )
    pause
    exit /b 0
)

REM ============================================================================
REM Main Execution
REM ============================================================================

echo.
echo ╔════════════════════════════════════════╗
echo ║  Humble Steam Key Redeemer - Launcher  ║
echo ║              v%VERSION%                    ║
echo ╚════════════════════════════════════════╝
echo.

REM Check for already running instance
call :check_already_running

REM Check if Python launcher exists
where py >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Python launcher 'py' not found
    echo.
    echo Please install Python 3 from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation
    call :cleanup
    goto :error
)

REM Check if Python 3 is available
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Python 3 not found
    echo.
    echo Please install Python 3 from https://www.python.org/
    call :cleanup
    goto :error
)

REM Display Python version
for /f "tokens=*" %%i in ('py -3 --version 2^>^&1') do set "PYTHON_VERSION=%%i"
echo %CYAN%[INFO]%RESET% Using !PYTHON_VERSION!

REM Check disk space (warn if less than 100MB free)
for /f "tokens=3" %%a in ('dir /-c 2^>nul ^| findstr /C:"bytes free"') do set "FREE_SPACE=%%a"
if defined FREE_SPACE (
    if !FREE_SPACE! LSS 100000000 (
        echo %YELLOW%[WARNING]%RESET% Low disk space: !FREE_SPACE! bytes free
    )
)

REM Validate required files
if not exist "%REQUIREMENTS%" (
    echo %RED%[ERROR]%RESET% %REQUIREMENTS% not found in current directory
    echo.
    echo Current directory: %CD%
    call :cleanup
    goto :error
)

if not exist "%SCRIPT%" (
    echo %RED%[ERROR]%RESET% %SCRIPT% not found in current directory
    echo.
    echo Current directory: %CD%
    call :cleanup
    goto :error
)

REM Check cookie ages
call :check_cookie_age

REM Check if venv exists and is valid
if exist "%VENV_DIR%" (
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        echo %YELLOW%[WARNING]%RESET% Incomplete virtual environment detected
        echo %CYAN%[INFO]%RESET% Recreating virtual environment...
        rmdir /s /q "%VENV_DIR%" 2>nul
        if errorlevel 1 (
            echo %RED%[ERROR]%RESET% Failed to remove corrupted venv
            echo Try closing any programs using files in the venv directory
            call :cleanup
            goto :error
        )
    )
)

REM Create virtual environment if needed
if not exist "%VENV_DIR%" (
    echo %CYAN%[INFO]%RESET% Creating virtual environment...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo %RED%[ERROR]%RESET% Failed to create virtual environment
        echo.
        echo Possible causes:
        echo   - Insufficient disk space
        echo   - Permission denied
        echo   - Python venv module not installed
        call :cleanup
        goto :error
    )
    echo %GREEN%[SUCCESS]%RESET% Virtual environment created
)

REM Activate virtual environment
echo %CYAN%[INFO]%RESET% Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Failed to activate virtual environment
    echo.
    echo Try running with --clean to recreate the environment
    call :cleanup
    goto :error
)

REM ============================================================================
REM Dependency Management
REM ============================================================================

if defined REINSTALL (
    REM Force reinstall all dependencies
    echo %CYAN%[INFO]%RESET% Reinstalling dependencies...
    del "%VENV_MARKER%" >nul 2>&1
    
    echo %CYAN%[INFO]%RESET% Upgrading pip...
    python -m pip install --upgrade pip
    if errorlevel 1 (
        echo %YELLOW%[WARNING]%RESET% Failed to upgrade pip, continuing with current version...
    )
    
    echo %CYAN%[INFO]%RESET% Installing requirements...
    pip install --force-reinstall -r "%REQUIREMENTS%"
    if errorlevel 1 (
        echo %RED%[ERROR]%RESET% Failed to reinstall dependencies
        echo.
        echo Check the error messages above for details
        call :cleanup
        goto :error
    )
    
    REM Create marker file
    echo. > "%VENV_MARKER%"
    echo %GREEN%[SUCCESS]%RESET% Dependencies reinstalled successfully
    echo.
    
) else if defined CHECK_UPDATES (
    REM Check for outdated packages
    echo %CYAN%[INFO]%RESET% Checking for dependency updates...
    echo.
    pip list --outdated
    if errorlevel 1 (
        echo %YELLOW%[WARNING]%RESET% Failed to check for updates
    )
    echo.
    echo Use --reinstall to update dependencies
    echo.
    call :cleanup
    pause
    exit /b 0
    
) else if not exist "%VENV_MARKER%" (
    REM First-time setup or marker deleted
    echo %CYAN%[INFO]%RESET% Installing dependencies...
    
    echo %CYAN%[INFO]%RESET% Upgrading pip...
    python -m pip install --upgrade pip
    if errorlevel 1 (
        echo %YELLOW%[WARNING]%RESET% Failed to upgrade pip, continuing with current version...
    )
    
    echo %CYAN%[INFO]%RESET% Installing requirements...
    pip install -r "%REQUIREMENTS%"
    if errorlevel 1 (
        echo %RED%[ERROR]%RESET% Failed to install dependencies
        echo.
        echo Check the error messages above for details
        call :cleanup
        goto :error
    )
    
    REM Create marker file
    echo. > "%VENV_MARKER%"
    echo %GREEN%[SUCCESS]%RESET% Dependencies installed successfully
    echo.
    
) else (
    REM Dependencies already installed
    echo %CYAN%[INFO]%RESET% Dependencies already installed
    echo.
)

REM ============================================================================
REM Run Python Script
REM ============================================================================

echo ════════════════════════════════════════
echo Running Humble Steam Key Redeemer
echo ════════════════════════════════════════
echo.

python "%SCRIPT%" %SCRIPT_ARGS%
set "EXIT_CODE=%errorlevel%"

echo.
echo ════════════════════════════════════════

REM Enhanced exit code handling
if %EXIT_CODE% equ 0 (
    echo %GREEN%[SUCCESS]%RESET% Script completed successfully
    call :show_statistics_inline
    
) else if %EXIT_CODE% equ 2 (
    echo %YELLOW%[WARNING]%RESET% Stale Cookies - Manual Login Required
    echo.
    echo The login session has expired. To fix:
    echo   1. Run: %~nx0 ^(without --auto^)
    echo   2. Complete the login process
    echo   3. Resume: %~nx0 --auto
    
) else if %EXIT_CODE% equ 124 (
    echo %YELLOW%[WARNING]%RESET% Script Timeout
    echo The script was terminated due to timeout
    echo Consider increasing timeout or running again
    
) else if %EXIT_CODE% equ 130 (
    echo %CYAN%[INFO]%RESET% User Interrupted
    echo Script stopped by user (Ctrl+C)
    
) else (
    echo %YELLOW%[WARNING]%RESET% Script exited with code %EXIT_CODE%
    echo Check the output above for details
)

echo ════════════════════════════════════════
echo.

call :cleanup
pause
exit /b %EXIT_CODE%

REM ============================================================================
REM Helper Functions
REM ============================================================================

:check_already_running
if exist "%LOCK_FILE%" (
    set /p LOCK_PID=<"%LOCK_FILE%" 2>nul
    if defined LOCK_PID (
        REM Check if process is still running
        tasklist /FI "PID eq !LOCK_PID!" 2>nul | find "!LOCK_PID!" >nul
        if not errorlevel 1 (
            echo %RED%[ERROR]%RESET% Script is already running (PID: !LOCK_PID!)
            echo.
            echo If you're sure it's not running, delete: %LOCK_FILE%
            pause
            exit /b 3
        ) else (
            REM Stale lock file
            echo %YELLOW%[WARNING]%RESET% Removing stale lock file
            del "%LOCK_FILE%" 2>nul
        )
    )
)

REM Create lock file with pseudo-PID (using random number)
set /a LOCK_PID=%RANDOM%*%RANDOM%
echo !LOCK_PID! > "%LOCK_FILE%"
goto :eof

:check_cookie_age
set "COOKIE_WARNING="

if exist "%HUMBLE_COOKIES%" (
    for %%F in ("%HUMBLE_COOKIES%") do (
        echo %CYAN%[INFO]%RESET% Humble cookies: %%~tF
    )
) else (
    echo %YELLOW%[WARNING]%RESET% No Humble session found (%HUMBLE_COOKIES% missing)
    echo Run without --auto to log in first
    set "COOKIE_WARNING=1"
)

if exist "%STEAM_COOKIES%" (
    for %%F in ("%STEAM_COOKIES%") do (
        echo %CYAN%[INFO]%RESET% Steam cookies: %%~tF
    )
) else (
    echo %YELLOW%[WARNING]%RESET% No Steam session found (%STEAM_COOKIES% missing)
    echo Run without --auto to log in first
    set "COOKIE_WARNING=1"
)

if defined COOKIE_WARNING (
    echo.
)
goto :eof

:show_log
set "LINES=%~1"
if not exist "%LOG_FILE%" (
    echo %YELLOW%[WARNING]%RESET% Log file not found: %LOG_FILE%
    goto :eof
)

echo.
echo ╔═══════════════════════════════════════╗
echo ║        RECENT LOG ENTRIES             ║
echo ╚═══════════════════════════════════════╝
echo.

REM Use PowerShell to get last N lines (more reliable than batch)
powershell -Command "if (Test-Path '%LOG_FILE%') { Get-Content -Path '%LOG_FILE%' -Tail %LINES% } else { Write-Host 'Log file not found' }" 2>nul
if errorlevel 1 (
    REM Fallback: use more command (if available)
    more +%LINES% "%LOG_FILE%" 2>nul
    if errorlevel 1 (
        echo %YELLOW%[WARNING]%RESET% Could not read log file
    )
)
echo.
goto :eof

:show_statistics
REM Count CSV files
call :count_csv_lines "%REDEEMED_CSV%" REDEEMED
call :count_csv_lines "%ERRORED_CSV%" ERRORED
call :count_csv_lines "%EXPIRED_CSV%" EXPIRED
call :count_csv_lines "%ALREADY_OWNED_CSV%" ALREADY_OWNED

set /a TOTAL=REDEEMED+ERRORED+EXPIRED+ALREADY_OWNED

echo.
echo ╔═══════════════════════════════════════╗
echo ║   HUMBLE KEY REDEEMER STATISTICS      ║
echo ╠═══════════════════════════════════════╣
echo ║  %GREEN%✓ Redeemed:%RESET%        !REDEEMED!
echo ║  %BLUE%○ Already Owned:%RESET%   !ALREADY_OWNED!
echo ║  %YELLOW%⚠ Expired:%RESET%         !EXPIRED!
echo ║  %RED%✗ Errored:%RESET%         !ERRORED!
echo ╠═══════════════════════════════════════╣
echo ║  Total Processed:  !TOTAL!
echo ╚═══════════════════════════════════════╝
echo.
goto :eof

:show_statistics_inline
REM Quick stats summary after successful run
call :count_csv_lines "%REDEEMED_CSV%" REDEEMED
call :count_csv_lines "%ALREADY_OWNED_CSV%" ALREADY_OWNED
set /a SESSION_TOTAL=REDEEMED+ALREADY_OWNED
echo.
echo Summary: !REDEEMED! redeemed, !ALREADY_OWNED! already owned
goto :eof

:count_csv_lines
REM %1 = filename, %2 = variable name to set
set "%~2=0"
if not exist "%~1" goto :eof

REM Count lines in file
for /f %%a in ('type "%~1" 2^>nul ^| find /c /v ""') do set "%~2=%%a"
REM Subtract header line if file has content
if !%~2! GTR 0 (
    set /a %~2=%~2-1
)
goto :eof

:cleanup
if exist "%LOCK_FILE%" del "%LOCK_FILE%" 2>nul
goto :eof

REM ============================================================================
REM Error Handler
REM ============================================================================
:error
echo.
echo ════════════════════════════════════════
echo %RED%[ERROR]%RESET% Execution failed
echo ════════════════════════════════════════
echo.
echo For help, run: %~nx0 --help
echo.
call :cleanup
pause
exit /b 1
