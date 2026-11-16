"""
SmartVision - Camera Subsystem Package
"""

from .capture_thread import CameraCaptureThread
from .config import (
    CameraBackend,
    CameraConfig,
    FrameMetadata,
    STANDARD_FOURCC,
    STANDARD_FPS,
    STANDARD_RESOLUTIONS,
)
from .service import CameraService
from .stream import async_get_mjpeg_stream, draw_hud_overlay, get_mjpeg_stream
from .synthetic import SyntheticCamera, SyntheticTestPattern


def __getattr__(name: str):
    if name in ("CameraProbe", "CameraDeviceInfo"):
        from .probe import CameraDeviceInfo, CameraProbe
        if name == "CameraProbe":
            return CameraProbe
        return CameraDeviceInfo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CameraBackend",
    "CameraCaptureThread",
    "CameraConfig",
    "CameraDeviceInfo",
    "CameraProbe",
    "CameraService",
    "FrameMetadata",
    "STANDARD_FOURCC",
    "STANDARD_FPS",
    "STANDARD_RESOLUTIONS",
    "SyntheticCamera",
    "SyntheticTestPattern",
    "async_get_mjpeg_stream",
    "draw_hud_overlay",
    "get_mjpeg_stream",
]
