#!/usr/bin/env python3
"""Cross-platform installer for DaVinci Resolve to After Effects Exporter."""

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
    print(f"[+] Successfully installed to:\n    {dest}")
    print("\nHow to use:")
    print("  1. Open DaVinci Resolve.")
    print("  2. Mark clips with Orange color on your active timeline.")
    print("  3. Menu: Workspace -> Scripts -> Utility -> ae_export")
    print("  4. After Effects will open automatically!")

if __name__ == "__main__":
    main()
