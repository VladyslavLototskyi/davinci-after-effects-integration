"""
Resolve to After Effects - Diagnostic Script (Stage 1)
------------------------------------------------------
This script connects to DaVinci Resolve, inspects the current timeline,
tracks, video clips, properties, and subtitle items, and outputs a detailed
diagnostic summary to both the console and a JSON file (`diagnostic_output.json`).

Can be run:
1. From terminal using DaVinci's built-in Python:
   & "C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\ResolvePython\\ResolvePython.exe" diagnostic.py
2. From DaVinci Resolve UI: Workspace -> Scripts -> Utility -> diagnostic
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional


def get_resolve_instance() -> Optional[Any]:
    """Connect to DaVinci Resolve, whether run internally or externally."""
    # 1. Internal execution: 'resolve' or 'bmd' may already exist in global namespace
    if "resolve" in globals() and globals()["resolve"] is not None:
        return globals()["resolve"]

    if "bmd" in globals() and globals()["bmd"] is not None:
        bmd = globals()["bmd"]
        if hasattr(bmd, "scriptapp"):
            return bmd.scriptapp("Resolve")

    # 2. External execution: try importing DaVinciResolveScript
    try:
        import DaVinciResolveScript as dvr_script
        return dvr_script.scriptapp("Resolve")
    except ImportError:
        pass

    # 3. Fallback: try loading DaVinciResolveScript from default installation directory
    possible_paths = []
    if sys.platform.startswith("win"):
        program_data = os.getenv("PROGRAMDATA", r"C:\ProgramData")
        possible_paths.append(
            os.path.join(
                program_data,
                "Blackmagic Design",
                "DaVinci Resolve",
                "Support",
                "Developer",
                "Scripting",
                "Modules",
            )
        )
    elif sys.platform.startswith("darwin"):
        possible_paths.append(
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
        )
    elif sys.platform.startswith("linux"):
        possible_paths.append("/opt/resolve/Developer/Scripting/Modules")

    for mod_path in possible_paths:
        if os.path.exists(mod_path) and mod_path not in sys.path:
            sys.path.insert(0, mod_path)
            try:
                import DaVinciResolveScript as dvr_script
                return dvr_script.scriptapp("Resolve")
            except Exception:
                pass

    return None


def safe_call(func, *args, **kwargs) -> Any:
    """Invoke an API function and return its result, or an error string if it fails."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return f"<Error: {type(e).__name__}: {e}>"


def inspect_properties(item: Any) -> Dict[str, Any]:
    """Inspect timeline item properties via GetProperties() and GetProperty()."""
    result: Dict[str, Any] = {}

    # Try GetProperties()
    if hasattr(item, "GetProperties"):
        raw_props = safe_call(item.GetProperties)
        result["GetProperties_result"] = raw_props
    else:
        result["GetProperties_result"] = "<Method not available>"

    # Specific common transform & composite properties to probe
    probe_keys = [
        "TransformEnabled",
        "Pan",
        "Tilt",
        "ZoomX",
        "ZoomY",
        "ZoomGang",
        "RotationAngle",
        "AnchorPointX",
        "AnchorPointY",
        "FlipX",
        "FlipY",
        "Opacity",
        "CroppingEnabled",
        "CropLeft",
        "CropRight",
        "CropTop",
        "CropBottom",
        "CompositeEnabled",
        "CompositeMode",
    ]

    direct_keys = {}
    if hasattr(item, "GetProperty"):
        for k in probe_keys:
            val = safe_call(item.GetProperty, k)
            if val is not None and not str(val).startswith("<Error"):
                direct_keys[k] = val
        result["GetProperty_probed"] = direct_keys
    else:
        result["GetProperty_probed"] = "<Method not available>"

    return result


def run_diagnostic() -> Dict[str, Any]:
    """Gather diagnostic info from DaVinci Resolve."""
    diag: Dict[str, Any] = {
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": sys.platform,
        "resolve_connected": False,
    }

    print("=" * 70)
    print(" DaVinci Resolve to After Effects - Diagnostics (Stage 1)")
    print("=" * 70)
    print(f"Python: {sys.executable} ({sys.version})")
    print(f"OS: {sys.platform}")

    resolve = get_resolve_instance()
    if resolve is None:
        msg = (
            "ERROR: Could not connect to DaVinci Resolve instance.\n"
            "Please ensure that:\n"
            "1. DaVinci Resolve is open and a project is loaded.\n"
            "2. In DaVinci Resolve Studio: Preferences -> System -> General -> External scripting using: Local.\n"
            "   (Or run this script from inside Resolve: Workspace -> Scripts -> Utility -> ae_export_diagnostic)."
        )
        print(f"\n[!] {msg}\n")
        diag["error"] = msg
        return diag

    diag["resolve_connected"] = True
    product_name = safe_call(resolve.GetProductName)
    version_str = safe_call(resolve.GetVersionString)
    version_list = safe_call(resolve.GetVersion)
    is_studio = safe_call(resolve.IsStudio)

    diag["product_name"] = product_name
    diag["version_string"] = version_str
    diag["version_list"] = version_list
    diag["is_studio"] = is_studio

    print(f"\n[+] Connected to: {product_name} v{version_str} (Studio: {is_studio})")

    pm = safe_call(resolve.GetProjectManager)
    if pm is None or str(pm).startswith("<Error"):
        diag["error"] = "Failed to get ProjectManager"
        return diag

    proj = safe_call(pm.GetCurrentProject)
    if proj is None or str(proj).startswith("<Error"):
        msg = "No project is currently open in DaVinci Resolve."
        print(f"[!] {msg}")
        diag["error"] = msg
        return diag

    proj_name = safe_call(proj.GetName)
    diag["project_name"] = proj_name
    print(f"[+] Current Project: {proj_name}")

    timeline = safe_call(proj.GetCurrentTimeline)
    if timeline is None or str(timeline).startswith("<Error"):
        msg = "No timeline is currently open/selected in the project."
        print(f"[!] {msg}")
        diag["error"] = msg
        return diag

    timeline_name = safe_call(timeline.GetName)
    tl_start_frame = safe_call(timeline.GetStartFrame)
    tl_end_frame = safe_call(timeline.GetEndFrame)
    tl_start_tc = safe_call(timeline.GetStartTimecode)
    tl_current_tc = safe_call(timeline.GetCurrentTimecode)
    tl_settings = safe_call(timeline.GetSettings)

    diag["timeline"] = {
        "name": timeline_name,
        "start_frame": tl_start_frame,
        "end_frame": tl_end_frame,
        "start_timecode": tl_start_tc,
        "current_timecode": tl_current_tc,
        "settings": tl_settings,
    }

    print(f"\n[+] Current Timeline: {timeline_name}")
    print(f"    Start Frame: {tl_start_frame} | End Frame: {tl_end_frame}")
    print(f"    Start Timecode: {tl_start_tc} | Current Timecode: {tl_current_tc}")
    if isinstance(tl_settings, dict):
        print("    Timeline Settings:")
        for k in [
            "timelineResolutionWidth",
            "timelineResolutionHeight",
            "timelineFrameRate",
            "timelinePixelAspectRatio",
            "timelineDropFrameTimecode",
        ]:
            if k in tl_settings:
                print(f"      - {k}: {tl_settings.get(k)}")

    # Tracks inspection
    diag["tracks"] = {}
    print("\n" + "-" * 70)
    print(" TRACKS & CLIPS INSPECTION")
    print("-" * 70)

    for track_type in ["video", "audio", "subtitle"]:
        count = safe_call(timeline.GetTrackCount, track_type)
        if not isinstance(count, int):
            count = 0

        track_list_data = []
        print(f"\n[{track_type.upper()} Tracks: {count}]")

        for track_idx in range(1, count + 1):
            track_name = safe_call(timeline.GetTrackName, track_type, track_idx)
            is_enabled = safe_call(timeline.GetIsTrackEnabled, track_type, track_idx)
            is_locked = safe_call(timeline.GetIsTrackLocked, track_type, track_idx)
            items = safe_call(timeline.GetItemListInTrack, track_type, track_idx)
            if not isinstance(items, list):
                items = []

            print(
                f"  Track {track_idx}: '{track_name}' (Enabled: {is_enabled}, Locked: {is_locked}, Items: {len(items)})"
            )

            items_data = []
            for item_idx, item in enumerate(items, 1):
                item_data = inspect_item(item, track_type, track_idx, item_idx)
                items_data.append(item_data)

            track_list_data.append(
                {
                    "track_index": track_idx,
                    "track_name": track_name,
                    "is_enabled": is_enabled,
                    "is_locked": is_locked,
                    "item_count": len(items),
                    "items": items_data,
                }
            )

        diag["tracks"][track_type] = {
            "count": count,
            "tracks": track_list_data,
        }

    return diag


def inspect_item(
    item: Any, track_type: str, track_idx: int, item_idx: int
) -> Dict[str, Any]:
    """Inspect an individual timeline item (video clip, subtitle, etc.)."""
    item_name = safe_call(item.GetName)
    clip_color = safe_call(item.GetClipColor)
    start = safe_call(item.GetStart)
    end = safe_call(item.GetEnd)
    duration = safe_call(item.GetDuration)

    info: Dict[str, Any] = {
        "index_in_track": item_idx,
        "name": item_name,
        "clip_color": clip_color,
        "timeline_start": start,
        "timeline_end": end,
        "timeline_duration": duration,
    }

    # Video & general item specifics
    if track_type == "video":
        src_start = safe_call(item.GetSourceStartFrame)
        src_end = safe_call(item.GetSourceEndFrame)
        left_offset = safe_call(item.GetLeftOffset)
        right_offset = safe_call(item.GetRightOffset)
        speed = safe_call(item.GetSpeed)
        enabled = safe_call(item.GetClipEnabled)
        fusion_comp_count = safe_call(item.GetFusionCompCount)

        info.update(
            {
                "source_start_frame": src_start,
                "source_end_frame": src_end,
                "left_offset": left_offset,
                "right_offset": right_offset,
                "speed": speed,
                "is_enabled": enabled,
                "fusion_comp_count": fusion_comp_count,
            }
        )

        # MediaPoolItem inspection
        mpi = safe_call(item.GetMediaPoolItem)
        if mpi is None or str(mpi).startswith("<Error"):
            info["media_pool_item"] = None
            info["clip_type_hint"] = "No MediaPoolItem (Compound / Fusion / Adjustment / Generator / Title)"
        else:
            mpi_props = safe_call(mpi.GetClipProperty)
            if not isinstance(mpi_props, dict):
                # Fallback to key-by-key
                mpi_props = {
                    "File Path": safe_call(mpi.GetClipProperty, "File Path"),
                    "Proxy Media Path": safe_call(mpi.GetClipProperty, "Proxy Media Path"),
                    "FPS": safe_call(mpi.GetClipProperty, "FPS"),
                    "Resolution": safe_call(mpi.GetClipProperty, "Resolution"),
                    "Format": safe_call(mpi.GetClipProperty, "Format"),
                    "Video Codec": safe_call(mpi.GetClipProperty, "Video Codec"),
                    "Start TC": safe_call(mpi.GetClipProperty, "Start TC"),
                }

            file_path = mpi_props.get("File Path") if isinstance(mpi_props, dict) else None
            exists_on_disk = os.path.exists(file_path) if (file_path and isinstance(file_path, str)) else False

            info["media_pool_item"] = {
                "file_path": file_path,
                "exists_on_disk": exists_on_disk,
                "proxy_path": mpi_props.get("Proxy Media Path") if isinstance(mpi_props, dict) else None,
                "fps": mpi_props.get("FPS") if isinstance(mpi_props, dict) else None,
                "resolution": mpi_props.get("Resolution") if isinstance(mpi_props, dict) else None,
                "format": mpi_props.get("Format") if isinstance(mpi_props, dict) else None,
                "video_codec": mpi_props.get("Video Codec") if isinstance(mpi_props, dict) else None,
                "start_tc": mpi_props.get("Start TC") if isinstance(mpi_props, dict) else None,
                "raw_clip_properties": mpi_props,
            }

        # Inspect transform properties
        info["properties"] = inspect_properties(item)

        # Brief terminal print for this clip
        color_str = f"[{clip_color}]" if clip_color else "[No Color]"
        file_str = info["media_pool_item"]["file_path"] if info.get("media_pool_item") else info.get("clip_type_hint")
        print(f"    - Clip {item_idx}: '{item_name}' {color_str}")
        print(f"      Time: Start={start}, End={end}, Dur={duration} | File: {file_str}")
        if info.get("properties", {}).get("GetProperties_result"):
            props = info["properties"]["GetProperties_result"]
            if isinstance(props, dict):
                nonzero_props = {
                    k: v
                    for k, v in props.items()
                    if v not in (0, 0.0, 1.0, 100.0, False, "", None)
                    or k in ("Pan", "Tilt", "ZoomX", "ZoomY", "RotationAngle", "Opacity")
                }
                print(f"      Key Properties: {nonzero_props}")

    elif track_type == "subtitle":
        # Detailed inspection of subtitle timeline item
        mpi = safe_call(item.GetMediaPoolItem)
        markers = safe_call(item.GetMarkers)
        props = inspect_properties(item)

        # Inspect all public attributes/methods of the item object
        item_dir = [attr for attr in dir(item) if not attr.startswith("_")]

        info.update(
            {
                "subtitle_text_probe": {
                    "item_name": item_name,
                    "media_pool_item": str(mpi),
                    "markers": markers,
                    "available_methods": item_dir,
                },
                "properties": props,
            }
        )

        print(f"    - Subtitle {item_idx}: Name='{item_name}' (Start={start}, End={end}, Dur={duration})")
        print(f"      Markers: {markers}")

    return info


def main():
    diagnostic_data = run_diagnostic()

    # Save to JSON file in current working directory
    out_file = os.path.abspath("diagnostic_output.json")
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(diagnostic_data, f, indent=2, ensure_ascii=False)
        print("\n" + "=" * 70)
        print(f"[+] Full diagnostic report saved to:\n    {out_file}")
        print("=" * 70)
    except Exception as e:
        print(f"\n[!] Failed to save diagnostic JSON to {out_file}: {e}")


if __name__ == "__main__":
    main()
