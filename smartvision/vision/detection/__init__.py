"""
SmartVision - Person Detection Subsystem
Provides deep learning YOLO person detection with graceful mock fallback for offline tests.
"""

from .base import BasePersonDetector
from .factory import create_detector
from .mock_detector import MockPersonDetector
from .types import PersonDetection
from .yolo_detector import DetectorUnavailableError, YoloPersonDetector

__all__ = [
    "PersonDetection",
    "BasePersonDetector",
    "YoloPersonDetector",
    "MockPersonDetector",
    "DetectorUnavailableError",
    "create_detector",
]
