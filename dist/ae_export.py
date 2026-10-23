"""
DaVinci Resolve to Adobe After Effects Exporter (v1.0.0)
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

__version__ = "1.0.0"
logger = logging.getLogger("ResolveToAE")


# --- Config ---
@dataclass
class SubtitleStyleConfig:
    """Styling settings for subtitle text layers created in After Effects."""
    font_family: str = "Arial"
    font_size: int = 48
    font_color_rgb: tuple = (1.0, 1.0, 1.0)  # Normalized 0.0 - 1.0 (White)
    apply_stroke: bool = True
    stroke_color_rgb: tuple = (0.0, 0.0, 0.0)  # Black outline
    stroke_width: int = 4
    justification: str = "CENTER"  # LEFT, CENTER, RIGHT
    # Vertical position in composition: fraction of height (e.g. 0.85 = bottom 15%)
    vertical_position_ratio: float = 0.85


@dataclass
class ExportConfig:
    """Main export configuration."""
    # Clip color to filter by (e.g. 'Orange', 'Navy', 'Olive', 'All')
    target_color: str = "Orange"

    # Destination directory for export.jsx and report
    output_dir: str = field(
        default_factory=lambda: os.path.join(
            os.path.expanduser("~"), "Videos", "Resolve_to_AE"
        )
    )

    # Subtitle handling
    include_subtitles: bool = True
    subtitle_style: SubtitleStyleConfig = field(default_factory=SubtitleStyleConfig)
    filter_subtitles_to_clips: bool = True  # Only export subtitles overlapping exported clips

    # Composition duration & timing
    # 'clips' = duration equals exported content span; 'timeline' = full DaVinci timeline
    comp_duration_mode: str = "clips"
    align_to_start: bool = True  # Shift first exported clip to start at 0:00:00:00

    # Media handling: if True and proxy media exists, use proxy path instead of original
    use_proxy_media: bool = False

    # After Effects Auto-launch
    open_after_effects: bool = True
    after_effects_path: Optional[str] = None

    # Non-native AE formats that require warnings
    non_native_extensions: tuple = (
        ".braw",
        ".r3d",
        ".crm",
        ".ari",
        ".arx",
        ".dng",
    )

    # Logging level
    log_level: str = "INFO"


# Default instance
DEFAULT_CONFIG = ExportConfig()


# --- Model ---
@dataclass
class TransformProperties:
    """Static transform properties extracted from Resolve."""
    pan: float = 0.0          # Horizontal translation in pixels
    tilt: float = 0.0         # Vertical translation in pixels
    zoom_x: float = 1.0       # Horizontal scale multiplier (1.0 = 100%)
    zoom_y: float = 1.0       # Vertical scale multiplier (1.0 = 100%)
    rotation: float = 0.0     # Rotation angle in degrees
    anchor_x: float = 0.0     # Anchor point X offset
    anchor_y: float = 0.0     # Anchor point Y offset
    opacity: float = 100.0    # Opacity percentage (0.0 - 100.0)
    flip_x: bool = False      # Horizontal flip
    flip_y: bool = False      # Vertical flip
    crop_left: float = 0.0    # Pixels cropped from left
    crop_right: float = 0.0   # Pixels cropped from right
    crop_top: float = 0.0     # Pixels cropped from top
    crop_bottom: float = 0.0  # Pixels cropped from bottom


@dataclass
class VideoClipItem:
    """Represents a single video clip on the timeline."""
    id: int
    name: str
    clip_color: str
    track_index: int
    track_name: str
    # Timeline timing in frames (0-based relative to timeline start)
    timeline_start_frame: int
    timeline_end_frame: int
    timeline_duration_frames: int
    # Source media timing in frames
    source_start_frame: int
    source_end_frame: int
    source_duration_frames: int
    left_offset: int
    right_offset: int
    # Media paths & info
    file_path: str
    proxy_path: Optional[str] = None
    resolved_path: str = ""       # Path chosen according to config (original or proxy)
    file_exists: bool = True
    is_supported_format: bool = True
    clip_fps: Optional[float] = None
    clip_resolution: Optional[str] = None
    # Playback / retime
    speed_percentage: float = 100.0
    is_retime_applied: bool = False
    is_enabled: bool = True
    # Transform
    transform: TransformProperties = field(default_factory=TransformProperties)
    # Processing status & warnings
    status: str = "INCLUDED"      # INCLUDED, PARTIAL, SKIPPED
    skip_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class SubtitleItem:
    """Represents a subtitle caption item."""
    id: int
    text: str
    timeline_start_frame: int
    timeline_end_frame: int
    timeline_duration_frames: int
    track_index: int
    track_name: str = "Subtitle 1"


@dataclass
class TimelineInfo:
    """Timeline properties and settings."""
    name: str
    width: int
    height: int
    fps: float
    pixel_aspect_ratio: str = "square"
    start_frame: int = 0
    end_frame: int = 0
    duration_frames: int = 0
    start_timecode: str = "00:00:00:00"


@dataclass
class TimelineDump:
    """Complete snapshot of the filtered timeline ready for JSX generation."""
    timeline: TimelineInfo
    target_color: str
    total_timeline_clips: int
    matched_color_clips: int
    clips: List[VideoClipItem] = field(default_factory=list)
    subtitles: List[SubtitleItem] = field(default_factory=list)
    skipped_items: List[Dict[str, Any]] = field(default_factory=list)
    general_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert entire dump hierarchy to dictionary."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize dump to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save_json(self, file_path: str) -> None:
        """Write dump to JSON file."""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineDump":
        """Deserialize from dictionary."""
        tl_data = data["timeline"]
        timeline_info = TimelineInfo(**tl_data)

        clips = []
        for c in data.get("clips", []):
            tf_data = c.pop("transform", {})
            tf = TransformProperties(**tf_data)
            clip = VideoClipItem(transform=tf, **c)
            clips.append(clip)

        subtitles = [SubtitleItem(**s) for s in data.get("subtitles", [])]

        return cls(
            timeline=timeline_info,
            target_color=data.get("target_color", ""),
            total_timeline_clips=data.get("total_timeline_clips", 0),
            matched_color_clips=data.get("matched_color_clips", 0),
            clips=clips,
            subtitles=subtitles,
            skipped_items=data.get("skipped_items", []),
            general_warnings=data.get("general_warnings", []),
        )

    @classmethod
    def load_json(cls, file_path: str) -> "TimelineDump":
        """Load dump from JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# --- Resolve Reader ---
def get_resolve_instance(resolve_obj: Optional[Any] = None) -> Optional[Any]:
    """Connect to DaVinci Resolve, whether run internally or externally."""
    if resolve_obj is not None:
        return resolve_obj

    if "resolve" in globals() and globals()["resolve"] is not None:
        return globals()["resolve"]

    if "bmd" in globals() and globals()["bmd"] is not None:
        bmd = globals()["bmd"]
        if hasattr(bmd, "scriptapp"):
            return bmd.scriptapp("Resolve")

    # When run internally from Resolve script menu, 'resolve' is in __main__
    main_mod = sys.modules.get("__main__")
    if main_mod:
        if hasattr(main_mod, "resolve") and getattr(main_mod, "resolve") is not None:
            return getattr(main_mod, "resolve")
        if hasattr(main_mod, "bmd") and getattr(main_mod, "bmd") is not None:
            bmd = getattr(main_mod, "bmd")
            if hasattr(bmd, "scriptapp"):
                return bmd.scriptapp("Resolve")

    try:
        import DaVinciResolveScript as dvr_script
        return dvr_script.scriptapp("Resolve")
    except ImportError:
        pass

    # Windows fallback path
    if sys.platform.startswith("win"):
        prog_data = os.getenv("PROGRAMDATA", r"C:\ProgramData")
        mod_path = os.path.join(
            prog_data,
            "Blackmagic Design",
            "DaVinci Resolve",
            "Support",
            "Developer",
            "Scripting",
            "Modules",
        )
        if os.path.exists(mod_path) and mod_path not in sys.path:
            sys.path.insert(0, mod_path)
            try:
                import DaVinciResolveScript as dvr_script
                return dvr_script.scriptapp("Resolve")
            except Exception:
                pass

    return None


class ResolveReader:
    """Reads DaVinci Resolve timeline and produces intermediate data structures."""

    def __init__(self, config: Optional[ExportConfig] = None, resolve_obj: Optional[Any] = None):
        self.config = config or DEFAULT_CONFIG
        self.resolve_obj = resolve_obj
        self._setup_logging()

    def _setup_logging(self):
        level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def read_current_timeline(self) -> TimelineDump:
        """Main entry point: inspects active timeline and builds TimelineDump."""
        resolve = get_resolve_instance(self.resolve_obj)
        if not resolve:
            raise RuntimeError(
                "Unable to connect to DaVinci Resolve API. "
                "Ensure Resolve is running and scripting is enabled."
            )

        pm = resolve.GetProjectManager()
        if not pm:
            raise RuntimeError("Failed to obtain ProjectManager from Resolve.")

        project = pm.GetCurrentProject()
        if not project:
            raise RuntimeError("No project is currently open in DaVinci Resolve.")

        timeline = project.GetCurrentTimeline()
        if not timeline:
            raise RuntimeError("No timeline is currently open/selected in the project.")

        logger.info(f"Connected to project '{project.GetName()}', timeline '{timeline.GetName()}'")

        # 1. Timeline metadata
        timeline_info, tl_start_frame = self._read_timeline_info(timeline)

        # 2. Clips extraction & filtering
        clips, skipped_items, total_clips, matched_clips, tl_warnings = self._read_video_clips(
            timeline, tl_start_frame, timeline_info.fps
        )

        # 3. Subtitles extraction
        subtitles = []
        if self.config.include_subtitles:
            clip_ranges = None
            if self.config.filter_subtitles_to_clips and self.config.target_color.lower() != "all" and clips:
                clip_ranges = [(c.timeline_start_frame, c.timeline_end_frame) for c in clips]
            subtitles = self._read_subtitles(timeline, tl_start_frame, clip_ranges=clip_ranges)

        return TimelineDump(
            timeline=timeline_info,
            target_color=self.config.target_color,
            total_timeline_clips=total_clips,
            matched_color_clips=matched_clips,
            clips=clips,
            subtitles=subtitles,
            skipped_items=skipped_items,
            general_warnings=tl_warnings,
        )

    def _read_timeline_info(self, timeline: Any) -> Tuple[TimelineInfo, int]:
        """Extract resolution, fps, start timecode and start frame."""
        name = timeline.GetName() or "Untitled Timeline"
        start_frame = timeline.GetStartFrame() or 0
        end_frame = timeline.GetEndFrame() or 0
        start_tc = timeline.GetStartTimecode() or "00:00:00:00"

        settings = timeline.GetSettings() or {}

        # Default fallback values
        width = 1920
        height = 1080
        fps = 24.0
        par = "square"

        if isinstance(settings, dict):
            try:
                width = int(settings.get("timelineResolutionWidth", 1920))
                height = int(settings.get("timelineResolutionHeight", 1080))
            except (ValueError, TypeError):
                pass

            try:
                raw_fps = settings.get("timelineFrameRate", 24.0)
                fps = float(raw_fps)
            except (ValueError, TypeError):
                pass

            par = settings.get("timelinePixelAspectRatio", "square")

        duration = max(0, end_frame - start_frame)

        tl_info = TimelineInfo(
            name=name,
            width=width,
            height=height,
            fps=fps,
            pixel_aspect_ratio=par,
            start_frame=start_frame,
            end_frame=end_frame,
            duration_frames=duration,
            start_timecode=start_tc,
        )

        logger.info(
            f"Timeline '{name}': {width}x{height} @ {fps}fps, "
            f"Frames: {start_frame}..{end_frame} (dur: {duration}), Start TC: {start_tc}"
        )
        return tl_info, start_frame

    def _read_video_clips(
        self, timeline: Any, tl_start_frame: int, tl_fps: float
    ) -> Tuple[List[VideoClipItem], List[Dict[str, Any]], int, int, List[str]]:
        """Walk all video tracks and filter items by color."""
        clips: List[VideoClipItem] = []
        skipped_items: List[Dict[str, Any]] = []
        general_warnings: List[str] = []

        track_count = timeline.GetTrackCount("video") or 0
        total_clips = 0
        matched_clips = 0
        clip_id_counter = 1

        target_color = self.config.target_color.strip().lower()

        for track_idx in range(1, track_count + 1):
            track_name = timeline.GetTrackName("video", track_idx) or f"Video {track_idx}"
            items = timeline.GetItemListInTrack("video", track_idx) or []

            for item in items:
                total_clips += 1
                item_name = item.GetName() or f"Clip_{clip_id_counter}"
                clip_color = (item.GetClipColor() or "").strip()

                # Filter condition: target_color == "all" or matches clip_color
                is_match = (
                    target_color == "all"
                    or target_color == ""
                    or clip_color.lower() == target_color
                )

                if not is_match:
                    continue

                matched_clips += 1
                logger.debug(f"Processing matched clip '{item_name}' (color: {clip_color}) on {track_name}")

                # Check if item has MediaPoolItem (identifies compound/fusion/generators/adjustments)
                mpi = item.GetMediaPoolItem()
                if mpi is None:
                    reason = (
                        "Clip has no underlying media file (Compound clip, Fusion clip, "
                        "Adjustment clip, Generator, or Title)."
                    )
                    logger.warning(f"Skipping clip '{item_name}': {reason}")
                    skipped_items.append(
                        {
                            "name": item_name,
                            "track": track_name,
                            "color": clip_color,
                            "reason": reason,
                            "timeline_start": item.GetStart(),
                            "timeline_end": item.GetEnd(),
                        }
                    )
                    continue

                clip_obj = self._build_clip_item(
                    item, mpi, clip_id_counter, track_idx, track_name, tl_start_frame, tl_fps
                )
                clips.append(clip_obj)
                clip_id_counter += 1

        if matched_clips == 0:
            msg = f"No clips matched target color '{self.config.target_color}'."
            general_warnings.append(msg)
            logger.warning(msg)

        return clips, skipped_items, total_clips, matched_clips, general_warnings

    def _build_clip_item(
        self,
        item: Any,
        mpi: Any,
        clip_id: int,
        track_idx: int,
        track_name: str,
        tl_start_frame: int,
        tl_fps: float,
    ) -> VideoClipItem:
        """Extract all details and inspect special cases for a single clip."""
        item_name = item.GetName() or f"Clip_{clip_id}"
        clip_color = item.GetClipColor() or ""

        # Timeline timings (normalized relative to timeline start)
        raw_start = item.GetStart() or 0
        raw_end = item.GetEnd() or 0
        tl_duration = item.GetDuration() or (raw_end - raw_start)

        # Normalize relative to timeline start_frame (e.g. if timeline starts at 0 or 3600)
        norm_start = raw_start - tl_start_frame
        norm_end = raw_end - tl_start_frame

        # Source timings
        src_start = item.GetSourceStartFrame() or 0
        src_end = item.GetSourceEndFrame() or 0
        src_duration = max(0, src_end - src_start)
        left_offset = item.GetLeftOffset() or 0
        right_offset = item.GetRightOffset() or 0

        # Media properties
        mpi_props = mpi.GetClipProperty() or {}
        if not isinstance(mpi_props, dict):
            mpi_props = {}

        file_path = mpi_props.get("File Path") or ""
        proxy_path = mpi_props.get("Proxy Media Path") or None
        clip_fps_raw = mpi_props.get("FPS")
        clip_res = mpi_props.get("Resolution")

        clip_fps: Optional[float] = None
        if clip_fps_raw is not None:
            try:
                clip_fps = float(clip_fps_raw)
            except (ValueError, TypeError):
                pass

        # Retime inspection
        speed_info = item.GetSpeed() or {}
        speed_pct = 100.0
        if isinstance(speed_info, dict):
            speed_pct = speed_info.get("Percentage", 100.0)

        is_retime = abs(speed_pct - 100.0) > 0.001

        # Transform inspection
        tf = self._extract_transform(item)

        # Evaluate warnings and special cases
        warnings: List[str] = []
        status = "INCLUDED"

        # Resolved path based on config
        resolved_path = file_path
        if self.config.use_proxy_media and proxy_path:
            resolved_path = proxy_path
            logger.info(f"Using proxy path for '{item_name}': {proxy_path}")

        # Check file existence
        file_exists = os.path.exists(resolved_path) if resolved_path else False
        if not file_exists:
            status = "PARTIAL"
            warnings.append(
                f"Media file not found on disk: '{resolved_path}'"
            )

        # Check format support (AE non-native formats)
        ext = os.path.splitext(resolved_path)[1].lower()
        is_supported_format = True
        if ext in self.config.non_native_extensions:
            is_supported_format = False
            status = "PARTIAL"
            warnings.append(
                f"Non-native After Effects format '{ext}' detected for clip '{item_name}'. "
                f"AE may require an external importer plugin or pre-render."
            )

        # Check mixed fps
        if clip_fps is not None and abs(clip_fps - tl_fps) > 0.01:
            warnings.append(
                f"Mixed FPS: Clip is {clip_fps} fps while Timeline is {tl_fps} fps. "
                f"Timecode calculation and frame alignment may drift."
            )

        # Check retime
        if is_retime:
            warnings.append(
                f"Retime speed change detected: {speed_pct:.2f}%. "
                f"AE JSX will apply time stretch, but complex speed ramps/curves cannot be transferred."
            )

        # Check Fusion comp existence on clip
        fusion_comps = item.GetFusionCompCount() or 0
        if fusion_comps > 0:
            warnings.append(
                f"Clip contains {fusion_comps} Fusion composition(s). Fusion effects cannot be exported to AE."
            )

        return VideoClipItem(
            id=clip_id,
            name=item_name,
            clip_color=clip_color,
            track_index=track_idx,
            track_name=track_name,
            timeline_start_frame=norm_start,
            timeline_end_frame=norm_end,
            timeline_duration_frames=tl_duration,
            source_start_frame=src_start,
            source_end_frame=src_end,
            source_duration_frames=src_duration,
            left_offset=left_offset,
            right_offset=right_offset,
            file_path=file_path,
            proxy_path=proxy_path,
            resolved_path=resolved_path,
            file_exists=file_exists,
            is_supported_format=is_supported_format,
            clip_fps=clip_fps,
            clip_resolution=clip_res,
            speed_percentage=speed_pct,
            is_retime_applied=is_retime,
            is_enabled=bool(item.GetClipEnabled() if hasattr(item, "GetClipEnabled") else True),
            transform=tf,
            status=status,
            warnings=warnings,
        )

    def _extract_transform(self, item: Any) -> TransformProperties:
        """Extract transform properties via GetProperties() or GetProperty()."""
        raw_props = {}
        if hasattr(item, "GetProperties"):
            res = item.GetProperties()
            if isinstance(res, dict):
                raw_props = res

        # Helper to read float property
        def get_f(key: str, default: float) -> float:
            if key in raw_props:
                try:
                    return float(raw_props[key])
                except (ValueError, TypeError):
                    pass
            if hasattr(item, "GetProperty"):
                val = item.GetProperty(key)
                if val is not None and not isinstance(val, bool):
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        pass
            return default

        # Helper to read bool property
        def get_b(key: str, default: bool) -> bool:
            if key in raw_props:
                return bool(raw_props[key])
            if hasattr(item, "GetProperty"):
                val = item.GetProperty(key)
                if isinstance(val, bool):
                    return val
            return default

        return TransformProperties(
            pan=get_f("Pan", 0.0),
            tilt=get_f("Tilt", 0.0),
            zoom_x=get_f("ZoomX", 1.0),
            zoom_y=get_f("ZoomY", 1.0),
            rotation=get_f("RotationAngle", 0.0),
            anchor_x=get_f("AnchorPointX", 0.0),
            anchor_y=get_f("AnchorPointY", 0.0),
            opacity=get_f("Opacity", 100.0),
            flip_x=get_b("FlipX", False),
            flip_y=get_b("FlipY", False),
            crop_left=get_f("CropLeft", 0.0),
            crop_right=get_f("CropRight", 0.0),
            crop_top=get_f("CropTop", 0.0),
            crop_bottom=get_f("CropBottom", 0.0),
        )

    def _read_subtitles(
        self,
        timeline: Any,
        tl_start_frame: int,
        clip_ranges: Optional[List[Tuple[int, int]]] = None,
    ) -> List[SubtitleItem]:
        """Extract subtitle items from all subtitle tracks, optionally filtered to clip ranges."""
        subtitles: List[SubtitleItem] = []
        track_count = timeline.GetTrackCount("subtitle") or 0
        sub_id = 1

        for track_idx in range(1, track_count + 1):
            track_name = timeline.GetTrackName("subtitle", track_idx) or f"Subtitle {track_idx}"
            items = timeline.GetItemListInTrack("subtitle", track_idx) or []

            for item in items:
                text = item.GetName() or ""
                # Trim empty subtitles
                if not text.strip():
                    continue

                raw_start = item.GetStart() or 0
                raw_end = item.GetEnd() or 0
                norm_start = raw_start - tl_start_frame
                norm_end = raw_end - tl_start_frame
                duration = item.GetDuration() or (norm_end - norm_start)

                # Filter subtitles if clip_ranges is provided
                if clip_ranges:
                    overlaps = any(
                        norm_start < c_end and norm_end > c_start
                        for c_start, c_end in clip_ranges
                    )
                    if not overlaps:
                        continue

                subtitles.append(
                    SubtitleItem(
                        id=sub_id,
                        text=text,
                        timeline_start_frame=norm_start,
                        timeline_end_frame=norm_end,
                        timeline_duration_frames=duration,
                        track_index=track_idx,
                        track_name=track_name,
                    )
                )
                sub_id += 1

        logger.info(f"Extracted {len(subtitles)} subtitle items from {track_count} subtitle track(s)")
        return subtitles


# --- JSX Generator ---
class JSXGenerator:
    """Generates After Effects ExtendScript (.jsx) from a TimelineDump."""

    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config or DEFAULT_CONFIG

    def generate_jsx(self, dump: TimelineDump) -> str:
        """Generate full JSX script content from TimelineDump."""
        lines = []

        # Header comments
        lines.append("// ===========================================================================")
        lines.append("// DaVinci Resolve to After Effects Export Script")
        lines.append(f"// Generated for timeline: {dump.timeline.name}")
        lines.append(f"// Target clip color: {dump.target_color}")
        lines.append(f"// Clips count: {len(dump.clips)}, Subtitles count: {len(dump.subtitles)}")
        lines.append("// ===========================================================================")
        lines.append("")
        lines.append("(function() {")
        lines.append("    app.beginUndoGroup(\"Import Resolve Timeline\");")
        lines.append("")
        lines.append("    try {")
        lines.append("        var project = app.project;")
        lines.append("        if (!project) {")
        lines.append("            alert(\"Error: No active project found in After Effects.\");")
        lines.append("            return;")
        lines.append("        }")
        lines.append("")

        # 1. Create Composition
        comp_name_esc = json.dumps(f"{dump.timeline.name}_FromResolve")
        w = dump.timeline.width
        h = dump.timeline.height
        fps = dump.timeline.fps

        # Determine composition timing and offset
        time_offset_sec = 0.0
        if self.config.comp_duration_mode == "clips" and dump.clips:
            min_frame = min(c.timeline_start_frame for c in dump.clips)
            max_frame = max(c.timeline_end_frame for c in dump.clips)

            if self.config.align_to_start:
                time_offset_sec = min_frame / fps
                duration_frames = max(1, max_frame - min_frame)
            else:
                duration_frames = max(1, max_frame)

            duration_sec = duration_frames / fps
        else:
            duration_sec = max(1.0 / fps, dump.timeline.duration_frames / fps)
            duration_frames = dump.timeline.duration_frames

        par = 1.0  # Square pixels standard

        lines.append("        // -------------------------------------------------------------------")
        lines.append("        // 1. Create Target Composition")
        lines.append("        // -------------------------------------------------------------------")
        lines.append(f"        var compName = {comp_name_esc};")
        lines.append(f"        var compWidth = {w};")
        lines.append(f"        var compHeight = {h};")
        lines.append(f"        var compPixelAspect = {par};")
        lines.append(f"        var compDuration = {duration_sec:.6f}; // {duration_frames} frames @ {fps} fps")
        lines.append(f"        var compFrameRate = {fps};")
        lines.append("")
        lines.append("        var targetComp = project.items.addComp(")
        lines.append("            compName, compWidth, compHeight, compPixelAspect, compDuration, compFrameRate")
        lines.append("        );")
        lines.append("        targetComp.openInViewer();")
        lines.append("")

        # 2. Project Folder for Footages
        lines.append("        // -------------------------------------------------------------------")
        lines.append("        // 2. Footage Organization Folder")
        lines.append("        // -------------------------------------------------------------------")
        lines.append("        var footageFolder = project.items.addFolder(\"Resolve Imported Media\");")
        lines.append("        var importedFootageMap = {};")
        lines.append("")
        lines.append("        function getOrImportFootage(filePath, clipName) {")
        lines.append("            if (importedFootageMap[filePath]) {")
        lines.append("                return importedFootageMap[filePath];")
        lines.append("            }")
        lines.append("            var fileObj = new File(filePath);")
        lines.append("            if (!fileObj.exists) {")
        lines.append("                // Attempt decodeURI fallback")
        lines.append("                fileObj = new File(decodeURI(filePath));")
        lines.append("            }")
        lines.append("            if (!fileObj.exists) {")
        lines.append("                return null;")
        lines.append("            }")
        lines.append("            var io = new ImportOptions(fileObj);")
        lines.append("            var footageItem = project.importFile(io);")
        lines.append("            footageItem.parentFolder = footageFolder;")
        lines.append("            if (clipName) footageItem.name = clipName;")
        lines.append("            importedFootageMap[filePath] = footageItem;")
        lines.append("            return footageItem;")
        lines.append("        }")
        lines.append("")

        # 3. Add Video Clips (processed in reverse order so track 1 / clip 1 sits on top in AE)
        lines.append("        // -------------------------------------------------------------------")
        lines.append("        // 3. Video Clip Layers")
        lines.append("        // -------------------------------------------------------------------")
        lines.append("        var missingFilesList = [];")
        lines.append("        var addedLayers = [];")
        lines.append("")

        # Reverse clips so earlier/lower track index layers end up visually stacked correctly
        for clip in reversed(dump.clips):
            clip_block = self._generate_clip_code(clip, fps, w, h, time_offset_sec)
            lines.append(clip_block)

        # 4. Subtitles (if included)
        if dump.subtitles and self.config.include_subtitles:
            lines.append("")
            lines.append("        // -------------------------------------------------------------------")
            lines.append("        // 4. Subtitle Text Layers")
            lines.append("        // -------------------------------------------------------------------")
            max_comp_time = duration_sec + time_offset_sec
            for sub in reversed(dump.subtitles):
                sub_start_sec = sub.timeline_start_frame / fps
                sub_end_sec = sub.timeline_end_frame / fps
                # Filter out subtitles outside the composition time range
                if self.config.comp_duration_mode == "clips" and dump.clips:
                    if sub_end_sec <= time_offset_sec or sub_start_sec >= max_comp_time:
                        continue
                sub_block = self._generate_subtitle_code(sub, fps, w, h, time_offset_sec)
                lines.append(sub_block)

        # Completion summary & undo group close
        lines.append("")
        lines.append("        if (missingFilesList.length > 0) {")
        lines.append("            alert(\"Resolve Import complete with warnings:\\nSome media files were not found:\\n\" + missingFilesList.join(\"\\n\"));")
        lines.append("        }")
        lines.append("    } catch(err) {")
        lines.append("        alert(\"Error executing Resolve export script:\\n\" + err.toString());")
        lines.append("    } finally {")
        lines.append("        app.endUndoGroup();")
        lines.append("    }")
        lines.append("})();")

        return "\n".join(lines)

    def _generate_clip_code(
        self,
        clip: VideoClipItem,
        tl_fps: float,
        comp_w: int,
        comp_h: int,
        time_offset_sec: float = 0.0,
    ) -> str:
        """Generate ExtendScript code for a single VideoClipItem."""
        # Normalize file path to forward slashes for ExtendScript
        clean_path = clip.resolved_path.replace("\\", "/")
        path_esc = json.dumps(clean_path)
        clip_name_esc = json.dumps(clip.name)

        # Timing calculations relative to composition start
        in_point_sec = (clip.timeline_start_frame / tl_fps) - time_offset_sec
        out_point_sec = (clip.timeline_end_frame / tl_fps) - time_offset_sec

        # Retime speed factor
        speed_factor = clip.speed_percentage / 100.0
        if speed_factor <= 0.0:
            speed_factor = 1.0

        # Calculate source start in seconds
        # Resolve source_start_frame is at clip source FPS
        source_fps = clip.clip_fps or tl_fps
        source_start_sec = clip.source_start_frame / source_fps

        # Transform values
        tf = clip.transform
        scale_x = tf.zoom_x * 100.0 * (-1.0 if tf.flip_x else 1.0)
        scale_y = tf.zoom_y * 100.0 * (-1.0 if tf.flip_y else 1.0)
        pos_x = (comp_w / 2.0) + tf.pan
        pos_y = (comp_h / 2.0) - tf.tilt  # Resolve tilt up (+) is AE Y down (-)
        rot = tf.rotation
        opacity = tf.opacity

        code = []
        code.append(f"        // Clip [{clip.id}] '{clip.name}' (Color: {clip.clip_color}, Track: {clip.track_name})")
        code.append("        (function() {")
        code.append(f"            var filePath = {path_esc};")
        code.append(f"            var footage = getOrImportFootage(filePath, {clip_name_esc});")
        code.append("            if (!footage) {")
        code.append(f"                missingFilesList.push({path_esc});")
        code.append("                return;")
        code.append("            }")
        code.append("            var layer = targetComp.layers.add(footage);")
        code.append(f"            layer.name = {clip_name_esc};")
        code.append(f"            layer.enabled = {str(clip.is_enabled).lower()};")
        code.append("")

        # Speed stretch (if retime applied)
        if clip.is_retime_applied and abs(clip.speed_percentage - 100.0) > 0.01:
            code.append(f"            // Retime: {clip.speed_percentage:.2f}%")
            code.append(f"            layer.stretch = {(100.0 / speed_factor):.4f};")

        # Layer Timing
        code.append("            // In/Out points and timeline position")
        code.append(f"            var inPoint = {in_point_sec:.6f}; // frame {clip.timeline_start_frame}")
        code.append(f"            var outPoint = {out_point_sec:.6f}; // frame {clip.timeline_end_frame}")
        code.append(f"            var srcStartSec = {source_start_sec:.6f};")
        code.append("            var stretchRatio = layer.stretch / 100.0;")
        code.append("            layer.startTime = inPoint - (srcStartSec * stretchRatio);")
        code.append("            layer.inPoint = inPoint;")
        code.append("            layer.outPoint = outPoint;")
        code.append("")

        # Transform Properties
        code.append("            // Static Transform Properties")
        code.append(f"            layer.property(\"Position\").setValue([{pos_x:.4f}, {pos_y:.4f}]);")
        code.append(f"            layer.property(\"Scale\").setValue([{scale_x:.4f}, {scale_y:.4f}]);")
        if abs(rot) > 0.0001:
            code.append(f"            layer.property(\"Rotation\").setValue({rot:.4f});")
        if abs(opacity - 100.0) > 0.0001:
            code.append(f"            layer.property(\"Opacity\").setValue({opacity:.4f});")

        # Cropping (applied as a mask if cropping values exist)
        if (
            tf.crop_left > 0
            or tf.crop_right > 0
            or tf.crop_top > 0
            or tf.crop_bottom > 0
        ):
            code.append("")
            code.append("            // Cropping rectangle mask")
            code.append("            var cropMask = layer.Masks.addProperty(\"Mask\");")
            code.append("            cropMask.maskMode = MaskMode.ADD;")
            code.append("            var cropShape = new Shape();")
            code.append(f"            var x1 = {tf.crop_left:.2f};")
            code.append(f"            var y1 = {tf.crop_top:.2f};")
            code.append(f"            var x2 = layer.width - {tf.crop_right:.2f};")
            code.append(f"            var y2 = layer.height - {tf.crop_bottom:.2f};")
            code.append("            cropShape.vertices = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];")
            code.append("            cropShape.closed = true;")
            code.append("            cropMask.property(\"maskShape\").setValue(cropShape);")

        code.append("            addedLayers.push(layer);")
        code.append("        })();\n")

        return "\n".join(code)

    def _generate_subtitle_code(
        self,
        sub,
        tl_fps: float,
        comp_w: int,
        comp_h: int,
        time_offset_sec: float = 0.0,
    ) -> str:
        """Generate ExtendScript code for a subtitle TextLayer."""
        text_esc = json.dumps(sub.text)
        in_sec = max(0.0, (sub.timeline_start_frame / tl_fps) - time_offset_sec)
        out_sec = max(in_sec + (1.0 / tl_fps), (sub.timeline_end_frame / tl_fps) - time_offset_sec)

        style: SubtitleStyleConfig = self.config.subtitle_style
        font_name_esc = json.dumps(style.font_family)
        pos_x = comp_w / 2.0
        pos_y = comp_h * style.vertical_position_ratio
        color_r, color_g, color_b = style.font_color_rgb
        stroke_r, stroke_g, stroke_b = style.stroke_color_rgb

        justification_enum = "ParagraphJustification.CENTER_JUSTIFY"
        if style.justification.upper() == "LEFT":
            justification_enum = "ParagraphJustification.LEFT_JUSTIFY"
        elif style.justification.upper() == "RIGHT":
            justification_enum = "ParagraphJustification.RIGHT_JUSTIFY"

        code = []
        code.append(f"        // Subtitle [{sub.id}]: {text_esc}")
        code.append("        (function() {")
        code.append("            var textLayer = targetComp.layers.addText(\"\");")
        code.append(f"            textLayer.name = {text_esc};")
        code.append(f"            textLayer.inPoint = {in_sec:.6f};")
        code.append(f"            textLayer.outPoint = {out_sec:.6f};")
        code.append(f"            textLayer.property(\"Position\").setValue([{pos_x:.2f}, {pos_y:.2f}]);")
        code.append("")
        code.append("            var textProp = textLayer.property(\"Source Text\");")
        code.append("            var textDocument = textProp.value;")
        code.append(f"            textDocument.text = {text_esc};")
        code.append(f"            textDocument.fontSize = {style.font_size};")
        code.append(f"            textDocument.font = {font_name_esc};")
        code.append(f"            textDocument.fillColor = [{color_r}, {color_g}, {color_b}];")
        code.append("            textDocument.applyFill = true;")
        if style.apply_stroke:
            code.append(f"            textDocument.strokeColor = [{stroke_r}, {stroke_g}, {stroke_b}];")
            code.append(f"            textDocument.strokeWidth = {style.stroke_width};")
            code.append("            textDocument.applyStroke = true;")
        code.append(f"            textDocument.justification = {justification_enum};")
        code.append("            textProp.setValue(textDocument);")
        code.append("        })();\n")

        return "\n".join(code)

    def export_jsx_file(self, dump: TimelineDump, output_path: str) -> str:
        """Generate JSX and write it to output_path."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        jsx_content = self.generate_jsx(dump)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(jsx_content)
        return output_path


# --- Report Generator ---
@dataclass
class ReportSummary:
    """High-level summary of the export operation."""
    timestamp: str
    timeline_name: str
    timeline_resolution: str
    timeline_fps: float
    timeline_duration_frames: int
    timeline_start_timecode: str
    target_color: str
    total_clips_scanned: int
    matched_color_clips: int
    exported_clips_count: int
    fully_transferred_count: int
    partial_transferred_count: int
    skipped_items_count: int
    subtitles_count: int


class ReportGenerator:
    """Builds report.json and report.md from TimelineDump and ExportConfig."""

    def __init__(self, config: Optional[ExportConfig] = None):
        self.config = config

    def build_report_data(self, dump: TimelineDump) -> Dict[str, Any]:
        """Aggregate all details into a structured dictionary."""
        fully_transferred = sum(1 for c in dump.clips if c.status == "INCLUDED" and not c.warnings)
        partial_transferred = sum(1 for c in dump.clips if c.status == "PARTIAL" or (c.status == "INCLUDED" and c.warnings))

        summary = ReportSummary(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            timeline_name=dump.timeline.name,
            timeline_resolution=f"{dump.timeline.width}x{dump.timeline.height}",
            timeline_fps=dump.timeline.fps,
            timeline_duration_frames=dump.timeline.duration_frames,
            timeline_start_timecode=dump.timeline.start_timecode,
            target_color=dump.target_color,
            total_clips_scanned=dump.total_timeline_clips,
            matched_color_clips=dump.matched_color_clips,
            exported_clips_count=len(dump.clips),
            fully_transferred_count=fully_transferred,
            partial_transferred_count=partial_transferred,
            skipped_items_count=len(dump.skipped_items),
            subtitles_count=len(dump.subtitles),
        )

        clips_report = []
        for c in dump.clips:
            clip_dict = {
                "id": c.id,
                "name": c.name,
                "track": c.track_name,
                "clip_color": c.clip_color,
                "status": "PARTIAL" if c.warnings else "FULL",
                "timeline_start_frame": c.timeline_start_frame,
                "timeline_end_frame": c.timeline_end_frame,
                "duration_frames": c.timeline_duration_frames,
                "source_start_frame": c.source_start_frame,
                "source_end_frame": c.source_end_frame,
                "file_path": c.resolved_path,
                "file_exists": c.file_exists,
                "is_proxy": (c.resolved_path == c.proxy_path) if c.proxy_path else False,
                "clip_fps": c.clip_fps,
                "speed_percentage": c.speed_percentage,
                "is_retime_applied": c.is_retime_applied,
                "transforms_applied": {
                    "position_pan_tilt": [c.transform.pan, c.transform.tilt],
                    "scale_zoom": [c.transform.zoom_x, c.transform.zoom_y],
                    "rotation": c.transform.rotation,
                    "opacity": c.transform.opacity,
                    "crop": [c.transform.crop_left, c.transform.crop_right, c.transform.crop_top, c.transform.crop_bottom],
                    "flip": [c.transform.flip_x, c.transform.flip_y],
                },
                "warnings": c.warnings,
            }
            clips_report.append(clip_dict)

        special_cases_summary = self._collect_special_cases(dump)

        needs_real_project_check = [
            "Эффекты скорости со сложными кривыми/рампами (speed ramps): передаются как постоянный stretch (на уровне всего слоя). Кривые требуют ручной доработки в AE.",
            "Форматы RAW (BRAW, R3D): в AE требуют установленного официального плагина (Blackmagic RAW Plugin или RED Cine-X).",
            "Смешанный FPS клипа и таймлайна: пересчёт времени в секунды математически точен, но при некратных fps возможен сдвиг фазы кадра на субкадровом уровне.",
            "Многострочные субтитры с индивидуальными шрифтами: стиль субтитров применяется по единому шаблону, так как Resolve API не отдаёт параметры форматирования отдельных слов/стилей дорожки.",
        ]

        return {
            "summary": asdict(summary),
            "clips": clips_report,
            "skipped_items": dump.skipped_items,
            "special_cases_detected": special_cases_summary,
            "requires_manual_verification": needs_real_project_check,
            "general_warnings": dump.general_warnings,
        }

    def _collect_special_cases(self, dump: TimelineDump) -> Dict[str, Any]:
        """Group detected special cases across all clips."""
        mixed_fps_clips = [c.name for c in dump.clips if c.clip_fps and abs(c.clip_fps - dump.timeline.fps) > 0.01]
        retime_clips = [c.name for c in dump.clips if c.is_retime_applied]
        missing_files = [c.name for c in dump.clips if not c.file_exists]
        non_native_format_clips = [c.name for c in dump.clips if not c.is_supported_format]

        return {
            "mixed_fps_detected": len(mixed_fps_clips) > 0,
            "mixed_fps_clips": mixed_fps_clips,
            "retime_detected": len(retime_clips) > 0,
            "retime_clips": retime_clips,
            "missing_files_detected": len(missing_files) > 0,
            "missing_files": missing_files,
            "non_native_formats_detected": len(non_native_format_clips) > 0,
            "non_native_clips": non_native_format_clips,
            "non_zero_start_timecode": dump.timeline.start_timecode not in ("00:00:00:00", "00:00:00;00"),
            "start_timecode": dump.timeline.start_timecode,
        }

    def generate_markdown(self, report_data: Dict[str, Any]) -> str:
        """Convert report dictionary to clean, readable Markdown format."""
        s = report_data["summary"]
        lines = []

        lines.append("# Отчёт экспорта из DaVinci Resolve в After Effects")
        lines.append(f"**Дата и время**: {s['timestamp']}  ")
        lines.append(f"**Таймлайн**: `{s['timeline_name']}` ({s['timeline_resolution']} @ {s['timeline_fps']} fps, {s['timeline_duration_frames']} кадров)  ")
        lines.append(f"**Фильтр по цвету клипа**: `{s['target_color']}`  ")
        lines.append(f"**Начальный таймкод таймлайна**: `{s['timeline_start_timecode']}`  ")
        lines.append("")

        lines.append("## 1. Сводка результатов")
        lines.append("| Параметр | Значение |")
        lines.append("|---|---|")
        lines.append(f"| Всего клипов на таймлайне | **{s['total_clips_scanned']}** |")
        lines.append(f"| Клипов с цветом `{s['target_color']}` | **{s['matched_color_clips']}** |")
        lines.append(f"| Перенесено в JSX (всего) | **{s['exported_clips_count']}** |")
        lines.append(f"| Полный перенос (без предупреждений) | **{s['fully_transferred_count']}** |")
        lines.append(f"| Частичный перенос (с предупреждениями) | **{s['partial_transferred_count']}** |")
        lines.append(f"| Пропущено (Compound, Fusion, генераторы) | **{s['skipped_items_count']}** |")
        lines.append(f"| Субтитров перенесено | **{s['subtitles_count']}** |")
        lines.append("")

        # Section 2: Processed clips
        lines.append("## 2. Обработанные клипы")
        if not report_data["clips"]:
            lines.append("*Помеченных клипов для экспорта не найдено.*")
        else:
            for c in report_data["clips"]:
                status_icon = "🟢" if c["status"] == "FULL" else "🟡"
                lines.append(f"### {status_icon} Клип #{c['id']}: `{c['name']}`")
                lines.append(f"- **Цвет клипа**: `{c['clip_color']}` | **Дорожка**: `{c['track']}` | **Статус**: `{c['status']}`")
                lines.append(f"- **Тайминги на таймлайне**: кадры `{c['timeline_start_frame']}..{c['timeline_end_frame']}` (длительность: `{c['duration_frames']}` кадров)")
                lines.append(f"- **Тайминги исходника**: кадры `{c['source_start_frame']}..{c['source_end_frame']}`")
                lines.append(f"- **Файл**: `{c['file_path']}` (существует на диске: `{c['file_exists']}`)")
                if c["is_proxy"]:
                    lines.append("- *Использован прокси-файл по настройке конфигурации.*")
                lines.append(f"- **FPS клипа**: `{c['clip_fps']}` | **Retime**: `{c['speed_percentage']:.2f}%`")
                tf = c["transforms_applied"]
                lines.append(f"- **Transform свойства**: Pan/Tilt: `{tf['position_pan_tilt']}`, Zoom: `{tf['scale_zoom']}`, Rotation: `{tf['rotation']}°`, Opacity: `{tf['opacity']}%`")

                if c["warnings"]:
                    lines.append("- **Предупреждения и особенности**:")
                    for w in c["warnings"]:
                        lines.append(f"  - ⚠️ {w}")
                lines.append("")

        # Section 3: Skipped items
        lines.append("## 3. Пропущенные элементы")
        if not report_data["skipped_items"]:
            lines.append("*Пропущенных элементов нет.*")
        else:
            for item in report_data["skipped_items"]:
                lines.append(f"- ⛔ **{item['name']}** (дорожка: `{item.get('track', 'N/A')}`, цвет: `{item.get('color', 'N/A')}`)")
                lines.append(f"  - *Причина*: {item['reason']}")
            lines.append("")

        # Section 4: Special cases detected
        lines.append("## 4. Обнаруженные особые случаи")
        sc = report_data["special_cases_detected"]
        lines.append(f"- **Смешанный FPS (Mixed FPS)**: {'Обнаружен (' + ', '.join(sc['mixed_fps_clips']) + ')' if sc['mixed_fps_detected'] else 'Не обнаружен'}")
        lines.append(f"- **Изменение скорости (Retime)**: {'Обнаружено (' + ', '.join(sc['retime_clips']) + ')' if sc['retime_detected'] else 'Не обнаружено'}")
        lines.append(f"- **Отсутствующие медиафайлы**: {'Обнаружены (' + ', '.join(sc['missing_files']) + ')' if sc['missing_files_detected'] else 'Все файлы на диске найдены'}")
        lines.append(f"- **Ненативные форматы для AE (RAW/BRAW)**: {'Обнаружены (' + ', '.join(sc['non_native_clips']) + ')' if sc['non_native_formats_detected'] else 'Все файлы в стандартных форматах'}")
        lines.append(f"- **Ненулевой Start Timecode**: {'Да (' + sc['start_timecode'] + ')' if sc['non_zero_start_timecode'] else 'Нет (00:00:00:00)'}")
        lines.append("")

        # Section 5: Requires verification on real project
        lines.append("## 5. Требует проверки на реальном проекте")
        for item in report_data["requires_manual_verification"]:
            lines.append(f"- 🔍 {item}")
        lines.append("")

        return "\n".join(lines)

    def export_reports(self, dump: TimelineDump, output_dir: str) -> Tuple[str, str]:
        """Save report.json and report.md to target directory."""
        os.makedirs(output_dir, exist_ok=True)
        report_data = self.build_report_data(dump)

        json_path = os.path.join(output_dir, "report.json")
        md_path = os.path.join(output_dir, "report.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)

        md_content = self.generate_markdown(report_data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        return json_path, md_path


# --- Pipeline Runner ---
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
        msg = f"An error occurred during export:\n\n{type(e).__name__}: {str(e)}\n\nDetails:\n{err_details}"
        show_error_dialog("Resolve -> After Effects Export Error", msg)


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-psn"):
        main()
    else:
        run_menu_export()
else:
    run_menu_export()
