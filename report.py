"""
Resolve to After Effects Integration - Report Generator
-------------------------------------------------------
Collects warnings, clip status, skipped items, and generates structured
reports in both JSON (report.json) and Markdown (report.md) formats.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from config import ExportConfig
from model import TimelineDump, VideoClipItem


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
