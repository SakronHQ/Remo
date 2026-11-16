"""
SmartVision - High-Priority Double-Buffered Background Capture Thread
Continuously drains OpenCV video driver buffers to ensure zero-lag frame delivery,
calculates real-time FPS metrics, and tracks frame dropping.
"""

from collections import deque
import threading
import time
from typing import Any, Callable, Deque, Dict, Optional, Tuple, Union

import cv2
import numpy as np

from vision.camera.config import CameraConfig, FrameMetadata


class CameraCaptureThread:
    """
    Decoupled background thread that drains the camera capture buffer as fast
    as frames are produced. Solves OpenCV's multi-frame driver lag by guaranteeing
    that any consumer asking for a frame receives the freshest frame available.
    """

    def __init__(
        self,
        cap: Union[cv2.VideoCapture, Any],
        config: CameraConfig,
        on_error_callback: Optional[Callable[[int], None]] = None,
        source_name: str = "camera",
    ):
        self.cap = cap
        self.config = config
        self.on_error_callback = on_error_callback
        self.source_name = source_name

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Double-buffer storage
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_metadata: Optional[FrameMetadata] = None
        self._readers_for_current_frame = 0

        # Telemetry & metrics
        self._frame_id = 0
        self._dropped_frames = 0
        self._consecutive_errors = 0
        self._start_time = 0.0
        self._recent_timestamps: Deque[float] = deque(maxlen=60)
        self._fps_measured: float = 0.0

    @property
    def is_running(self) -> bool:
        """Returns True if capture thread is active."""
        return self._running

    def start(self) -> None:
        """Starts the background capture loop."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._start_time = time.time()
            self._frame_id = 0
            self._dropped_frames = 0
            self._consecutive_errors = 0
            self._recent_timestamps.clear()

        self._thread = threading.Thread(
            target=self._capture_loop,
            name="SmartVision-CameraCaptureThread",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Stops the capture thread and waits for join."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._condition.notify_all()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def update_capture_source(
        self,
        new_cap: Union[cv2.VideoCapture, Any],
        source_name: str,
    ) -> None:
        """
        Hot-swaps the video capture source (e.g., when falling back to synthetic
        or recovering physical camera) without interrupting consumers.
        """
        with self._lock:
            old_cap = self.cap
            self.cap = new_cap
            self.source_name = source_name
            self._consecutive_errors = 0

        # Release old capture device outside the lock if possible
        if old_cap and hasattr(old_cap, "release") and old_cap is not new_cap:
            try:
                old_cap.release()
            except Exception:
                pass

    def _capture_loop(self) -> None:
        """Tight loop continuously draining video frames."""
        while self._running:
            cap_obj = self.cap
            if cap_obj is None:
                time.sleep(0.01)
                continue

            try:
                ret, frame = cap_obj.read()
            except Exception:
                ret = False
                frame = None

            now_utc = time.time()
            now_mono = time.monotonic()

            if not ret or frame is None:
                with self._lock:
                    self._consecutive_errors += 1
                    error_count = self._consecutive_errors

                if self.on_error_callback and error_count >= self.config.max_consecutive_errors:
                    self.on_error_callback(error_count)

                # Avoid 100% spin if camera is disconnected
                time.sleep(0.015)
                continue

            # Frame successfully retrieved
            h, w = frame.shape[:2]

            with self._lock:
                self._consecutive_errors = 0

                # If previous frame had zero readers before being superseded, record as dropped
                if self._frame_id > 0 and self._readers_for_current_frame == 0:
                    self._dropped_frames += 1

                self._frame_id += 1
                self._readers_for_current_frame = 0

                # Update rolling FPS
                self._recent_timestamps.append(now_mono)
                if len(self._recent_timestamps) >= 2:
                    delta = self._recent_timestamps[-1] - self._recent_timestamps[0]
                    if delta > 0.0001:
                        self._fps_measured = (len(self._recent_timestamps) - 1) / delta

                # Build frame metadata
                is_synthetic = "synthetic" in self.source_name.lower()
                metadata = FrameMetadata(
                    frame_id=self._frame_id,
                    timestamp_utc=now_utc,
                    monotonic_time=now_mono,
                    width=w,
                    height=h,
                    fps_measured=round(self._fps_measured, 1),
                    dropped_frames=self._dropped_frames,
                    is_synthetic=is_synthetic,
                    source=self.source_name,
                )

                # Store latest frame in double-buffer
                self._latest_frame = frame
                self._latest_metadata = metadata
                self._condition.notify_all()

    def get_latest_frame(
        self,
        timeout: Optional[float] = 1.0,
        wait_for_new: bool = False,
        last_frame_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMetadata]]:
        """
        Retrieves the freshest available frame from the double buffer.
        
        Args:
            timeout: Maximum seconds to wait (None to wait indefinitely).
            wait_for_new: If True and last_frame_id is None, waits for a new frame
                produced after this method was invoked.
            last_frame_id: If provided, waits until a frame with frame_id > last_frame_id
                arrives. This enables arbitrary concurrent consumers to receive each frame
                without stealing frames or race conditions.
        """
        with self._condition:
            if not self._running:
                return False, None, None

            if last_frame_id is not None:
                # Wait until frame_id advances past caller's previous frame
                notified = self._condition.wait_for(
                    lambda: (self._frame_id > last_frame_id) or not self._running,
                    timeout=timeout,
                )
                if not notified or not self._running or self._latest_frame is None:
                    return False, None, None

            elif wait_for_new:
                # Wait for next fresh frame produced after this invocation
                target_id = self._frame_id
                notified = self._condition.wait_for(
                    lambda: (self._frame_id > target_id) or not self._running,
                    timeout=timeout,
                )
                if not notified or not self._running or self._latest_frame is None:
                    return False, None, None

            else:
                # Immediate read of freshest frame; wait only if no frame has ever arrived
                if self._latest_frame is None:
                    notified = self._condition.wait_for(
                        lambda: self._latest_frame is not None or not self._running,
                        timeout=timeout,
                    )
                    if not notified or self._latest_frame is None or not self._running:
                        return False, None, None

            self._readers_for_current_frame += 1
            return True, self._latest_frame.copy(), self._latest_metadata

    def get_latest_frame_nowait(
        self,
        copy: bool = False,
    ) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMetadata]]:
        """
        Non-blocking read of the latest frame from the double-buffer.
        Set copy=True if caller intends to modify the array in-place.
        """
        with self._lock:
            if not self._running or self._latest_frame is None:
                return False, None, None
            self._readers_for_current_frame += 1
            frame_out = self._latest_frame.copy() if copy else self._latest_frame
            return True, frame_out, self._latest_metadata

    def get_stats(self) -> Dict[str, Any]:
        """Returns thread runtime telemetry and health status."""
        with self._lock:
            uptime = time.time() - self._start_time if self._start_time > 0 else 0.0
            return {
                "is_running": self._running,
                "frame_id": self._frame_id,
                "dropped_frames": self._dropped_frames,
                "consecutive_errors": self._consecutive_errors,
                "fps_measured": round(self._fps_measured, 2),
                "uptime_seconds": round(uptime, 2),
                "source": self.source_name,
            }
