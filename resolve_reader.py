"""
Resolve to After Effects Integration - Resolve Reader
-----------------------------------------------------
The sole module that interfaces with the DaVinci Resolve Scripting API.
Reads timeline metadata, filters clips by color, detects transforms and
special cases, and returns decoupled `TimelineDump` models without any
Resolve API objects.
"""

import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
except NameError:
    pass

from config import DEFAULT_CONFIG, ExportConfig
from model import (
    SubtitleItem,
    TimelineDump,
    TimelineInfo,
    TransformProperties,
    VideoClipItem,
)

logger = logging.getLogger("ResolveReader")


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
