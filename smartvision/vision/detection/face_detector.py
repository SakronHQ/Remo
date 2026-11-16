"""
SmartVision - High-Performance Real-Time Face Detector
Powered by OpenCV YuNet (cv2.FaceDetectorYN), running ultra-fast (<5ms) on CPU.
Detects human faces, providing tight face bounding boxes for precise pan-tilt gimbal tracking.
"""

import logging
import os
from typing import List, Optional
import cv2
import numpy as np

from .base import BasePersonDetector
from .types import PersonDetection

logger = logging.getLogger("SmartVision.FaceDetector")

DEFAULT_YUNET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models",
    "face_detection_yunet_2023mar.onnx",
)


class FaceDetector(BasePersonDetector):
    """
    OpenCV YuNet face detector.
    Detects all visible human faces in the video frame with high accuracy and low latency.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        conf_thresh: float = 0.50,
        nms_thresh: float = 0.30,
        top_k: int = 5000,
    ):
        self.model_path = model_path or DEFAULT_YUNET_PATH
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.top_k = top_k
        self._detector: Optional[cv2.FaceDetectorYN] = None
        self._input_size = (640, 480)
        self._load_model()

    @property
    def name(self) -> str:
        return f"YuNetFaceDetector({os.path.basename(self.model_path)})"

    @property
    def is_ready(self) -> bool:
        return self._detector is not None

    def _load_model(self) -> None:
        if not os.path.exists(self.model_path):
            try:
                import urllib.request
                os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
                url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
                logger.info("Downloading YuNet face detection model (%s)...", url)
                urllib.request.urlretrieve(url, self.model_path)
            except Exception as e:
                logger.error("Failed to download YuNet face model: %s", e)
                raise FileNotFoundError(f"YuNet face model not found at: {self.model_path}") from e

        try:
            self._detector = cv2.FaceDetectorYN_create(
                model=self.model_path,
                config="",
                input_size=self._input_size,
                score_threshold=self.conf_thresh,
                nms_threshold=self.nms_thresh,
                top_k=self.top_k,
            )
            logger.info("YuNet face detector loaded successfully from %s", self.model_path)
        except Exception as e:
            logger.error("Failed to load YuNet face detector: %s", e)
            raise

    def detect(self, frame: np.ndarray, conf_thresh: Optional[float] = None) -> List[PersonDetection]:
        if frame is None or self._detector is None:
            return []

        h, w = frame.shape[:2]
        if (w, h) != self._input_size:
            self._input_size = (w, h)
            self._detector.setInputSize((w, h))

        thresh = conf_thresh if conf_thresh is not None else self.conf_thresh
        self._detector.setScoreThreshold(thresh)

        _, faces = self._detector.detect(frame)
        if faces is None:
            return []

        detections: List[PersonDetection] = []
        for face in faces:
            x, y, bw, bh = face[0:4]
            score = float(face[-1])

            x1 = max(0.0, float(x))
            y1 = max(0.0, float(y))
            x2 = min(float(w), float(x + bw))
            y2 = min(float(h), float(y + bh))

            if x2 > x1 and y2 > y1 and score >= thresh:
                detections.append(
                    PersonDetection(
                        x1=x1,
                        y1=y1,
                        x2=x2,
                        y2=y2,
                        confidence=round(score, 4),
                        class_id=0,
                        class_name="face",
                        raw_face=face,
                    )
                )

        return detections
