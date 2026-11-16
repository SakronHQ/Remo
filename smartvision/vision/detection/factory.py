"""
SmartVision - Person & Face Detector Factory
Instantiates Face (YuNet), YOLO, or Mock detector instances with automatic failover for offline test environments.
"""

import logging
import os
from typing import Optional

from .base import BasePersonDetector
from .face_detector import DEFAULT_YUNET_PATH, FaceDetector
from .mock_detector import MockPersonDetector
from .yolo_detector import DetectorUnavailableError, YoloPersonDetector

logger = logging.getLogger("SmartVision.DetectorFactory")


def create_detector(
    mode: str = "auto",
    model_path: str = "yolov8n.pt",
    conf_thresh: float = 0.40,
    device: Optional[str] = None,
    mock_mode: str = "synthetic_sync",
) -> BasePersonDetector:
    """
    Creates and returns an operational person or face detector.

    Args:
        mode: "auto" (attempts YOLOv8 first, then FaceDetector, falls back to Mock if missing),
              "face" (OpenCV YuNet face detection),
              "yolo" (requires YOLO, raises DetectorUnavailableError if unavailable),
              "mock" (deterministic mock simulator for tests/CI).
        model_path: Path to YOLO weights (e.g. 'yolov8n.pt').
        conf_thresh: Minimum detection confidence threshold (default: 0.40).
        device: 'cpu', 'cuda', or None for auto.
        mock_mode: Sub-mode for MockPersonDetector ('synthetic_sync', 'multi_person', 'single_bounce').

    Returns:
        An instance conforming to BasePersonDetector.
    """
    normalized_mode = mode.lower().strip()

    if normalized_mode == "mock":
        logger.info("Initializing MockPersonDetector (mode=%s)...", mock_mode)
        return MockPersonDetector(mode=mock_mode, conf_thresh=conf_thresh)

    if normalized_mode == "face":
        logger.info("Initializing FaceDetector (YuNet)...")
        return FaceDetector(conf_thresh=conf_thresh)

    if normalized_mode == "yolo":
        logger.info("Initializing YoloPersonDetector (%s)...", model_path)
        return YoloPersonDetector(model_path=model_path, conf_thresh=conf_thresh, device=device)

    if normalized_mode == "auto":
        # 1. Try YOLOv8 person detector
        try:
            logger.info("Attempting to load YOLOv8 person detector (%s)...", model_path)
            detector = YoloPersonDetector(model_path=model_path, conf_thresh=conf_thresh, device=device)
            return detector
        except (DetectorUnavailableError, Exception) as exc:
            logger.info("YOLOv8 unavailable (%s). Checking for FaceDetector.", exc)

        # 2. Try YuNet FaceDetector if present and model_path was default
        if model_path == "yolov8n.pt" and os.path.exists(DEFAULT_YUNET_PATH):
            try:
                logger.info("Attempting to load YuNet FaceDetector (%s)...", DEFAULT_YUNET_PATH)
                return FaceDetector(model_path=DEFAULT_YUNET_PATH, conf_thresh=conf_thresh)
            except Exception as exc:
                logger.info("FaceDetector unavailable (%s). Falling back to Mock.", exc)

        # 3. Fallback to MockPersonDetector
        return MockPersonDetector(mode=mock_mode, conf_thresh=conf_thresh)

    raise ValueError(f"Unknown detector mode: {mode!r}. Valid options: 'auto', 'face', 'yolo', 'mock'.")
