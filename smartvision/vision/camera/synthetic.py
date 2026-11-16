"""
SmartVision - Synthetic Test Pattern & Virtual Camera Fallback
Generates dynamic SMPTE color bars, moving simulated targets, and live OSD
timestamps. Acts as a drop-in replacement for cv2.VideoCapture when no physical
webcam is connected or when hardware drops out.
"""

from datetime import datetime
import math
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np


class SyntheticTestPattern:
    """
    Renders high-fidelity synthetic calibration frames with dynamic moving targets,
    color bars, and timestamp overlays.
    """

    # SMPTE 7-Color Bars (BGR format)
    COLOR_BARS = [
        (255, 255, 255),  # White
        (0, 255, 255),    # Yellow
        (255, 255, 0),    # Cyan
        (0, 255, 0),      # Green
        (255, 0, 255),    # Magenta
        (0, 0, 255),      # Red
        (255, 0, 0),      # Blue
    ]

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        pattern: str = "moving_target",
    ):
        self.width = width
        self.height = height
        self.fps = max(1.0, fps)
        self.pattern = pattern
        self._frame_count = 0
        self._start_time = time.time()

        # Motion trajectory frequencies
        self.freq_x = 0.25  # Hz
        self.freq_y = 0.18  # Hz
        self.target_w = 90
        self.target_h = 160

    def generate_frame(self, t: Optional[float] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Generates a synthetic frame at time t (or current monotonic time).
        Returns (frame_bgr, ground_truth_dict).
        """
        if t is None:
            t = time.time() - self._start_time

        self._frame_count += 1
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

        # 1. Background: Upper color bars (55% height)
        bar_height = int(self.height * 0.55)
        num_bars = len(self.COLOR_BARS)
        bar_width = self.width // num_bars

        for i, color in enumerate(self.COLOR_BARS):
            x1 = i * bar_width
            x2 = self.width if i == num_bars - 1 else (i + 1) * bar_width
            frame[0:bar_height, x1:x2] = color

        # 2. Intermediate grayscale wedge (15% height)
        wedge_start = bar_height
        wedge_height = int(self.height * 0.15)
        wedge_end = wedge_start + wedge_height
        num_gray_steps = 8
        gray_step_width = self.width // num_gray_steps
        for i in range(num_gray_steps):
            val = int(255 * (i / (num_gray_steps - 1)))
            x1 = i * gray_step_width
            x2 = self.width if i == num_gray_steps - 1 else (i + 1) * gray_step_width
            frame[wedge_start:wedge_end, x1:x2] = (val, val, val)

        # 3. Bottom dark telemetry zone
        frame[wedge_end:self.height, :] = (24, 24, 24)

        # 4. Moving Simulated Person Target
        center_x = self.width / 2.0
        center_y = self.height / 2.0

        if self.pattern == "moving_target" or self.pattern == "sinusoidal":
            amp_x = (self.width - self.target_w) * 0.35
            amp_y = (self.height - self.target_h) * 0.20
            cx = center_x + amp_x * math.sin(2.0 * math.pi * self.freq_x * t)
            cy = center_y + amp_y * math.cos(2.0 * math.pi * self.freq_y * t)
        elif self.pattern == "center_static":
            cx = center_x
            cy = center_y
        else:
            # Linear bounce
            speed_x = 120.0  # px/s
            period_x = (self.width - self.target_w) / speed_x
            phase_x = (t % (2 * period_x)) / period_x
            if phase_x > 1.0:
                phase_x = 2.0 - phase_x
            cx = (self.target_w / 2.0) + phase_x * (self.width - self.target_w)
            cy = center_y

        x1 = int(cx - self.target_w / 2.0)
        y1 = int(cy - self.target_h / 2.0)
        x2 = x1 + self.target_w
        y2 = y1 + self.target_h

        # Draw semi-transparent bounding box and reticle
        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), -1)
        cv2.addWeighted(overlay, 0.25, frame, 0.75, 0, frame)

        # Solid bounding box frame & corner accents
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        corner_len = 16
        cv2.line(frame, (x1, y1), (x1 + corner_len, y1), (0, 255, 255), 3)
        cv2.line(frame, (x1, y1), (x1, y1 + corner_len), (0, 255, 255), 3)
        cv2.line(frame, (x2, y1), (x2 - corner_len, y1), (0, 255, 255), 3)
        cv2.line(frame, (x2, y1), (x2, y1 + corner_len), (0, 255, 255), 3)

        # Centroid crosshair
        icx, icy = int(cx), int(cy)
        cv2.drawMarker(frame, (icx, icy), (0, 0, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

        # Target label
        label = f"SIM_PERSON_01 ({cx:.0f}, {cy:.0f})"
        cv2.putText(frame, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv2.LINE_AA)

        # 5. On-Screen Display (OSD) / Status Banner
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        banner_text = " [SYNTHETIC TEST PATTERN - HARDWARE SIMULATOR ACTIVE] "
        cv2.putText(frame, banner_text, (20, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, banner_text, (20, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 255), 1, cv2.LINE_AA)

        # Footer OSD
        footer_y = self.height - 12
        footer_info = f"TIME: {now_str}  |  FRAME: {self._frame_count:06d}  |  RES: {self.width}x{self.height} @ {self.fps:.0f}FPS"
        cv2.putText(frame, footer_info, (14, footer_y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)

        # Heartbeat visual spinner in corner
        spin_radius = 8
        spin_center = (self.width - 24, footer_y - 4)
        spin_angle = (t * 4.0) % (2.0 * math.pi)
        spin_x = int(spin_center[0] + spin_radius * math.cos(spin_angle))
        spin_y = int(spin_center[1] + spin_radius * math.sin(spin_angle))
        cv2.circle(frame, spin_center, spin_radius, (60, 60, 60), 1)
        cv2.circle(frame, (spin_x, spin_y), 3, (0, 255, 0), -1)

        ground_truth = {
            "target_detected": True,
            "centroid": (cx, cy),
            "bbox": (x1, y1, x2, y2),
            "label": "SIM_PERSON_01",
            "confidence": 0.96,
            "timestamp": t,
            "frame_id": self._frame_count,
        }

        return frame, ground_truth


class SyntheticCamera:
    """
    OpenCV VideoCapture compatible camera emulator yielding synthetic frames.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        pattern: str = "moving_target",
        realtime_pacing: bool = True,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_interval = 1.0 / max(1.0, fps)
        self.realtime_pacing = realtime_pacing
        self.pattern_generator = SyntheticTestPattern(width, height, fps, pattern)

        self._is_opened = True
        self._next_read_time = 0.0
        self.last_ground_truth: Optional[Dict[str, Any]] = None

    def isOpened(self) -> bool:
        """Emulates cv2.VideoCapture.isOpened()."""
        return self._is_opened

    def open(self, *args: Any, **kwargs: Any) -> bool:
        """Reopens the synthetic camera."""
        self._is_opened = True
        self._next_read_time = 0.0
        return True

    def release(self) -> None:
        """Emulates cv2.VideoCapture.release()."""
        self._is_opened = False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Emulates cv2.VideoCapture.read().
        Applies real-time pacing if realtime_pacing is True.
        """
        if not self._is_opened:
            return False, None

        if self.realtime_pacing:
            now_mono = time.monotonic()
            if self._next_read_time > 0.0 and now_mono < self._next_read_time:
                sleep_time = self._next_read_time - now_mono
                if sleep_time > 0.001:
                    time.sleep(sleep_time)
                now_mono = time.monotonic()
            self._next_read_time = max(now_mono, self._next_read_time) + self.frame_interval

        frame, gt = self.pattern_generator.generate_frame()
        self.last_ground_truth = gt
        return True, frame

    def grab(self) -> bool:
        """Emulates cv2.VideoCapture.grab()."""
        return self._is_opened

    def retrieve(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Emulates cv2.VideoCapture.retrieve()."""
        return self.read()

    def get(self, prop_id: int) -> float:
        """Emulates cv2.VideoCapture.get(prop_id)."""
        if prop_id == getattr(cv2, "CAP_PROP_FRAME_WIDTH", 3):
            return float(self.width)
        elif prop_id == getattr(cv2, "CAP_PROP_FRAME_HEIGHT", 4):
            return float(self.height)
        elif prop_id == getattr(cv2, "CAP_PROP_FPS", 5):
            return float(self.fps)
        elif prop_id == getattr(cv2, "CAP_PROP_FOURCC", 6):
            return float(cv2.VideoWriter_fourcc(*"MJPG"))
        elif prop_id == getattr(cv2, "CAP_PROP_FRAME_COUNT", 7):
            return float(self.pattern_generator._frame_count)
        return 0.0

    def set(self, prop_id: int, value: float) -> bool:
        """Emulates cv2.VideoCapture.set(prop_id, value)."""
        if prop_id == getattr(cv2, "CAP_PROP_FRAME_WIDTH", 3):
            self.width = int(value)
            self.pattern_generator.width = int(value)
            return True
        elif prop_id == getattr(cv2, "CAP_PROP_FRAME_HEIGHT", 4):
            self.height = int(value)
            self.pattern_generator.height = int(value)
            return True
        elif prop_id == getattr(cv2, "CAP_PROP_FPS", 5):
            self.fps = max(1.0, float(value))
            self.frame_interval = 1.0 / self.fps
            self.pattern_generator.fps = self.fps
            return True
        return True
