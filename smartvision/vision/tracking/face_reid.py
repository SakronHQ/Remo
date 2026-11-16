"""
SmartVision - Face Re-Identification & Persistent Target Memory
Uses OpenCV SFace (cv2.FaceRecognizerSF) to extract 128-d face embeddings and SQLite
to persist active locked target signatures across occlusions, frame exits, and restarts.
"""

import logging
import os
import sqlite3
from typing import Any, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("SmartVision.FaceReID")

DEFAULT_SFACE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models",
    "face_recognition_sface_2021dec.onnx",
)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "face_memory.db",
)


class FaceMemory:
    """
    SQLite-backed single-target face identity memory.
    Stores exactly one active target embedding (row id=1) to ensure zero schema overhead
    and seamless re-acquisition when a locked target re-enters camera view.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._cached_embedding: Optional[np.ndarray] = None
        self._init_db()
        self._load_cache()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS active_target (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    embedding BLOB NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _load_cache(self) -> None:
        cursor = self._conn.cursor()
        cursor.execute("SELECT embedding FROM active_target WHERE id = 1")
        row = cursor.fetchone()
        if row and row[0]:
            try:
                arr = np.frombuffer(row[0], dtype=np.float32).reshape(1, 128)
                self._cached_embedding = arr
                logger.info("Loaded persistent active target face signature from %s", self.db_path)
            except Exception as e:
                logger.warning("Failed to deserialize face embedding from DB: %s", e)
                self._cached_embedding = None

    def save_target(self, embedding: np.ndarray) -> None:
        """Persists or replaces the active target embedding."""
        if embedding is None:
            return
        arr = np.ascontiguousarray(embedding, dtype=np.float32).reshape(1, 128)
        blob = arr.tobytes()
        import time
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO active_target (id, embedding, updated_at) VALUES (1, ?, ?)",
                (blob, time.time()),
            )
        self._cached_embedding = arr

    def get_target(self) -> Optional[np.ndarray]:
        """Returns the current active target embedding, if any."""
        return self._cached_embedding

    def has_target(self) -> bool:
        """Checks if a target embedding is stored."""
        return self._cached_embedding is not None

    def clear(self) -> None:
        """Clears active target memory."""
        with self._conn:
            self._conn.execute("DELETE FROM active_target WHERE id = 1")
        self._cached_embedding = None

    def close(self) -> None:
        """Closes SQLite connection cleanly."""
        try:
            self._conn.close()
        except Exception:
            pass


class FaceReID:
    """
    Lightweight facial embedding extractor and matcher powered by OpenCV SFace.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        db_path: Optional[str] = None,
        match_thresh: float = 0.45,
    ):
        self.model_path = model_path or DEFAULT_SFACE_PATH
        self.match_thresh = match_thresh
        self.memory = FaceMemory(db_path=db_path)
        self._recognizer: Optional[cv2.FaceRecognizerSF] = None
        self._load_model()

    @property
    def is_ready(self) -> bool:
        return self._recognizer is not None

    def close(self) -> None:
        """Closes memory resources cleanly."""
        if self.memory is not None:
            self.memory.close()

    def _load_model(self) -> None:
        if not os.path.exists(self.model_path):
            try:
                import urllib.request
                os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
                url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
                logger.info("Downloading SFace face recognition model (%s)...", url)
                urllib.request.urlretrieve(url, self.model_path)
            except Exception as e:
                logger.warning("Failed to download SFace model: %s. Re-ID will be disabled.", e)
                return

        try:
            self._recognizer = cv2.FaceRecognizerSF.create(self.model_path, "")
            logger.info("SFace face recognition model loaded successfully from %s", self.model_path)
        except Exception as e:
            logger.warning("Failed to initialize FaceRecognizerSF: %s", e)
            self._recognizer = None

    def extract_embedding(self, frame: np.ndarray, raw_face: Any) -> Optional[np.ndarray]:
        """
        Aligns, crops, and extracts a 128-d face embedding from frame using YuNet raw_face landmarks.
        """
        if self._recognizer is None or frame is None or raw_face is None:
            return None
        try:
            aligned = self._recognizer.alignCrop(frame, raw_face)
            feat = self._recognizer.feature(aligned)
            return feat
        except Exception as e:
            logger.debug("Failed to extract face embedding: %s", e)
            return None

    def match(self, feat1: np.ndarray, feat2: np.ndarray) -> float:
        """
        Calculates cosine similarity between two face feature vectors.
        """
        if feat1 is None or feat2 is None:
            return -1.0
        if self._recognizer is not None:
            try:
                return float(self._recognizer.match(feat1, feat2, cv2.FaceRecognizerSF_FR_COSINE))
            except Exception:
                pass
        # Fallback pure numpy cosine similarity
        f1 = feat1.flatten()
        f2 = feat2.flatten()
        norm1 = np.linalg.norm(f1)
        norm2 = np.linalg.norm(f2)
        if norm1 < 1e-6 or norm2 < 1e-6:
            return -1.0
        return float(np.dot(f1, f2) / (norm1 * norm2))

    def is_match(self, feat1: np.ndarray, feat2: np.ndarray) -> bool:
        """Returns True if cosine similarity exceeds match threshold."""
        return self.match(feat1, feat2) >= self.match_thresh
