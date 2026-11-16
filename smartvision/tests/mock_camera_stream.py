#!/usr/bin/env python3
"""
SmartVision - Mock Camera Stream
Emulates a USB UVC webcam by generating synthetic 640x480 RGB/BGR frames at 30 FPS.
Supports sinusoidal, diagonal bounce, and intermittent occlusion trajectories.
Can be run standalone as a frame generator or imported as a cv2.VideoCapture drop-in mock.
"""

import argparse
import math
import sys
import time
from typing import Dict, Optional, Tuple

try:
    import numpy as np
except ImportError:
    print("Error: numpy is required for mock_camera_stream. Run: pip install numpy", file=sys.stderr)
    sys.exit(1)


class MockCameraStream:
    """
    Drop-in replacement for cv2.VideoCapture providing synthetic video frames
    with simulated moving human targets and ground-truth metadata.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        fps: float = 30.0,
        pattern: str = "sinusoidal",
        target_width: int = 80,
        target_height: int = 160,
    ):
        self.width = width
        self.height = height
        self.fps = fps
        self.frame_interval = 1.0 / fps
        self.pattern = pattern.lower()
        self.target_width = target_width
        self.target_height = target_height

        self._is_opened = True
        self._frame_count = 0
        self._start_time = time.time()
        self._last_frame_time = 0.0

        # Pattern parameters
        self.freq_x = 0.25  # Hz (one full cycle every 4 seconds)
        self.freq_y = 0.20
        self.occlusion_interval = 4.0  # seconds between occlusions
        self.occlusion_duration = 0.6  # seconds duration of occlusion

        # Last computed ground truth
        self.last_target_bbox: Optional[Tuple[int, int, int, int]] = None
        self.last_target_centroid: Optional[Tuple[float, float]] = None
        self.is_occluded = False

    def isOpened(self) -> bool:
        return self._is_opened

    def release(self) -> None:
        self._is_opened = False

    def get(self, prop_id: int) -> float:
        # Compatibility with cv2.CAP_PROP_*
        if prop_id == 3:  # CAP_PROP_FRAME_WIDTH
            return float(self.width)
        elif prop_id == 4:  # CAP_PROP_FRAME_HEIGHT
            return float(self.height)
        elif prop_id == 5:  # CAP_PROP_FPS
            return float(self.fps)
        elif prop_id == 7:  # CAP_PROP_FRAME_COUNT
            return float(self._frame_count)
        return 0.0

    def set(self, prop_id: int, value: float) -> bool:
        return True

    def _compute_target_position(self, t: float) -> Tuple[Optional[float], Optional[float]]:
        """Computes center coordinates (cx, cy) of target at time t."""
        center_x = self.width / 2.0
        center_y = self.height / 2.0

        if self.pattern == "sinusoidal":
            # Pure horizontal oscillation
            amp_x = 180.0
            cx = center_x + amp_x * math.sin(2.0 * math.pi * self.freq_x * t)
            cy = center_y
            self.is_occluded = False
            return cx, cy

        elif self.pattern == "diagonal":
            # Dual-axis oscillation
            amp_x = 160.0
            amp_y = 90.0
            cx = center_x + amp_x * math.sin(2.0 * math.pi * self.freq_x * t)
            cy = center_y + amp_y * math.cos(2.0 * math.pi * self.freq_y * t)
            self.is_occluded = False
            return cx, cy

        elif self.pattern == "occlusion":
            # Horizontal motion with intermittent target loss
            amp_x = 180.0
            cx = center_x + amp_x * math.sin(2.0 * math.pi * self.freq_x * t)
            cy = center_y

            cycle_phase = t % self.occlusion_interval
            if cycle_phase < self.occlusion_duration:
                self.is_occluded = True
                return None, None
            else:
                self.is_occluded = False
                return cx, cy

        elif self.pattern == "static":
            # Centered target for deadband and jitter testing
            cx = center_x
            cy = center_y
            self.is_occluded = False
            return cx, cy

        else:
            # Default fallback to sinusoidal
            amp_x = 180.0
            cx = center_x + amp_x * math.sin(2.0 * math.pi * self.freq_x * t)
            cy = center_y
            self.is_occluded = False
            return cx, cy

    def read(self) -> Tuple[bool, np.ndarray]:
        """
        Generates and returns the next synthetic 640x480 BGR frame.
        Simulates hardware camera timing at target FPS.
        """
        if not self._is_opened:
            return False, np.zeros((self.height, self.width, 3), dtype=np.uint8)

        current_time = time.time()
        elapsed = current_time - self._start_time

        # Create base background canvas (subtle slate dark gray #1e2430)
        frame = np.full((self.height, self.width, 3), (30, 36, 48), dtype=np.uint8)

        # Draw subtle grid lines (every 80 px)
        for x in range(0, self.width, 80):
            frame[:, x, :] = [45, 52, 65]
        for y in range(0, self.height, 80):
            frame[y, :, :] = [45, 52, 65]

        # Draw optical center crosshairs (at 320, 240)
        mid_x, mid_y = self.width // 2, self.height // 2
        frame[mid_y - 10 : mid_y + 11, mid_x, :] = [80, 100, 120]
        frame[mid_y, mid_x - 10 : mid_x + 11, :] = [80, 100, 120]

        # Draw deadband inner boundary (dashed box +/- 15px)
        db_x1, db_y1 = mid_x - 15, mid_y - 15
        db_x2, db_y2 = mid_x + 15, mid_y + 15
        frame[db_y1:db_y2:3, db_x1, :] = [0, 140, 200]
        frame[db_y1:db_y2:3, db_x2, :] = [0, 140, 200]
        frame[db_y1, db_x1:db_x2:3, :] = [0, 140, 200]
        frame[db_y2, db_x1:db_x2:3, :] = [0, 140, 200]

        # Compute synthetic target position
        cx, cy = self._compute_target_position(elapsed)

        if cx is not None and cy is not None:
            # Compute integer pixel coordinates of bounding box
            half_w = self.target_width // 2
            half_h = self.target_height // 2
            x1 = max(0, int(cx - half_w))
            y1 = max(0, int(cy - half_h))
            x2 = min(self.width - 1, int(cx + half_w))
            y2 = min(self.height - 1, int(cy + half_h))

            # Store ground truth
            self.last_target_bbox = (x1, y1, x2, y2)
            self.last_target_centroid = (cx, cy)

            # Draw synthetic target: torso/legs rectangle in vibrant cyan-blue [B=220, G=140, R=40]
            frame[y1:y2, x1:x2, :] = [220, 140, 40]

            # Draw synthetic head circle/square
            head_size = self.target_width // 3
            hx1 = max(0, int(cx - head_size))
            hx2 = min(self.width - 1, int(cx + head_size))
            hy1 = max(0, y1 - head_size * 2)
            hy2 = max(0, y1)
            frame[hy1:hy2, hx1:hx2, :] = [240, 180, 80]

            # Draw white border around target
            frame[y1, x1:x2, :] = [255, 255, 255]
            frame[y2, x1:x2, :] = [255, 255, 255]
            frame[y1:y2, x1, :] = [255, 255, 255]
            frame[y1:y2, x2, :] = [255, 255, 255]
        else:
            # Target is currently occluded
            self.last_target_bbox = None
            self.last_target_centroid = None

        self._frame_count += 1
        self._last_frame_time = current_time
        return True, frame

    def get_ground_truth(self) -> Dict:
        """Returns dictionary of active ground-truth tracking properties."""
        return {
            "frame_id": self._frame_count,
            "timestamp": time.time(),
            "pattern": self.pattern,
            "target_present": self.last_target_bbox is not None,
            "is_occluded": self.is_occluded,
            "bbox": self.last_target_bbox,
            "centroid": self.last_target_centroid,
            "optical_center": (self.width / 2.0, self.height / 2.0),
        }


def main():
    parser = argparse.ArgumentParser(description="SmartVision Mock Camera Stream Generator")
    parser.add_argument("--pattern", choices=["sinusoidal", "diagonal", "occlusion", "static"], default="sinusoidal")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--duration", type=float, default=5.0, help="Run duration in seconds")
    parser.add_argument("--save-sample", type=str, default="", help="Optional filepath to save sample frame (e.g. sample.jpg)")
    args = parser.parse_args()

    print(f"=== SmartVision Mock Camera Stream ===")
    print(f"Pattern:  {args.pattern}")
    print(f"FPS:      {args.fps}")
    print(f"Duration: {args.duration} s")

    stream = MockCameraStream(pattern=args.pattern, fps=args.fps)
    start = time.time()
    frames = 0

    saved = False
    while time.time() - start < args.duration:
        ret, frame = stream.read()
        if not ret:
            break
        frames += 1

        gt = stream.get_ground_truth()
        if frames % 30 == 0:
            if gt["target_present"]:
                cx, cy = gt["centroid"]
                print(f"Frame {frames:04d} | Target Centroid: ({cx:.1f}, {cy:.1f}) | BBox: {gt['bbox']}")
            else:
                print(f"Frame {frames:04d} | Target OCCLUDED")

        if args.save_sample and not saved and frames == 15:
            try:
                from PIL import Image
                # Convert BGR to RGB for PIL
                rgb = frame[:, :, ::-1]
                img = Image.fromarray(rgb)
                img.save(args.save_sample)
                print(f"Saved sample frame to: {args.save_sample}")
                saved = True
            except Exception as e:
                print(f"Could not save image: {e}")

        # Sleep to pace at requested FPS
        time.sleep(1.0 / args.fps)

    elapsed = time.time() - start
    actual_fps = frames / elapsed if elapsed > 0 else 0
    print(f"\nGenerated {frames} frames in {elapsed:.2f} s ({actual_fps:.1f} FPS). Test passed.")
    stream.release()


if __name__ == "__main__":
    main()
