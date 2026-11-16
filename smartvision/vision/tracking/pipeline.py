"""
SmartVision - Integrated Computer Vision & Person Tracking Pipeline
Coordinates frame acquisition, YOLO person detection, ByteTrack multi-object association,
target selection, dual-axis PID control, visual HUD rendering, and protocol telemetry serialization.
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..detection.base import BasePersonDetector
from ..detection.factory import create_detector
from .bytetrack import ByteTracker, STrack, TrackState
from .hud import HUDOverlay
from .pid_controller import DualAxisTrackingController, TrackingControlOutput
from .target_selector import TargetSelectionResult, TargetSelector, TargetState


@dataclass
class TrackingPipelineResult:
    """Consolidated results of processing a single video frame."""
    frame_annotated: np.ndarray
    raw_frame: np.ndarray
    tracks: List[STrack]
    target_result: TargetSelectionResult
    control_output: TrackingControlOutput
    fps: float
    inference_ms: float
    telemetry_message: Dict[str, Any]


class TrackingPipeline:
    """
    Central vision and person tracking engine coordinating detection, tracking,
    control, and telemetry serialization.
    """

    def __init__(
        self,
        detector: Optional[BasePersonDetector] = None,
        tracker: Optional[ByteTracker] = None,
        selector: Optional[TargetSelector] = None,
        controller: Optional[DualAxisTrackingController] = None,
        hud: Optional[HUDOverlay] = None,
        frame_width: int = 640,
        frame_height: int = 480,
        enable_hud: bool = True,
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.enable_hud = enable_hud

        # Initialize or default subsystem components
        self.detector = detector or create_detector(mode="auto")
        self.tracker = tracker or ByteTracker()
        self.selector = selector or TargetSelector(frame_width=frame_width, frame_height=frame_height)
        self.controller = controller or DualAxisTrackingController(
            frame_width=frame_width, frame_height=frame_height
        )
        self.hud = hud or HUDOverlay(frame_width=frame_width, frame_height=frame_height)

        self._frame_id = 0
        self._seq = 0
        self._last_process_time = time.time()
        self._fps_ema = 30.0
        self._last_frame: Optional[np.ndarray] = None

    @property
    def frame_id(self) -> int:
        return self._frame_id

    def reset(self) -> None:
        """Resets all tracking, PID, and target selection state."""
        self.tracker.reset()
        self.selector.stop_tracking()
        self.controller.reset()
        self._frame_id = 0
        self._seq = 0
        self._last_process_time = time.time()
        self._last_frame = None

    def click_to_track(self, click_x: float, click_y: float, frame: Optional[np.ndarray] = None) -> Optional[int]:
        """Interactively locks onto target nearest to (click_x, click_y)."""
        active_tracks = [
            t for t in self.tracker.tracked_tracks
            if getattr(t, "is_activated", True) and getattr(t, "state", None) == TrackState.Tracked
        ]
        f = frame if frame is not None else self._last_frame
        return self.selector.click_to_track(click_x, click_y, active_tracks, frame=f)

    def select_track_id(self, track_id: int, frame: Optional[np.ndarray] = None) -> bool:
        """Directly locks onto a specific track ID."""
        active_tracks = [
            t for t in self.tracker.tracked_tracks
            if getattr(t, "is_activated", True) and getattr(t, "state", None) == TrackState.Tracked
        ]
        f = frame if frame is not None else self._last_frame
        return self.selector.select_track_id(track_id, active_tracks, frame=f)

    def auto_track_first(self, strategy: str = "largest", frame: Optional[np.ndarray] = None) -> Optional[int]:
        """Engages automatic tracking of the primary detected person."""
        active_tracks = [
            t for t in self.tracker.tracked_tracks
            if getattr(t, "is_activated", True) and getattr(t, "state", None) == TrackState.Tracked
        ]
        f = frame if frame is not None else self._last_frame
        return self.selector.auto_track_first(active_tracks, strategy=strategy, frame=f)

    def set_mode(self, mode: str) -> None:
        """Sets tracking operating mode ('idle', 'auto_track', 'locked_id')."""
        self.selector.set_mode(mode)

    def stop_tracking(self) -> None:
        """Releases active lock and stops servo tracking."""
        self.selector.stop_tracking()

    def center_servos(self) -> TrackingControlOutput:
        """Commands return to calibrated center position (90°, 90°)."""
        self.selector.stop_tracking()
        return self.controller.center()

    def set_hud_enabled(self, enabled: bool) -> None:
        """Toggles visual HUD overlay rendering."""
        self.enable_hud = enabled

    def process_frame(
        self,
        frame: np.ndarray,
        timestamp_captured_ms: Optional[float] = None,
    ) -> TrackingPipelineResult:
        """
        Processes a single input BGR frame through the full vision & tracking pipeline.
        """
        now = time.time()
        now_ms = now * 1000.0
        ts_captured = timestamp_captured_ms if timestamp_captured_ms is not None else now_ms
        self._frame_id += 1
        self._seq += 1

        # Calculate instantaneous FPS
        dt = max(0.001, min(0.20, now - self._last_process_time))
        self._last_process_time = now
        inst_fps = 1.0 / dt
        self._fps_ema = 0.10 * inst_fps + 0.90 * self._fps_ema

        # 1. Person Detection
        self._last_frame = frame
        t_det_start = time.perf_counter()
        detections = self.detector.detect(frame)
        inference_ms = (time.perf_counter() - t_det_start) * 1000.0

        # 2. Multi-Object Tracking via ByteTrack
        tracks = self.tracker.update(detections)

        # 3. Target Selection & Lost Target State Machine
        target_res = self.selector.update(tracks, timestamp_ms=now_ms, frame=frame)

        # 4. Closed-Loop Dual-Axis PID Control
        is_coasting = (target_res.state == TargetState.COASTING)
        auto_center = (target_res.state == TargetState.LOST)
        centroid = target_res.centroid if target_res.state == TargetState.TRACKING else None
        control_output = self.controller.update(
            target_centroid=centroid,
            dt=dt,
            coast_factor=target_res.coast_factor,
            is_coasting=is_coasting,
            auto_center=auto_center,
        )

        # 5. Visual Tactical HUD Overlay
        if self.enable_hud:
            annotated_frame = self.hud.render(
                frame=frame,
                tracks=tracks,
                target_result=target_res,
                control_output=control_output,
                fps=self._fps_ema,
                inference_ms=inference_ms,
            )
        else:
            annotated_frame = frame.copy()

        # 6. Serialize JSON Protocol Message (track.frame_target)
        telemetry = self._build_telemetry_envelope(
            frame_id=self._frame_id,
            timestamp_captured=ts_captured,
            timestamp_processed=time.time() * 1000.0,
            target_res=target_res,
            control_output=control_output,
            tracks=tracks,
        )

        return TrackingPipelineResult(
            frame_annotated=annotated_frame,
            raw_frame=frame,
            tracks=tracks,
            target_result=target_res,
            control_output=control_output,
            fps=self._fps_ema,
            inference_ms=inference_ms,
            telemetry_message=telemetry,
        )

    def _build_telemetry_envelope(
        self,
        frame_id: int,
        timestamp_captured: float,
        timestamp_processed: float,
        target_res: TargetSelectionResult,
        control_output: TrackingControlOutput,
        tracks: List[STrack],
    ) -> Dict[str, Any]:
        """
        Serializes vision telemetry strictly adhering to docs/protocol.md section 3.5.
        """
        active_target_dict: Optional[Dict[str, Any]] = None
        locked_id = target_res.locked_track_id

        if target_res.active_track is not None:
            t = target_res.active_track
            norm_box = [
                round(t.bbox[0] / self.frame_width, 4),
                round(t.bbox[1] / self.frame_height, 4),
                round(t.bbox[2] / self.frame_width, 4),
                round(t.bbox[3] / self.frame_height, 4),
            ]
            cx, cy = t.centroid
            norm_centroid = [round(cx / self.frame_width, 4), round(cy / self.frame_height, 4)]

            active_target_dict = {
                "track_id": t.track_id,
                "class_name": "person",
                "confidence": round(t.score, 4),
                "bbox": list(t.bbox_int),
                "bbox_normalized": norm_box,
                "centroid": [round(cx, 1), round(cy, 1)],
                "centroid_normalized": norm_centroid,
                "error_px": [round(control_output.raw_error_x, 1), round(control_output.raw_error_y, 1)],
                "in_deadband": control_output.is_settled,
                "commanded_delta_deg": {
                    "pan": round(control_output.delta_pan, 2),
                    "tilt": round(control_output.delta_tilt, 2),
                },
            }

        all_detections_list: List[Dict[str, Any]] = []
        for t in tracks:
            all_detections_list.append({
                "track_id": t.track_id,
                "class_name": "person",
                "confidence": round(t.score, 4),
                "bbox": list(t.bbox_int),
                "is_primary": (t.track_id == locked_id),
            })

        latency_ms = max(0.0, timestamp_processed - timestamp_captured)

        return {
            "type": "track.frame_target",
            "timestamp": int(timestamp_processed),
            "sender": "backend",
            "seq": self._seq,
            "corr_id": None,
            "payload": {
                "frame_id": frame_id,
                "timestamp_captured": int(timestamp_captured),
                "timestamp_processed": int(timestamp_processed),
                "latency_ms": round(latency_ms, 1),
                "frame_dimensions": {
                    "width": self.frame_width,
                    "height": self.frame_height,
                },
                "tracking_mode": target_res.state.value,
                "target_locked": target_res.target_locked,
                "active_target": active_target_dict,
                "all_detections": all_detections_list,
            },
        }
