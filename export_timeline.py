"""
Resolve to After Effects Integration - Main Runner & Pipeline
-------------------------------------------------------------
Executes the full pipeline:
1. Reads DaVinci Resolve timeline (resolve_reader).
2. Filters clips by color and outputs intermediate model (model, timeline_dump.json).
3. Generates Adobe After Effects ExtendScript (jsx_generator, export.jsx).
4. Compiles structured reports (report, report.json, report.md).
5. Optionally launches Adobe After Effects with the generated script.
"""

import argparse
import glob
import os
import subprocess
import sys
from typing import Any, Dict, Optional

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
except NameError:
    SCRIPT_DIR = os.getcwd()
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)

from config import DEFAULT_CONFIG, ExportConfig, SubtitleStyleConfig
from jsx_generator import JSXGenerator
from report import ReportGenerator
from resolve_reader import ResolveReader


def find_after_effects_path() -> str:
    """Find the executable path for Adobe After Effects across Windows and macOS."""
    if sys.platform.startswith("win"):
        patterns = [
            r"C:\Program Files\Adobe\Adobe After Effects*\Support Files\AfterFX.exe",
            r"C:\Program Files (x86)\Adobe\Adobe After Effects*\Support Files\AfterFX.exe",
        ]
        for p in patterns:
            matches = glob.glob(p)
            if matches:
                return sorted(matches)[-1]
    elif sys.platform == "darwin":
        patterns = [
            "/Applications/Adobe After Effects */Adobe After Effects *.app/Contents/MacOS/After Effects",
        ]
        for p in patterns:
            matches = glob.glob(p)
            if matches:
                return sorted(matches)[-1]
    return ""


def run_pipeline(
    config: Optional[ExportConfig] = None,
    resolve_obj: Optional[Any] = None,
    launch_ae: Optional[bool] = None,
) -> Dict[str, Any]:
    """Execute the full export pipeline programmatically or via CLI."""
    cfg = config or ExportConfig()
    os.makedirs(cfg.output_dir, exist_ok=True)

    # 1. Read Timeline from Resolve
    reader = ResolveReader(cfg, resolve_obj=resolve_obj)
    dump = reader.read_current_timeline()

    # 2. Save timeline_dump.json
    dump_out_path = os.path.join(cfg.output_dir, "timeline_dump.json")
    dump.save_json(dump_out_path)
    try:
        if SCRIPT_DIR and os.path.isdir(SCRIPT_DIR):
            dump.save_json(os.path.join(SCRIPT_DIR, "timeline_dump.json"))
    except Exception:
        pass

    # 3. Generate export.jsx
    jsx_gen = JSXGenerator(cfg)
    jsx_out_path = os.path.join(cfg.output_dir, "export.jsx")
    jsx_gen.export_jsx_file(dump, jsx_out_path)
    try:
        if SCRIPT_DIR and os.path.isdir(SCRIPT_DIR):
            jsx_gen.export_jsx_file(dump, os.path.join(SCRIPT_DIR, "export.jsx"))
    except Exception:
        pass

    # 4. Generate report.json and report.md
    reporter = ReportGenerator(cfg)
    reporter.export_reports(dump, cfg.output_dir)
    try:
        if SCRIPT_DIR and os.path.isdir(SCRIPT_DIR):
            reporter.export_reports(dump, SCRIPT_DIR)
    except Exception:
        pass

    # 5. Launch After Effects if requested
    should_launch = cfg.open_after_effects if launch_ae is None else launch_ae
    ae_launched = False
    if should_launch:
        ae_exe = cfg.after_effects_path or find_after_effects_path()
        if ae_exe and os.path.exists(ae_exe):
            try:
                subprocess.Popen([ae_exe, "-r", jsx_out_path])
                ae_launched = True
            except Exception as ex:
                print(f"[!] Warning: Failed to launch After Effects: {ex}")
        else:
            print("[!] Warning: After Effects executable was not found.")

    return {
        "timeline_name": dump.timeline.name,
        "timeline_width": dump.timeline.width,
        "timeline_height": dump.timeline.height,
        "timeline_fps": dump.timeline.fps,
        "color": cfg.target_color,
        "total_timeline_clips": dump.total_timeline_clips,
        "matched_color_clips": dump.matched_color_clips,
        "clips_count": len(dump.clips),
        "skipped_count": len(dump.skipped_items),
        "subtitles_count": len(dump.subtitles),
        "jsx_path": jsx_out_path,
        "report_dir": cfg.output_dir,
        "ae_launched": ae_launched,
        "dump": dump,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Extract marked clips from DaVinci Resolve timeline and export to After Effects JSX."
    )
    parser.add_argument(
        "--color",
        "-c",
        default="Orange",
        help="Clip color to filter by (default: 'Orange', use 'All' to export all clips)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Destination directory (default: C:\\Users\\<user>\\Videos\\Resolve_to_AE)",
    )
    parser.add_argument(
        "--proxy",
        action="store_true",
        help="Use proxy media paths instead of original source files if available",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Do not export subtitles",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically launch After Effects after export",
    )
    parser.add_argument(
        "--font",
        default="Arial",
        help="Font family for subtitle text layers in After Effects (default: 'Arial')",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=48,
        help="Font size for subtitle text layers (default: 48)",
    )

    args = parser.parse_args()

    # Configure pipeline
    config = ExportConfig()
    config.target_color = args.color
    if args.output_dir:
        config.output_dir = os.path.abspath(args.output_dir)
    config.use_proxy_media = args.proxy
    config.include_subtitles = not args.no_subtitles
    config.subtitle_style = SubtitleStyleConfig(
        font_family=args.font,
        font_size=args.font_size,
    )

    print("=" * 72)
    print(" Resolve to After Effects Exporter")
    print("=" * 72)
    print(f"Target Clip Color: '{config.target_color}'")
    print(f"Output Directory:  {config.output_dir}")
    print(f"Include Subtitles: {config.include_subtitles} (Font: {config.subtitle_style.font_family}, Size: {config.subtitle_style.font_size})")
    print(f"Use Proxy Media:   {config.use_proxy_media}")
    print("-" * 72)

    try:
        res = run_pipeline(config=config, launch_ae=not args.no_open)
    except Exception as e:
        print(f"\n[!] Error during pipeline execution: {e}")
        sys.exit(1)

    dump = res["dump"]

    # Output Summary to Console
    print("\n" + "=" * 72)
    print(" EXPORT PIPELINE COMPLETED")
    print("=" * 72)
    print(f"Timeline: '{dump.timeline.name}' ({dump.timeline.width}x{dump.timeline.height} @ {dump.timeline.fps}fps)")
    print(f"Total video clips on timeline: {dump.total_timeline_clips}")
    print(f"Clips matching color '{dump.target_color}': {dump.matched_color_clips}")
    print(f"Exported video clips:          {len(dump.clips)}")
    print(f"Skipped items:                 {len(dump.skipped_items)}")
    print(f"Exported subtitles:            {len(dump.subtitles)}")

    if dump.clips:
        print("\nExported Clips:")
        for c in dump.clips:
            status_tag = "[OK]" if not c.warnings else "[PARTIAL]"
            print(f"  {status_tag} Clip #{c.id}: '{c.name}'")
            print(f"       Frames: {c.timeline_start_frame}..{c.timeline_end_frame} | File: {c.resolved_path}")
            if c.warnings:
                for w in c.warnings:
                    print(f"       [Warning] {w}")

    if dump.skipped_items:
        print("\nSkipped Items:")
        for item in dump.skipped_items:
            print(f"  - '{item['name']}': {item['reason']}")

    print("\n" + "=" * 72)
    print(" GENERATED FILES:")
    print(f" 1. ExtendScript:  {res['jsx_path']}")
    print(f" 2. Markdown Rep.: {os.path.join(config.output_dir, 'report.md')}")
    print(f" 3. JSON Report:   {os.path.join(config.output_dir, 'report.json')}")
    print(f" 4. Timeline Dump: {os.path.join(config.output_dir, 'timeline_dump.json')}")
    print("=" * 72)


if __name__ == "__main__":
    main()
