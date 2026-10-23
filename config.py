"""
Resolve to After Effects Integration - Configuration
---------------------------------------------------
Configuration settings for extracting timeline items from DaVinci Resolve
and exporting to Adobe After Effects JSX.
"""

from dataclasses import dataclass, field
import os
from typing import Optional


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
