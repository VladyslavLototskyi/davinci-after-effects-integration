"""
Resolve to After Effects Integration - JSX Generator
----------------------------------------------------
Generates Adobe After Effects ExtendScript (export.jsx) from an intermediate
TimelineDump model. Completely independent of the DaVinci Resolve API.
"""

import json
import os
from typing import Optional

from config import DEFAULT_CONFIG, ExportConfig, SubtitleStyleConfig
from model import TimelineDump, VideoClipItem


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
