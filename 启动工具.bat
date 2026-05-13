@echo off
title OCR 识别操作工具
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Step 1: scan known Python install paths
set "PY="
for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%ProgramFiles%\Python311"
    "%ProgramFiles%\Python312"
    "%ProgramFiles%\Python313"
    "C:\Python311"
    "C:\Python312"
) do (
    if exist "%%~d\python.exe" (
        set "PATH=%%~d;%%~d\Scripts;%PATH%"
        set "PY=%%~d\python.exe"
        goto :has_python
    )
)

:: Step 2: try py launcher
py --version >nul 2>nul
if %errorlevel% equ 0 (
    set "PY=py"
    goto :has_python
)

:: Step 3: try python from PATH (skip WindowsApps stubs)
for /f "tokens=*" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if %errorlevel% neq 0 (
        python -c "exit(0)" >nul 2>nul
        if %errorlevel% equ 0 (
            set "PY=python"
            goto :has_python
        )
    )
)

echo [ERROR] Python not found.
echo Please install Python 3.9+ from https://www.python.org/downloads/
echo During installation, check "Add Python to PATH"
echo.
pause
exit /b 1

:has_python
echo [INFO] Python: %PY%
echo.

:: Check dependencies
%PY% -c "import cv2, pyautogui, PIL" >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing dependencies, please wait...
    %PY% -m pip install -r "%SCRIPT_DIR%requirements.txt" -q
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        echo Please run manually: pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo [INFO] Dependencies installed.
    echo.
)

echo [INFO] Starting OCR Tool...
%PY% "%SCRIPT_DIR%main.py"
pause
