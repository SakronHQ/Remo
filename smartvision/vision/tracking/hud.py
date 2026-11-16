"""
SmartVision - High-Performance Visual HUD Overlay
Renders tracking bounding boxes, target lock reticles, deadband zones, and real-time telemetry.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .bytetrack import STrack
from .pid_controller import TrackingControlOutput
from .target_selector import TargetSelectionResult, TargetState


class HUDOverlay:
    """
    Renders military-grade tactical HUD overlay over video frames:
    - Colored bounding boxes for all active tracklets with 'ID: <id> (<conf>)'
    - Highlighted box and lock reticle on the actively tracked target
    - Central deadband boundary rectangles (inner +-15px, outer +-25px)
    - Live telemetry HUD banner (FPS, inference ms, pan/tilt angles, error vectors)
    """

    # Tactical color palette (BGR)
    COLOR_PRIMARY_TARGET = (0, 0, 255)     # Vivid Red for locked target
    COLOR_LOCKED_CORNER = (0, 0, 255)      # Red corner accents
    COLOR_TRACKED_ID = (255, 200, 0)       # Cyan/Blue for untracked candidates
    COLOR_DEADBAND_INNER = (0, 255, 0)     # Green inner deadband (settled)
    COLOR_DEADBAND_OUTER = (0, 165, 255)   # Amber outer deadband (breakout)
    COLOR_RETICLE_CENTER = (80, 80, 80)    # Gray center crosshair
    COLOR_BANNER_BG = (16, 16, 16)         # Dark slate HUD banner background
    COLOR_TEXT_PRIMARY = (255, 255, 255)   # Crisp white telemetry text
    COLOR_TEXT_ACCENT = (0, 255, 255)     # Gold telemetry highlight

    def __init__(
        self,
        frame_width: int = 640,
        frame_height: int = 480,
        inner_deadband: float = 15.0,
        outer_deadband: float = 25.0,
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.cx = int(round(frame_width / 2.0))
        self.cy = int(round(frame_height / 2.0))
        self.inner_db = int(round(inner_deadband))
        self.outer_db = int(round(outer_deadband))

    def render(
        self,
        frame: np.ndarray,
        tracks: List[STrack],
        target_result: Optional[TargetSelectionResult] = None,
        control_output: Optional[TrackingControlOutput] = None,
        fps: float = 30.0,
        inference_ms: float = 0.0,
    ) -> np.ndarray:
        """
        Renders complete HUD overlay directly onto frame (in-place or copy).
        """
        if frame is None or frame.size == 0:
            return frame

        canvas = frame.copy()

        # 1. Draw central deadband rectangles & optical center reticle
        self._draw_deadband_and_crosshair(canvas, control_output)

        # 2. Draw all detected & tracked candidate boxes
        locked_id = target_result.locked_track_id if target_result else None
        active_track = target_result.active_track if target_result else None

        for t in tracks:
            is_locked = (t.track_id == locked_id)
            if not is_locked:
                self._draw_candidate_box(canvas, t)

        # 3. Draw active target highlighted box, lock reticle, and error vector line
        if active_track is not None:
            self._draw_locked_target(canvas, active_track, target_result)
        elif target_result is not None and target_result.state in (
            TargetState.COASTING,
            TargetState.HOLDING,
        ):
            # Target temporarily lost; render ghost / predicted reticle
            self._draw_ghost_target(canvas, target_result)

        # 4. Draw top telemetry HUD banner
        self._draw_telemetry_banner(canvas, fps, inference_ms, target_result, control_output)

        return canvas

    def _draw_deadband_and_crosshair(
        self, canvas: np.ndarray, control: Optional[TrackingControlOutput]
    ) -> None:
        """Draws center optical reticle and inner/outer deadband zones."""
        cx, cy = self.cx, self.cy

        # Center optical crosshair lines
        line_len = 10
        cv2.line(canvas, (cx - line_len, cy), (cx + line_len, cy), self.COLOR_RETICLE_CENTER, 1)
        cv2.line(canvas, (cx, cy - line_len), (cx, cy + line_len), self.COLOR_RETICLE_CENTER, 1)
        cv2.circle(canvas, (cx, cy), 2, self.COLOR_RETICLE_CENTER, -1)

        # Determine deadband state colors
        is_settled = control.is_settled if control else True
        inner_color = self.COLOR_DEADBAND_INNER if is_settled else (60, 180, 60)

        # Outer Deadband (25 px) - dotted/thin line
        o_x1, o_y1 = cx - self.outer_db, cy - self.outer_db
        o_x2, o_y2 = cx + self.outer_db, cy + self.outer_db
        cv2.rectangle(canvas, (o_x1, o_y1), (o_x2, o_y2), self.COLOR_DEADBAND_OUTER, 1, cv2.LINE_AA)

        # Inner Deadband (15 px) - solid rectangle
        i_x1, i_y1 = cx - self.inner_db, cy - self.inner_db
        i_x2, i_y2 = cx + self.inner_db, cy + self.inner_db
        cv2.rectangle(canvas, (i_x1, i_y1), (i_x2, i_y2), inner_color, 1, cv2.LINE_AA)

    def _draw_candidate_box(self, canvas: np.ndarray, track: STrack) -> None:
        """Renders bounding box and tag for an untracked person."""
        x1, y1, x2, y2 = track.bbox_int
        color = self.COLOR_TRACKED_ID

        # Bounding box
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 1, cv2.LINE_AA)

        # Tag label
        label = f"ID: {track.track_id} ({track.score:.2f})"
        font_scale = 0.40
        (w, h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        tag_y1 = max(16, y1 - 4)
        cv2.rectangle(canvas, (x1, tag_y1 - h - 2), (x1 + w + 4, tag_y1 + 2), (20, 20, 20), -1)
        cv2.putText(canvas, label, (x1 + 2, tag_y1), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 1, cv2.LINE_AA)

    def _draw_locked_target(
        self,
        canvas: np.ndarray,
        track: STrack,
        target_res: Optional[TargetSelectionResult],
    ) -> None:
        """Renders accented lock reticle and corner brackets on the active target."""
        x1, y1, x2, y2 = track.bbox_int
        tcx, tcy = int(round(track.centroid[0])), int(round(track.centroid[1]))

        # Semi-transparent target fill
        overlay = canvas.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), self.COLOR_PRIMARY_TARGET, -1)
        cv2.addWeighted(overlay, 0.12, canvas, 0.88, 0, canvas)

        # Box outline
        cv2.rectangle(canvas, (x1, y1), (x2, y2), self.COLOR_PRIMARY_TARGET, 2, cv2.LINE_AA)

        # 4 Corner bracket accents
        c_len = min(20, max(8, int((x2 - x1) * 0.20)))
        thick = 3
        c_col = self.COLOR_LOCKED_CORNER
        # Top-left
        cv2.line(canvas, (x1, y1), (x1 + c_len, y1), c_col, thick)
        cv2.line(canvas, (x1, y1), (x1, y1 + c_len), c_col, thick)
        # Top-right
        cv2.line(canvas, (x2, y1), (x2 - c_len, y1), c_col, thick)
        cv2.line(canvas, (x2, y1), (x2, y1 + c_len), c_col, thick)
        # Bottom-left
        cv2.line(canvas, (x1, y2), (x1 + c_len, y2), c_col, thick)
        cv2.line(canvas, (x1, y2), (x1, y2 - c_len), c_col, thick)
        # Bottom-right
        cv2.line(canvas, (x2, y2), (x2 - c_len, y2), c_col, thick)
        cv2.line(canvas, (x2, y2), (x2, y2 - c_len), c_col, thick)

        # Target Centroid Lock Reticle (concentric circle & crosshairs)
        cv2.circle(canvas, (tcx, tcy), 14, self.COLOR_PRIMARY_TARGET, 1, cv2.LINE_AA)
        cv2.circle(canvas, (tcx, tcy), 3, (0, 0, 255), -1)
        cv2.line(canvas, (tcx - 18, tcy), (tcx - 6, tcy), self.COLOR_PRIMARY_TARGET, 2)
        cv2.line(canvas, (tcx + 6, tcy), (tcx + 18, tcy), self.COLOR_PRIMARY_TARGET, 2)
        cv2.line(canvas, (tcx, tcy - 18), (tcx, tcy - 6), self.COLOR_PRIMARY_TARGET, 2)
        cv2.line(canvas, (tcx, tcy + 6), (tcx, tcy + 18), self.COLOR_PRIMARY_TARGET, 2)

        # Error vector line from center to target centroid
        cv2.line(canvas, (self.cx, self.cy), (tcx, tcy), (0, 200, 255), 1, cv2.LINE_AA)

        # Highlighted label badge
        label = f"LOCKED TARGET [ID: {track.track_id}] ({track.score:.2f})"
        font_scale = 0.45
        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        badge_y = max(18, y1 - 6)
        cv2.rectangle(canvas, (x1, badge_y - h - 4), (x1 + w + 6, badge_y + 2), (0, 0, 0), -1)
        cv2.rectangle(canvas, (x1, badge_y - h - 4), (x1 + w + 6, badge_y + 2), self.COLOR_PRIMARY_TARGET, 1)
        cv2.putText(canvas, label, (x1 + 3, badge_y - 1), cv2.FONT_HERSHEY_SIMPLEX, font_scale, self.COLOR_PRIMARY_TARGET, 1, cv2.LINE_AA)

    def _draw_ghost_target(self, canvas: np.ndarray, target_res: TargetSelectionResult) -> None:
        """Draws ghost tracking reticle when target is in COASTING or HOLDING phase."""
        if target_res.centroid is None:
            return
        gx, gy = int(round(target_res.centroid[0])), int(round(target_res.centroid[1]))
        color = (0, 165, 255) if target_res.state == TargetState.COASTING else (0, 100, 255)
        text = f"{target_res.state.value.upper()} [{target_res.time_lost_ms:.0f}ms]"

        cv2.circle(canvas, (gx, gy), 16, color, 1, cv2.LINE_AA)
        cv2.drawMarker(canvas, (gx, gy), color, markerType=cv2.MARKER_TILTED_CROSS, markerSize=14, thickness=1)
        cv2.putText(canvas, text, (gx - 35, gy - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.40, color, 1, cv2.LINE_AA)

    def _draw_telemetry_banner(
        self,
        canvas: np.ndarray,
        fps: float,
        inference_ms: float,
        target_res: Optional[TargetSelectionResult],
        control: Optional[TrackingControlOutput],
    ) -> None:
        """Renders top semi-transparent HUD telemetry bar."""
        bar_height = 42
        # Overlay semi-transparent bar
        banner = canvas[0:bar_height, :].copy()
        cv2.rectangle(banner, (0, 0), (self.frame_width, bar_height), self.COLOR_BANNER_BG, -1)
        cv2.addWeighted(banner, 0.85, canvas[0:bar_height, :], 0.15, 0, canvas[0:bar_height, :])

        # Bottom accent border line on banner
        cv2.line(canvas, (0, bar_height), (self.frame_width, bar_height), (40, 40, 40), 1)

        # Line 1 Telemetry: FPS, Inference, Target Status
        target_state_str = target_res.state.value.upper() if target_res else "IDLE"
        locked_id_str = f"ID: {target_res.locked_track_id}" if target_res and target_res.locked_track_id else "NONE"
        line1 = f"FPS: {fps:4.1f} | INFER: {inference_ms:4.1f}ms | TARGET: {locked_id_str} [{target_state_str}]"

        # Line 2 Telemetry: Pan, Tilt, Error Vector, Deadband
        if control:
            pan_deg = control.pan_angle
            tilt_deg = control.tilt_angle
            err_x = control.raw_error_x
            err_y = control.raw_error_y
            db_status = "SETTLED (DEADBAND)" if control.is_settled else "ACTIVE TRACK"
        else:
            pan_deg = 90.0
            tilt_deg = 90.0
            err_x = 0.0
            err_y = 0.0
            db_status = "IDLE"

        line2 = f"PAN: {pan_deg:5.1f}\u00b0 | TILT: {tilt_deg:5.1f}\u00b0 | ERR: ({err_x:+5.1f}, {err_y:+5.1f})px | {db_status}"

        # Render text with shadow for legibility
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 0.40
        cv2.putText(canvas, line1, (12, 16), font, scale, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(canvas, line1, (12, 16), font, scale, self.COLOR_TEXT_PRIMARY, 1, cv2.LINE_AA)

        cv2.putText(canvas, line2, (12, 34), font, scale, (0, 0, 0), 2, cv2.LINE_AA)
        db_color = (0, 255, 0) if (control and control.is_settled) else self.COLOR_TEXT_ACCENT
        cv2.putText(canvas, line2, (12, 34), font, scale, db_color, 1, cv2.LINE_AA)
