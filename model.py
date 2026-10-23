"""
Resolve to After Effects Integration - Intermediate Data Model
--------------------------------------------------------------
Pure data structures representing the timeline, clips, subtitles, and transforms.
Completely decoupled from DaVinci Resolve API objects.
"""

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Dict, List, Optional


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
