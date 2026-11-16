"""
SmartVision - YOLO Person Detection Engine
Wraps lightweight pretrained YOLOv8n filtered strictly to COCO Class 0 (Person).
Supports CPU and CUDA execution, with graceful exception handling when dependencies are missing.
"""

import logging
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

from .base import BasePersonDetector
from .types import PersonDetection

logger = logging.getLogger("SmartVision.YoloDetector")


class DetectorUnavailableError(Exception):
    """Raised when deep learning libraries or model weights cannot be loaded."""
    pass


class YoloPersonDetector(BasePersonDetector):
    """
    Production YOLOv8 person detector.
    Filters all inference results strictly to COCO class 0: "person".
    """

    COCO_PERSON_CLASS_ID = 0

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf_thresh: float = 0.40,
        iou_thresh: float = 0.45,
        device: Optional[str] = None,
    ):
        """
        Args:
            model_path: Path or identifier for YOLOv8 weights (e.g. 'yolov8n.pt').
            conf_thresh: Minimum detection confidence threshold (0.0 to 1.0).
            iou_thresh: Non-maximum suppression IoU threshold.
            device: 'cpu', 'cuda', 'cuda:0', or None for auto-selection.
        """
        self.model_path = model_path
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh
        self.requested_device = device

        self._model: Any = None
        self._is_ready = False
        self._device = "cpu"

        self._load_model()

    @property
    def name(self) -> str:
        return f"YOLOv8PersonDetector({self.model_path}, device={self._device})"

    @property
    def is_ready(self) -> bool:
        return self._is_ready

    @property
    def device(self) -> str:
        return self._device

    def _load_model(self) -> None:
        """Loads Ultralytics YOLO model or raises DetectorUnavailableError."""
        try:
            from ultralytics import YOLO  # lazy import
        except ImportError as e:
            raise DetectorUnavailableError(
                f"Ultralytics YOLO package is not installed ({e}). "
                "Install it with 'pip install ultralytics' or use MockPersonDetector fallback."
            ) from e

        # Determine target compute device
        try:
            import torch

            if self.requested_device:
                self._device = self.requested_device
            else:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"

        try:
            logger.info("Loading YOLO person detector from %s on %s...", self.model_path, self._device)
            self._model = YOLO(self.model_path)
            self._is_ready = True
            logger.info("YOLO person detector loaded successfully.")
        except Exception as e:
            self._is_ready = False
            raise DetectorUnavailableError(f"Failed to load YOLO model weights '{self.model_path}': {e}") from e

    def detect(self, frame: np.ndarray, conf_thresh: Optional[float] = None) -> List[PersonDetection]:
        """
        Executes YOLO inference on frame, filtering strictly to COCO Class 0 (Person).
        """
        if not self._is_ready or self._model is None:
            raise RuntimeError("YoloPersonDetector is not ready or failed to load.")

        if frame is None or frame.size == 0:
            return []

        thresh = conf_thresh if conf_thresh is not None else self.conf_thresh

        try:
            # Predict with classes=[0] (person only)
            results = self._model.predict(
                source=frame,
                classes=[self.COCO_PERSON_CLASS_ID],
                conf=thresh,
                iou=self.iou_thresh,
                device=self._device,
                verbose=False,
            )
        except Exception as e:
            logger.error("Error during YOLO inference: %s", e)
            return []

        detections: List[PersonDetection] = []
        if not results:
            return detections

        first_res = results[0]
        boxes = first_res.boxes
        if boxes is None or len(boxes) == 0:
            return detections

        # Extract coordinates and scores
        try:
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            classes = boxes.cls.cpu().numpy()

            for i in range(len(xyxy)):
                cls_id = int(classes[i])
                if cls_id != self.COCO_PERSON_CLASS_ID:
                    continue

                conf = float(confs[i])
                if conf < thresh:
                    continue

                box = xyxy[i]
                det = PersonDetection(
                    x1=float(box[0]),
                    y1=float(box[1]),
                    x2=float(box[2]),
                    y2=float(box[3]),
                    confidence=conf,
                    class_id=self.COCO_PERSON_CLASS_ID,
                    class_name="person",
                )
                detections.append(det)
        except Exception as e:
            logger.error("Error parsing YOLO output tensors: %s", e)

        return detections

    def close(self) -> None:
        """Releases YOLO model memory."""
        self._model = None
        self._is_ready = False
