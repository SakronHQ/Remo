"""
SmartVision - Person Detection Data Structures
Represents detected person bounding boxes, confidence scores, and centroid geometry.
"""

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class PersonDetection:
    """
    Immutable representation of a single detected person within a video frame.
    Coordinates are represented in standard image space (x: left-to-right, y: top-to-bottom).
    """

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_id: int = 0
    class_name: str = "person"

    def __post_init__(self):
        # Validate geometry ordering
        min_x = min(self.x1, self.x2)
        max_x = max(self.x1, self.x2)
        min_y = min(self.y1, self.y2)
        max_y = max(self.y1, self.y2)
        object.__setattr__(self, "x1", float(min_x))
        object.__setattr__(self, "x2", float(max_x))
        object.__setattr__(self, "y1", float(min_y))
        object.__setattr__(self, "y2", float(max_y))

    @property
    def width(self) -> float:
        """Bounding box pixel width."""
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        """Bounding box pixel height."""
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        """Bounding box pixel area."""
        return self.width * self.height

    @property
    def aspect_ratio(self) -> float:
        """Width-to-height aspect ratio."""
        return self.width / max(1e-6, self.height)

    @property
    def centroid(self) -> Tuple[float, float]:
        """Centroid coordinates (cx, cy) in pixels."""
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        """Integer bounding box tuple (x1, y1, x2, y2)."""
        return (int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2)))

    @property
    def bbox_float(self) -> Tuple[float, float, float, float]:
        """Float bounding box tuple (x1, y1, x2, y2)."""
        return (self.x1, self.y1, self.x2, self.y2)

    def to_tlwh(self) -> Tuple[float, float, float, float]:
        """Returns top-left-width-height tuple (x1, y1, w, h)."""
        return (self.x1, self.y1, self.width, self.height)

    def to_xyxy(self) -> Tuple[float, float, float, float]:
        """Returns corner coordinates (x1, y1, x2, y2)."""
        return (self.x1, self.y1, self.x2, self.y2)

    def normalized(self, frame_w: int, frame_h: int) -> Tuple[float, float, float, float]:
        """Returns normalized bounding box [nx1, ny1, nx2, ny2] in [0.0, 1.0]."""
        w = max(1.0, float(frame_w))
        h = max(1.0, float(frame_h))
        return (
            max(0.0, min(1.0, self.x1 / w)),
            max(0.0, min(1.0, self.y1 / h)),
            max(0.0, min(1.0, self.x2 / w)),
            max(0.0, min(1.0, self.y2 / h)),
        )

    def to_dict(self, frame_w: int = 640, frame_h: int = 480) -> Dict[str, Any]:
        """Serializes detection to JSON-compatible dictionary."""
        norm = self.normalized(frame_w, frame_h)
        cx, cy = self.centroid
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": round(float(self.confidence), 4),
            "bbox": [int(round(self.x1)), int(round(self.y1)), int(round(self.x2)), int(round(self.y2))],
            "bbox_normalized": [round(v, 4) for v in norm],
            "centroid": [round(cx, 1), round(cy, 1)],
            "centroid_normalized": [round(cx / frame_w, 4), round(cy / frame_h, 4)],
            "area": round(self.area, 1),
        }
