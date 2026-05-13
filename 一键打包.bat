@echo off
title 一键打包 OCR 工具
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

:: Ensure PyInstaller is installed
%PY% -c "import pyinstaller" >nul 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing PyInstaller...
    %PY% -m pip install pyinstaller -q
)

echo [INFO] Building exe, please wait (2-5 minutes)...
echo.
%PY% "%SCRIPT_DIR%build_exe.py"

echo.
echo Build finished. Output: dist\OCR识别操作工具.exe
echo Release folder (for distribution): release\
pause
