@echo off
setlocal enabledelayedexpansion

REM Humble Steam Key Redeemer - Windows Launcher
REM Version 1.1.0

REM Parse arguments
set "REINSTALL="
set "SHOW_HELP="
set "SHOW_VERSION="
set "CHECK_UPDATES="
set "SCRIPT_ARGS="

:parse_args
if "%1"=="" goto :args_done
if /i "%1"=="--help" set SHOW_HELP=1
if /i "%1"=="-h" set SHOW_HELP=1
if /i "%1"=="--version" set SHOW_VERSION=1
if /i "%1"=="-v" set SHOW_VERSION=1
if /i "%1"=="--reinstall" set REINSTALL=1
if /i "%1"=="--check-updates" set CHECK_UPDATES=1

REM Pass through other arguments to Python script
if "%1" neq "--reinstall" if "%1" neq "--check-updates" (
    if "%1" neq "--help" if "%1" neq "-h" (
        if "%1" neq "--version" if "%1" neq "-v" (
            set "SCRIPT_ARGS=!SCRIPT_ARGS! %1"
        )
    )
)

shift
goto :parse_args

:args_done

REM Show help
if defined SHOW_HELP (
    echo Humble Steam Key Redeemer - Windows Launcher
    echo.
    echo Usage: %~nx0 [options] [script options]
    echo.
    echo Launcher Options:
    echo   -h, --help          Show this help message
    echo   -v, --version      Show version information
    echo   --reinstall        Force reinstall of dependencies
    echo   --check-updates    Check for dependency updates
    echo.
    echo Script Options:
    echo   All other arguments are passed to humblesteamkeysredeemer.py
    echo.
    echo Examples:
    echo   %~nx0                    # Run interactively
    echo   %~nx0 --auto             # Run in automatic mode
    echo   %~nx0 --reinstall       # Reinstall dependencies first
    echo.
    exit /b 0
)

REM Show version
if defined SHOW_VERSION (
    echo Humble Steam Key Redeemer - Windows Launcher v1.1.0
    exit /b 0
)

REM Color codes for Windows 10+ (ANSI escape sequences)
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "CYAN=[96m"
set "RESET=[0m"

REM Configuration
set "VENV_DIR=venv"
set "REQUIREMENTS=requirements.txt"
set "SCRIPT=humblesteamkeysredeemer.py"
set "VENV_MARKER=%VENV_DIR%\.dependencies_installed"

echo.
echo ========================================
echo Humble Steam Key Redeemer - Launcher
echo ========================================
echo.

REM Check if Python launcher exists
where py >nul 2>&1
if errorlevel 1 (
    echo %RED%ERROR:%RESET% Python launcher 'py' not found
    echo Please install Python 3 from https://www.python.org/
    echo Make sure to check "Add Python to PATH" during installation
    goto :error
)

REM Check if Python 3 is available
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo %RED%ERROR:%RESET% Python 3 not found
    echo Please install Python 3 from https://www.python.org/
    goto :error
)

REM Display Python version
for /f "tokens=*" %%i in ('py -3 --version') do set PYTHON_VERSION=%%i
echo %CYAN%[INFO]%RESET% Using !PYTHON_VERSION!

REM Validate required files
if not exist "%REQUIREMENTS%" (
    echo %RED%ERROR:%RESET% %REQUIREMENTS% not found
    goto :error
)

if not exist "%SCRIPT%" (
    echo %RED%ERROR:%RESET% %SCRIPT% not found
    goto :error
)

REM Create virtual environment if needed
if not exist "%VENV_DIR%" (
    echo %CYAN%[INFO]%RESET% Creating virtual environment...
    py -3 -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo %RED%ERROR:%RESET% Failed to create virtual environment
        goto :error
    )
    echo %GREEN%[SUCCESS]%RESET% Virtual environment created
)

REM Activate virtual environment
echo %CYAN%[INFO]%RESET% Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo %RED%ERROR:%RESET% Failed to activate virtual environment
    goto :error
)

REM Handle dependencies
if defined REINSTALL (
    echo %CYAN%[INFO]%RESET% Reinstalling dependencies...
    del "%VENV_MARKER%" >nul 2>&1
    pip install --quiet --upgrade pip
    if errorlevel 1 (
        echo %RED%ERROR:%RESET% Failed to upgrade pip
        goto :error
    )
    pip install --force-reinstall -r "%REQUIREMENTS%"
    if errorlevel 1 (
        echo %RED%ERROR:%RESET% Failed to reinstall dependencies
        goto :error
    )
    echo. > "%VENV_MARKER%"
    echo %GREEN%[SUCCESS]%RESET% Dependencies reinstalled
) else if defined CHECK_UPDATES (
    echo %CYAN%[INFO]%RESET% Checking for dependency updates...
    pip list --outdated
    if errorlevel 1 (
        echo %YELLOW%[WARNING]%RESET% Failed to check for updates
    )
) else if not exist "%VENV_MARKER%" (
    echo %CYAN%[INFO]%RESET% Installing dependencies...
    pip install --quiet --upgrade pip
    if errorlevel 1 (
        echo %RED%ERROR:%RESET% Failed to upgrade pip
        goto :error
    )
    pip install -r "%REQUIREMENTS%"
    if errorlevel 1 (
        echo %RED%ERROR:%RESET% Failed to install dependencies
        goto :error
    )
    echo. > "%VENV_MARKER%"
    echo %GREEN%[SUCCESS]%RESET% Dependencies installed
) else (
    echo %CYAN%[INFO]%RESET% Dependencies OK
)

REM Run the script with any remaining arguments
echo.
echo ========================================
echo Running Humble Steam Key Redeemer
echo ========================================
echo.

python "%SCRIPT%" %SCRIPT_ARGS%
set EXIT_CODE=%errorlevel%

echo.
echo ========================================
if %EXIT_CODE% equ 0 (
    echo %GREEN%[SUCCESS]%RESET% Script completed successfully
) else (
    echo %YELLOW%[WARNING]%RESET% Script exited with code %EXIT_CODE%
)
echo ========================================
echo.

pause
exit /b %EXIT_CODE%

:error
echo.
echo ========================================
echo %RED%[ERROR]%RESET% Execution failed
echo ========================================
echo.
pause
exit /b 1
