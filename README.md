# DaVinci Resolve ➔ Adobe After Effects Exporter

**English** | [Русский](README_RU.md)

**Version 1.0.0** • One-click pipeline to export marked clips, subtitles, and transform properties from DaVinci Resolve into Adobe After Effects compositions.

---

## ⚡ Quick Start (1-Minute Installation)

### Windows
1. Download the release archive or folder.
2. Double-click **`install.bat`**.  
   *(The installer automatically detects your DaVinci Resolve folder and installs the plugin).*

### macOS / Linux
Run in Terminal:
```bash
python3 install.py
```

### Manual Installation (No installer needed)
Simply copy the standalone **`ae_export.py`** script into your DaVinci Resolve Utility folder:
- **Windows**: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`
- **macOS**: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
- **Linux**: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/`

---

## 🚀 How to Use

1. Open your project and timeline in **DaVinci Resolve**.
2. Select target clip(s), right-click $\rightarrow$ **Clip Color** $\rightarrow$ choose **Orange** *(default color)*.
3. In DaVinci's top menu, click:  
   **Workspace** $\rightarrow$ **Scripts** $\rightarrow$ **Utility** $\rightarrow$ **`ae_export`**
4. **Done!** Adobe After Effects will launch automatically with your imported composition ready to work on.

---

## ⌨️ Hotkey Setup (Recommended)

To export any marked scene with a single keystroke:
1. In DaVinci Resolve, open: **DaVinci Resolve** $\rightarrow$ **Keyboard Customization** (or press `Ctrl + Alt + K` / `Cmd + Option + K`).
2. Search for `ae_export` in the search bar.
3. Assign a shortcut (for example, `Ctrl + Alt + E`).
4. Click **Save**. Now you can export to After Effects in half a second!

---

## ✨ Features & Supported Attributes

- **Exact Timing & Duration**: The After Effects composition is cropped exactly to the duration of the exported clip(s) (no empty space or timeline drift).
- **Footage Management**: Media files are imported cleanly into an organized `Resolve Imported Media` project folder.
- **In / Out Points**: Frame-accurate alignment with source media In and Out points.
- **Retime & Speed Changes**: Speed multipliers are converted into layer `Stretch` percentages.
- **Transform Properties**:
  - **Position**
  - **Scale** (including independent X/Y and flip)
  - **Rotation**
  - **Opacity**
  - **Cropping** (`Crop Left / Right / Top / Bottom` applied as a clean vector mask)
- **Subtitles**: Subtitle tracks are converted into native, editable After Effects text layers with exact timings and customizable styling (font, size, color, stroke). Only subtitles overlapping the exported clips are included.
- **Audit Reports**: Structured `report.md` and `report.json` files are generated in `Videos/Resolve_to_AE` with status details and warnings (e.g. mixed FPS detection).

---

## ⚙️ Advanced CLI Options

You can also run the exporter standalone via command line:
```bash
python ae_export.py --color Orange --font "Montserrat" --font-size 52
```

### Available Arguments:
- `--color`, `-c` — Clip color to filter by (default: `Orange`, use `All` for entire track).
- `--output-dir`, `-o` — Output directory (default: `~/Videos/Resolve_to_AE`).
- `--proxy` — Use proxy media paths instead of raw footage (if available).
- `--no-subtitles` — Skip subtitle export.
- `--no-open` — Generate `export.jsx` without auto-launching After Effects.
- `--font` — Font family for subtitle text layers (default: `Arial`).
- `--font-size` — Font size for subtitle layers (default: `48`).
- `--full-timeline` — Match AE composition duration to full DaVinci timeline instead of content range.

---

## 📋 Requirements

- **DaVinci Resolve**: Studio or Free (versions 18, 19, 20, 21+)
- **Adobe After Effects**: CC 2020 through 2026+
- **Operating System**: Windows 10/11 (64-bit) or macOS
- **Python**: Uses DaVinci Resolve's embedded Python interpreter. No third-party packages or external dependencies required.
