"""
SmartVision - Person Detector Abstract Base Interface
Defines the unified detection contract across YOLO models and mock simulators.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np

from vision.detection.types import PersonDetection


class BasePersonDetector(ABC):
    """
    Abstract contract for 2D person detection models.
    All implementations must return a list of PersonDetection instances.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Returns the human-readable identifier of the detector implementation."""
        pass

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """Returns True if the detector model is loaded and ready to infer."""
        pass

    @abstractmethod
    def detect(self, frame: np.ndarray, conf_thresh: Optional[float] = None) -> List[PersonDetection]:
        """
        Executes person detection on a BGR image frame.

        Args:
            frame: Input image array in BGR format (height, width, 3).
            conf_thresh: Optional override for the detection confidence threshold.

        Returns:
            List of PersonDetection objects filtered strictly to person class (COCO 0).
        """
        pass

    def close(self) -> None:
        """Releases detector resources and GPU/CPU memory if applicable."""
        pass

    def __enter__(self) -> "BasePersonDetector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
