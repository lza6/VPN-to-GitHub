@echo off
chcp 65001 >nul
title GitHub Auto Uploader - Launcher
echo ==========================================
echo    GitHub Auto Uploader - Start Script
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [1/7] Checking Python environment...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not detected, please install Python 3.8 or higher
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYTHON_VERSION=%%a
echo [OK] Python detected: %PYTHON_VERSION%
echo.

echo [2/7] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment already exists
)
echo.

echo [3/7] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment
    pause
    exit /b 1
)
echo [OK] Virtual environment activated
echo.

echo [4/7] Installing/updating dependencies...
python -m pip install --upgrade pip -q
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

echo [5/7] Checking GitHub CLI...
gh --version >nul 2>&1
if errorlevel 1 (
    echo [!] GitHub CLI not installed, attempting to install...
    echo.
    
    where winget >nul 2>&1
    if %errorlevel% == 0 (
        echo Installing GitHub CLI using winget...
        winget install --id GitHub.cli --accept-source-agreements --accept-package-agreements
        if errorlevel 1 (
            echo [WARNING] winget installation failed, trying manual download...
            goto manual_install
        )
    ) else (
        :manual_install
        echo Downloading GitHub CLI...
        set "GH_CLI_URL=https://github.com/cli/cli/releases/download/v2.63.2/gh_2.63.2_windows_amd64.msi"
        set "GH_CLI_INSTALLER=%TEMP%\gh_cli_installer.msi"
        
        powershell -Command "Invoke-WebRequest -Uri '%GH_CLI_URL%' -OutFile '%GH_CLI_INSTALLER%' -UseBasicParsing" 2>nul
        
        if exist "%GH_CLI_INSTALLER%" (
            echo Download complete, installing...
            msiexec /i "%GH_CLI_INSTALLER%" /qn /norestart
            del "%GH_CLI_INSTALLER%"
            echo [OK] GitHub CLI installed
        ) else (
            echo [ERROR] Download failed, please install GitHub CLI manually
            echo Download: https://cli.github.com/
            start https://cli.github.com/
            pause
            exit /b 1
        )
    )
    
    echo Please run this script again to complete setup
    pause
    exit /b 0
) else (
    for /f "tokens=3" %%a in ('gh --version 2^>^&1 ^| findstr "gh version"') do echo [OK] GitHub CLI installed: %%a
)
echo.

echo [6/7] Detecting system proxy...
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable | find "0x1" >nul 2>&1
if %errorlevel% == 0 (
    for /f "tokens=3" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set PROXY_SERVER=%%a
    if defined PROXY_SERVER (
        if not "%PROXY_SERVER%"=="" (
            echo [OK] System proxy detected: %PROXY_SERVER%
            set HTTP_PROXY=http://%PROXY_SERVER%
            set HTTPS_PROXY=http://%PROXY_SERVER%
            echo [OK] Proxy environment variables configured
            echo [INFO] HTTP_PROXY=%HTTP_PROXY%
            echo [INFO] HTTPS_PROXY=%HTTPS_PROXY%
        ) else (
            echo [WARNING] Proxy enabled but server address is empty
            echo [INFO] Using default proxy: 127.0.0.1:10808
            set HTTP_PROXY=http://127.0.0.1:10808
            set HTTPS_PROXY=http://127.0.0.1:10808
        )
    ) else (
        echo [WARNING] Proxy enabled but server address not found
        echo [INFO] Using default proxy: 127.0.0.1:10808
        set HTTP_PROXY=http://127.0.0.1:10808
        set HTTPS_PROXY=http://127.0.0.1:10808
    )
) else (
    echo [OK] No system proxy detected, using direct connection
)
echo.

echo [7/7] Starting application...
echo ==========================================
echo.
python main.py
set EXIT_CODE=%errorlevel%
echo.
if %EXIT_CODE% neq 0 (
    echo [ERROR] Application exited abnormally, error code: %EXIT_CODE%
)
echo.
echo Press any key to close window...
pause >nul
deactivate