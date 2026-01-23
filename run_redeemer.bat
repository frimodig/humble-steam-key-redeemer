@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Humble Steam Key Redeemer - Windows Launcher
REM ============================================================================
set "VERSION=1.2.0"

REM ============================================================================
REM Configuration
REM ============================================================================
set "VENV_DIR=venv"
set "REQUIREMENTS=requirements.txt"
set "SCRIPT=humblesteamkeysredeemer.py"
set "VENV_MARKER=%VENV_DIR%\.dependencies_installed"

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
    set "RESET="
) else (
    REM Colors work, set them up
    set "RED=[91m"
    set "GREEN=[92m"
    set "YELLOW=[93m"
    set "CYAN=[96m"
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

REM All other arguments go to the Python script (preserve quotes)
set "SCRIPT_ARGS=!SCRIPT_ARGS! %1"
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
    echo   %~nx0 --reinstall         # Reinstall dependencies first
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

REM Check if Python launcher exists
where py >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Python launcher 'py' not found
    echo.
    echo Please install Python 3 from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation
    goto :error
)

REM Check if Python 3 is available
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR]%RESET% Python 3 not found
    echo.
    echo Please install Python 3 from https://www.python.org/
    goto :error
)

REM Display Python version
for /f "tokens=*" %%i in ('py -3 --version 2^>^&1') do set "PYTHON_VERSION=%%i"
echo %CYAN%[INFO]%RESET% Using !PYTHON_VERSION!

REM Check disk space (warn if less than 100MB free)
for /f "tokens=3" %%a in ('dir /-c ^| findstr /C:"bytes free"') do set "FREE_SPACE=%%a"
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
    goto :error
)

if not exist "%SCRIPT%" (
    echo %RED%[ERROR]%RESET% %SCRIPT% not found in current directory
    echo.
    echo Current directory: %CD%
    goto :error
)

REM Check if venv exists and is valid
if exist "%VENV_DIR%" (
    if not exist "%VENV_DIR%\Scripts\python.exe" (
        echo %YELLOW%[WARNING]%RESET% Incomplete virtual environment detected
        echo %CYAN%[INFO]%RESET% Recreating virtual environment...
        rmdir /s /q "%VENV_DIR%" 2>nul
        if errorlevel 1 (
            echo %RED%[ERROR]%RESET% Failed to remove corrupted venv
            echo Try closing any programs using files in the venv directory
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

python "%SCRIPT%"%SCRIPT_ARGS%
set "EXIT_CODE=%errorlevel%"

echo.
echo ════════════════════════════════════════
if %EXIT_CODE% equ 0 (
    echo %GREEN%[SUCCESS]%RESET% Script completed successfully
) else if %EXIT_CODE% equ 2 (
    echo %YELLOW%[WARNING]%RESET% Script exited with code 2 - Stale cookies
    echo.
    echo The login session has expired. Please:
    echo   1. Run this script again without --auto flag
    echo   2. Complete the login process
    echo   3. Resume with --auto flag if desired
) else (
    echo %YELLOW%[WARNING]%RESET% Script exited with code %EXIT_CODE%
)
echo ════════════════════════════════════════
echo.

pause
exit /b %EXIT_CODE%

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
pause
exit /b 1
