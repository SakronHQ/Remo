"""
SmartVision - Person Detector Factory
Instantiates YOLO or Mock detector instances with automatic failover for offline test environments.
"""

import logging
from typing import Optional

from .base import BasePersonDetector
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
    Creates and returns an operational person detector.

    Args:
        mode: "auto" (attempts YOLO first, falls back gracefully to Mock if missing),
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

    if normalized_mode == "yolo":
        logger.info("Initializing YoloPersonDetector (%s)...", model_path)
        return YoloPersonDetector(model_path=model_path, conf_thresh=conf_thresh, device=device)

    if normalized_mode == "auto":
        try:
            logger.info("Attempting to load YOLOv8 person detector (%s)...", model_path)
            detector = YoloPersonDetector(model_path=model_path, conf_thresh=conf_thresh, device=device)
            return detector
        except (DetectorUnavailableError, Exception) as exc:
            logger.warning(
                "YOLO detector could not be loaded (%s). Gracefully falling back to MockPersonDetector.",
                exc,
            )
            return MockPersonDetector(mode=mock_mode, conf_thresh=conf_thresh)

    raise ValueError(f"Unknown detector mode: {mode!r}. Valid options: 'auto', 'yolo', 'mock'.")
