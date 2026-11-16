"""
SmartVision - Mock & Synthetic Person Detector
Provides deterministic, zero-dependency person detection for unit tests, CI environments,
synthetic camera streams, and offline simulation without GPU or PyTorch dependencies.
"""

import math
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .base import BasePersonDetector
from .types import PersonDetection


class MockPersonDetector(BasePersonDetector):
    """
    Deterministic person detector mock supporting:
    - Optical extraction of green targets rendered by SyntheticCamera
    - Procedural multi-person motion simulations (crossing paths, occlusions)
    - Manual detection injection for unit test assertions
    """

    def __init__(
        self,
        mode: str = "synthetic_sync",
        conf_thresh: float = 0.35,
        default_confidence: float = 0.92,
    ):
        """
        Args:
            mode: "synthetic_sync" (tracks SyntheticCamera colors/targets),
                  "multi_person" (generates 2 crossing simulated persons),
                  "single_bounce" (generates 1 bouncing person),
                  "manual" (uses injected detections only).
            conf_thresh: Minimum confidence threshold.
            default_confidence: Confidence assigned to synthetic detections.
        """
        self._mode = mode
        self._conf_thresh = conf_thresh
        self._default_confidence = default_confidence
        self._manual_detections: Optional[List[PersonDetection]] = None
        self._start_time = time.time()
        self._frame_count = 0

    @property
    def name(self) -> str:
        return f"MockPersonDetector(mode={self._mode})"

    @property
    def is_ready(self) -> bool:
        return True

    def set_detections(self, detections: Optional[List[PersonDetection]]) -> None:
        """Manually injects detections for test scenarios."""
        self._manual_detections = detections

    def set_mode(self, mode: str) -> None:
        """Switches procedural simulation mode."""
        self._mode = mode

    def detect(self, frame: np.ndarray, conf_thresh: Optional[float] = None) -> List[PersonDetection]:
        """Runs detection on frame according to configured mock mode."""
        thresh = conf_thresh if conf_thresh is not None else self._conf_thresh
        self._frame_count += 1
        t = time.time() - self._start_time

        # 1. Manual injection override
        if self._manual_detections is not None:
            return [d for d in self._manual_detections if d.confidence >= thresh]

        # 2. Extract from Synthetic Camera frame if mode is synthetic_sync
        if self._mode == "synthetic_sync":
            dets = self._extract_synthetic_target(frame)
            if dets:
                return [d for d in dets if d.confidence >= thresh]

        # 3. Procedural multi-person simulation
        if self._mode == "multi_person":
            return self._generate_multi_person(frame.shape, t, thresh)

        # 4. Procedural single bouncing person
        if self._mode in ("single_bounce", "synthetic_sync"):
            return self._generate_single_bounce(frame.shape, t, thresh)

        return []

    def _extract_synthetic_target(self, frame: np.ndarray) -> List[PersonDetection]:
        """
        Detects bright bounding box reticles rendered by SyntheticTestPattern.
        Extracts centroid from red center crosshair or yellow corner brackets.
        """
        if frame is None or len(frame.shape) < 3:
            return []

        h, w = frame.shape[:2]
        bw, bh = 90.0, 160.0
        split_y = int(h * 0.55)

        # 1. Search for red marker in bottom half (grayscale & telemetry regions)
        red_lower = (
            (frame[split_y:int(h * 0.95), :, 2] > 200)
            & (frame[split_y:int(h * 0.95), :, 0] < 50)
            & (frame[split_y:int(h * 0.95), :, 1] < 50)
        )
        r_pts = np.argwhere(red_lower)
        if len(r_pts) >= 20:
            cx = float(np.median(r_pts[:, 1]))
            cy = float(np.median(r_pts[:, 0])) + float(split_y)
            x1 = max(0.0, cx - bw / 2.0)
            y1 = max(0.0, cy - bh / 2.0)
            x2 = min(float(w), x1 + bw)
            y2 = min(float(h), y1 + bh)
            return [
                PersonDetection(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    confidence=self._default_confidence,
                    class_id=0,
                    class_name="person",
                )
            ]

        # 2. Search for yellow corner accents (excluding yellow color bar at top)
        yellow = (frame[:, :, 0] < 40) & (frame[:, :, 1] > 200) & (frame[:, :, 2] > 200)
        # Mask out yellow color bar (bar index 1: w//7 to 2*(w//7), y < split_y) and top banner
        yellow[0:split_y, (w // 7) : 2 * (w // 7)] = 0
        yellow[0:30, :] = 0
        yellow[int(h * 0.95) :, :] = 0
        y_pts = np.argwhere(yellow)
        if len(y_pts) >= 30:
            y1_est = float(np.min(y_pts[:, 0]))
            x_min = float(np.min(y_pts[:, 1]))
            x_max = float(np.max(y_pts[:, 1]))
            cx = (x_min + x_max) / 2.0
            cy = y1_est + bh / 2.0
            x1 = max(0.0, cx - bw / 2.0)
            y1 = max(0.0, cy - bh / 2.0)
            x2 = min(float(w), x1 + bw)
            y2 = min(float(h), y1 + bh)
            return [
                PersonDetection(
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    confidence=self._default_confidence,
                    class_id=0,
                    class_name="person",
                )
            ]

        return []

    def _generate_single_bounce(
        self, shape: Tuple[int, ...], t: float, thresh: float
    ) -> List[PersonDetection]:
        """Generates a single smoothly oscillating person target."""
        h = shape[0] if len(shape) > 0 else 480
        w = shape[1] if len(shape) > 1 else 640

        box_w = 90.0
        box_h = 160.0

        # Sinusoidal trajectory around center
        cx = (w / 2.0) + ((w - box_w) * 0.30) * math.sin(2.0 * math.pi * 0.25 * t)
        cy = (h / 2.0) + ((h - box_h) * 0.15) * math.cos(2.0 * math.pi * 0.18 * t)

        x1 = cx - box_w / 2.0
        y1 = cy - box_h / 2.0
        x2 = x1 + box_w
        y2 = y1 + box_h

        det = PersonDetection(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            confidence=self._default_confidence,
            class_id=0,
            class_name="person",
        )
        return [det] if det.confidence >= thresh else []

    def _generate_multi_person(
        self, shape: Tuple[int, ...], t: float, thresh: float
    ) -> List[PersonDetection]:
        """
        Generates 2 people walking in opposite directions and crossing each other.
        Includes brief occlusion when they intersect.
        """
        h = shape[0] if len(shape) > 0 else 480
        w = shape[1] if len(shape) > 1 else 640

        # Person 1 (moves left to right)
        box1_w, box1_h = 90.0, 160.0
        cx1 = (w / 2.0) + (w * 0.35) * math.sin(2.0 * math.pi * 0.20 * t)
        cy1 = (h / 2.0) + 10.0 * math.cos(2.0 * math.pi * 0.10 * t)

        # Person 2 (moves right to left with different vertical position)
        box2_w, box2_h = 75.0, 140.0
        cx2 = (w / 2.0) - (w * 0.35) * math.sin(2.0 * math.pi * 0.20 * t)
        cy2 = (h / 2.0) - 20.0 + 15.0 * math.sin(2.0 * math.pi * 0.15 * t)

        p1 = PersonDetection(
            x1=cx1 - box1_w / 2.0,
            y1=cy1 - box1_h / 2.0,
            x2=cx1 + box1_w / 2.0,
            y2=cy1 + box1_h / 2.0,
            confidence=0.94,
            class_id=0,
            class_name="person",
        )

        p2 = PersonDetection(
            x1=cx2 - box2_w / 2.0,
            y1=cy2 - box2_h / 2.0,
            x2=cx2 + box2_w / 2.0,
            y2=cy2 + box2_h / 2.0,
            confidence=0.88,
            class_id=0,
            class_name="person",
        )

        # If they are overlapping heavily, simulate slight confidence dip on the farther one
        dist = abs(cx1 - cx2)
        if dist < 40.0:
            # Person 2 is partially occluded
            p2 = PersonDetection(
                x1=p2.x1,
                y1=p2.y1,
                x2=p2.x2,
                y2=p2.y2,
                confidence=0.30,  # below track_thresh but above low_thresh (for ByteTrack stage 2)
                class_id=0,
                class_name="person",
            )

        dets = [p for p in (p1, p2) if p.confidence >= thresh]
        return dets
