@echo off
setlocal
echo ======================================================================
echo   DaVinci Resolve to After Effects Exporter - One-Click Installer
echo ======================================================================
echo.

set "SCRIPT_NAME=ae_export.py"
set "SRC=%~dp0ae_export.py"
if not exist "%SRC%" set "SRC=%~dp0dist\ae_export.py"

if not exist "%SRC%" (
    echo [ERROR] %SCRIPT_NAME% was not found!
    echo Please make sure ae_export.py is in the same folder as this installer.
    echo.
    pause
    exit /b 1
)

set "RESOLVE_DIR=%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"

if not exist "%RESOLVE_DIR%" (
    echo Creating DaVinci Resolve scripts directory:
    echo   "%RESOLVE_DIR%"
    mkdir "%RESOLVE_DIR%"
)

copy /y "%SRC%" "%RESOLVE_DIR%\%SCRIPT_NAME%" >nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Plugin installed successfully!
    echo.
    echo Installed to:
    echo   %RESOLVE_DIR%\%SCRIPT_NAME%
    echo.
    echo How to use:
    echo   1. Open DaVinci Resolve
    echo   2. Mark clips on your timeline with Orange color
    echo   3. Click: Workspace -^> Scripts -^> Utility -^> ae_export
    echo   4. After Effects will open automatically with your comp!
    echo.
) else (
    echo [ERROR] Failed to copy %SCRIPT_NAME% to %RESOLVE_DIR%
)

pause
