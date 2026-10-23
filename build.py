"""
Build script for DaVinci Resolve to After Effects Integration (v1.0.0)
---------------------------------------------------------------------
Assembles modular Python source files into:
1. `dist/ae_export.py`: Standalone, single-file script for DaVinci Resolve.
2. `dist/install.bat` and `dist/install.py`: Automated installers.
3. `dist/ResolveToAfterEffects-v1.0.0.zip`: Release archive.
"""

import os
import re
import shutil
import zipfile

VERSION = "1.0.0"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(ROOT_DIR, "dist")


def extract_body(file_path: str, start_marker: str) -> str:
    """Extract code from file starting from start_marker."""
    with open(file_path, "r", encoding="utf-8") as f:
        code = f.read()
    idx = code.find(start_marker)
    if idx == -1:
        raise ValueError(f"Marker '{start_marker}' not found in {file_path}")
    return code[idx:]


def build_standalone_script() -> str:
    """Combine all project files into a single zero-dependency script."""
    os.makedirs(DIST_DIR, exist_ok=True)
    out_file = os.path.join(DIST_DIR, "ae_export.py")

    header = f'''"""
DaVinci Resolve to Adobe After Effects Exporter (v{VERSION})
============================================================
Automated one-click pipeline to export marked clips, subtitles, transforms,
retime and timing from DaVinci Resolve into Adobe After Effects compositions.

Requirements:
  - DaVinci Resolve 18, 19, 20, 21+
  - Adobe After Effects CC / 2020 - 2026+
  - Windows or macOS

Installation:
  Run install.bat (Windows) or install.py (macOS/Linux)
  OR copy this file directly to DaVinci Resolve Scripts/Utility folder.

Usage:
  1. In DaVinci Resolve, mark target clip(s) with color (default: Orange).
  2. Click: Workspace -> Scripts -> Utility -> ae_export
  3. After Effects will open automatically with your comp!
"""

import argparse
import ctypes
from dataclasses import asdict, dataclass, field
from datetime import datetime
import glob
import json
import logging
import math
import os
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

__version__ = "{VERSION}"
logger = logging.getLogger("ResolveToAE")
'''

    # Extract bodies of all components
    config_code = extract_body(os.path.join(ROOT_DIR, "config.py"), "@dataclass\nclass SubtitleStyleConfig")
    model_code = extract_body(os.path.join(ROOT_DIR, "model.py"), "@dataclass\nclass TransformProperties")
    reader_code = extract_body(os.path.join(ROOT_DIR, "resolve_reader.py"), "def get_resolve_instance")
    jsx_code = extract_body(os.path.join(ROOT_DIR, "jsx_generator.py"), "class JSXGenerator")
    report_code = extract_body(os.path.join(ROOT_DIR, "report.py"), "@dataclass\nclass ReportSummary")
    timeline_code = extract_body(os.path.join(ROOT_DIR, "export_timeline.py"), "def find_after_effects_path")

    # Strip existing __main__ runner from export_timeline
    timeline_code = re.sub(r'if __name__ == "__main__":\s+main\(\)', '', timeline_code)

    footer = '''
# ============================================================================
# Resolve Script Menu & CLI Entry Points
# ============================================================================

def show_error_dialog(title: str, text: str):
    """Show native error message box only if an error occurs."""
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10 | 0x00010000 | 0x00040000)
            return
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            cmd = f'display dialog "{text}" with title "{title}" buttons {{"OK"}} default button "OK" with icon stop'
            subprocess.run(["osascript", "-e", cmd], capture_output=True)
            return
        except Exception:
            pass
    print(f"[ERROR] {title}: {text}")


def run_menu_export():
    """Silent execution from DaVinci Resolve Scripts menu."""
    try:
        resolve_obj = globals().get("resolve")
        if not resolve_obj:
            bmd = globals().get("bmd")
            if bmd and hasattr(bmd, "scriptapp"):
                resolve_obj = bmd.scriptapp("Resolve")
        run_pipeline(resolve_obj=resolve_obj)
    except Exception as e:
        err_details = traceback.format_exc()
        msg = f"An error occurred during export:\\n\\n{type(e).__name__}: {str(e)}\\n\\nDetails:\\n{err_details}"
        show_error_dialog("Resolve -> After Effects Export Error", msg)


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        main()
    else:
        run_menu_export()
else:
    run_menu_export()
'''

    full_code = f"{header}\n\n# --- Config ---\n{config_code}\n\n# --- Model ---\n{model_code}\n\n# --- Resolve Reader ---\n{reader_code}\n\n# --- JSX Generator ---\n{jsx_code}\n\n# --- Report Generator ---\n{report_code}\n\n# --- Pipeline Runner ---\n{timeline_code}\n\n{footer}"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(full_code)

    print(f"[+] Successfully built standalone script: {out_file}")
    return out_file


def create_installer_bat():
    bat_content = """@echo off
setlocal
echo ======================================================================
echo   DaVinci Resolve to After Effects Exporter - One-Click Installer
echo ======================================================================
echo.

set "SCRIPT_NAME=ae_export.py"
set "SRC=%~dp0ae_export.py"
if not exist "%SRC%" set "SRC=%~dp0dist\\ae_export.py"

if not exist "%SRC%" (
    echo [ERROR] %SCRIPT_NAME% was not found!
    echo Please make sure ae_export.py is in the same folder as this installer.
    echo.
    pause
    exit /b 1
)

set "RESOLVE_DIR=%APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility"

if not exist "%RESOLVE_DIR%" (
    echo Creating DaVinci Resolve scripts directory:
    echo   "%RESOLVE_DIR%"
    mkdir "%RESOLVE_DIR%"
)

copy /y "%SRC%" "%RESOLVE_DIR%\\%SCRIPT_NAME%" >nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Plugin installed successfully!
    echo.
    echo Installed to:
    echo   %RESOLVE_DIR%\\%SCRIPT_NAME%
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
"""
    for folder in [ROOT_DIR, DIST_DIR]:
        path = os.path.join(folder, "install.bat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(bat_content)
    print(f"[+] Created install.bat")


def create_installer_py():
    py_content = """#!/usr/bin/env python3
\"\"\"Cross-platform installer for DaVinci Resolve to After Effects Exporter.\"\"\"

import os
import shutil
import sys

def get_utility_dir() -> str:
    if sys.platform.startswith("win"):
        return os.path.join(
            os.getenv("APPDATA", ""),
            "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion", "Scripts", "Utility"
        )
    elif sys.platform == "darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
        )
    else:
        return os.path.expanduser(
            "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility"
        )

def main():
    print("=" * 65)
    print(" DaVinci Resolve -> After Effects Exporter Installer")
    print("=" * 65)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "ae_export.py"),
        os.path.join(base_dir, "dist", "ae_export.py"),
    ]
    src = None
    for c in candidates:
        if os.path.exists(c):
            src = c
            break

    if not src:
        print("[!] Error: ae_export.py not found in package.")
        sys.exit(1)

    dest_dir = get_utility_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "ae_export.py")

    shutil.copy2(src, dest)
    print(f"[+] Successfully installed to:\\n    {dest}")
    print("\\nHow to use:")
    print("  1. Open DaVinci Resolve.")
    print("  2. Mark clips with Orange color on your active timeline.")
    print("  3. Menu: Workspace -> Scripts -> Utility -> ae_export")
    print("  4. After Effects will open automatically!")

if __name__ == "__main__":
    main()
"""
    for folder in [ROOT_DIR, DIST_DIR]:
        path = os.path.join(folder, "install.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(py_content)
    print(f"[+] Created install.py")


def create_release_zip(standalone_script: str):
    zip_name = f"ResolveToAfterEffects-v{VERSION}.zip"
    zip_path = os.path.join(DIST_DIR, zip_name)

    files_to_pack = [
        ("ae_export.py", standalone_script),
        ("install.bat", os.path.join(DIST_DIR, "install.bat")),
        ("install.py", os.path.join(DIST_DIR, "install.py")),
        ("README.md", os.path.join(ROOT_DIR, "README.md")),
        ("README_RU.md", os.path.join(ROOT_DIR, "README_RU.md")),
    ]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arcname, filepath in files_to_pack:
            if os.path.exists(filepath):
                zf.write(filepath, arcname)

    print(f"[+] Created release ZIP archive: {zip_path}")


def main():
    print(f"Building DaVinci Resolve -> After Effects Integration v{VERSION}...")
    script_path = build_standalone_script()
    create_installer_bat()
    create_installer_py()
    create_release_zip(script_path)
    print("\n[OK] Build completed successfully!")


if __name__ == "__main__":
    main()
