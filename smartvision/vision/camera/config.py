"""
SmartVision - Camera Configuration & Metadata Definitions
Platform-aware camera backend selection, video configuration presets,
and structured frame telemetry schemas.
"""

from dataclasses import asdict, dataclass
from enum import Enum
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2


class CameraBackend(str, Enum):
    """Supported video capture backends."""
    AUTO = "auto"
    DSHOW = "dshow"
    V4L2 = "v4l2"
    MSMF = "msmf"
    ANY = "any"
    SYNTHETIC = "synthetic"

    @classmethod
    def resolve_cv_backend(cls, backend: "CameraBackend") -> int:
        """Translates CameraBackend enum to corresponding cv2.CAP_* constant."""
        if backend == cls.DSHOW:
            return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
        elif backend == cls.V4L2:
            return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)
        elif backend == cls.MSMF:
            return getattr(cv2, "CAP_MSMF", cv2.CAP_ANY)
        elif backend == cls.ANY:
            return cv2.CAP_ANY
        elif backend == cls.AUTO:
            if sys.platform.startswith("win"):
                return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
            elif sys.platform.startswith("linux"):
                return getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)
            else:
                return cv2.CAP_ANY
        return cv2.CAP_ANY


# Standard candidate resolutions to probe during capability discovery
STANDARD_RESOLUTIONS: List[Tuple[int, int]] = [
    (1920, 1080),  # Full HD (1080p)
    (1280, 720),   # HD (720p)
    (800, 600),    # SVGA
    (640, 480),    # VGA (SmartVision default)
    (320, 240),    # QVGA (high-speed low-latency)
]

# Standard frame rates to test
STANDARD_FPS: List[float] = [60.0, 30.0, 24.0, 15.0]

# Standard fourcc codecs supported across UVC webcams
STANDARD_FOURCC: List[str] = ["MJPG", "YUY2", "NV12", "H264"]


@dataclass
class CameraConfig:
    """
    Configuration parameters for USB camera ingestion and streaming.
    """
    device_index: int = 0
    width: int = 640
    height: int = 480
    fps: float = 30.0
    fourcc: str = "MJPG"
    backend: CameraBackend = CameraBackend.AUTO
    buffer_size: int = 1
    auto_reconnect: bool = True
    reconnect_interval_s: float = 2.0
    max_consecutive_errors: int = 5
    enable_synthetic_fallback: bool = True
    synthetic_pattern: str = "moving_target"

    def get_fourcc_int(self) -> int:
        """Returns integer FourCC code for OpenCV."""
        if not self.fourcc or len(self.fourcc) != 4:
            return 0
        return cv2.VideoWriter_fourcc(*self.fourcc)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes configuration to standard dict."""
        data = asdict(self)
        data["backend"] = self.backend.value if isinstance(self.backend, CameraBackend) else str(self.backend)
        return data


@dataclass
class FrameMetadata:
    """
    Metadata associated with a captured video frame.
    """
    frame_id: int
    timestamp_utc: float
    monotonic_time: float
    width: int
    height: int
    fps_measured: float
    dropped_frames: int
    is_synthetic: bool
    source: str

    def to_dict(self) -> Dict[str, Any]:
        """Serializes metadata to standard JSON-compatible dict."""
        return asdict(self)
