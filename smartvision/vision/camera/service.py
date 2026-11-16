"""
SmartVision - Modular Camera Ingestion Service
Manages physical UVC camera capture, automatic reconnection, graceful synthetic
fallback on disconnect, and real-time operational telemetry.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union

import cv2
import numpy as np

from vision.camera.capture_thread import CameraCaptureThread
from vision.camera.config import (
    CameraBackend,
    CameraConfig,
    FrameMetadata,
)
from vision.camera.synthetic import SyntheticCamera

logger = logging.getLogger("SmartVision.CameraService")


class CameraService:
    """
    Central camera subsystem service. Coordinates capture threads, device probing,
    dynamic synthetic failover, and auto-reconnection.
    """

    def __init__(self, config: Optional[CameraConfig] = None):
        self.config = config or CameraConfig()
        self._lock = threading.Lock()
        self._is_running = False
        self._is_synthetic = False
        self._is_forced_synthetic = (self.config.backend == CameraBackend.SYNTHETIC)

        self._active_cap: Optional[Union[cv2.VideoCapture, SyntheticCamera]] = None
        self._capture_thread: Optional[CameraCaptureThread] = None

        # Reconnection worker
        self._reconnect_thread: Optional[threading.Thread] = None
        self._reconnect_event = threading.Event()
        self._stop_reconnect = threading.Event()

    @property
    def is_running(self) -> bool:
        """Returns True if camera service is actively running."""
        return self._is_running

    @property
    def is_synthetic(self) -> bool:
        """Returns True if the active video source is the synthetic fallback generator."""
        return self._is_synthetic

    def start(self) -> "CameraService":
        """
        Initializes video capture device and starts the decoupled capture thread.
        Falls back to synthetic pattern if physical device cannot be opened.
        """
        with self._lock:
            if self._is_running:
                return self

            # 1. Open primary capture device or fallback
            cap, is_synthetic = self._open_video_source()
            self._active_cap = cap
            self._is_synthetic = is_synthetic

            # 2. Instantiate and start capture thread
            source_name = "synthetic" if is_synthetic else f"cam_{self.config.device_index}"
            self._capture_thread = CameraCaptureThread(
                cap=cap,
                config=self.config,
                on_error_callback=self._on_capture_error,
                source_name=source_name,
            )
            self._capture_thread.start()
            self._is_running = True

            # 3. Start auto-reconnection daemon if enabled
            if self.config.auto_reconnect:
                self._stop_reconnect.clear()
                self._reconnect_thread = threading.Thread(
                    target=self._reconnect_worker,
                    name="SmartVision-CameraReconnectWorker",
                    daemon=True,
                )
                self._reconnect_thread.start()

            logger.info(
                f"CameraService started [source={source_name}, resolution={self.config.width}x{self.config.height}, "
                f"fps={self.config.fps}, synthetic={self._is_synthetic}]"
            )
            return self

    def stop(self) -> None:
        """
        Stops background capture threads and safely releases video hardware.
        """
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

            # Signal reconnect worker to stop
            self._stop_reconnect.set()
            self._reconnect_event.set()

        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=3.0)
        self._reconnect_thread = None

        # Stop capture thread
        if self._capture_thread:
            self._capture_thread.stop(timeout=2.0)
            self._capture_thread = None

        # Release capture device
        if self._active_cap and hasattr(self._active_cap, "release"):
            try:
                self._active_cap.release()
            except Exception:
                pass
            self._active_cap = None

        logger.info("CameraService stopped cleanly.")

    def __enter__(self) -> "CameraService":
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _open_hardware_device(self) -> Optional[cv2.VideoCapture]:
        """
        Attempts to open and configure the physical camera hardware device.
        Returns initialized cv2.VideoCapture on success, or None on failure.
        """
        cv_backend = CameraBackend.resolve_cv_backend(self.config.backend)
        try:
            cap = cv2.VideoCapture(self.config.device_index, cv_backend)
            if cap.isOpened():
                if self.config.fourcc and len(self.config.fourcc) == 4:
                    cap.set(cv2.CAP_PROP_FOURCC, self.config.get_fourcc_int())

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
                cap.set(cv2.CAP_PROP_FPS, self.config.fps)

                if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, self.config.buffer_size)

                ret, frame = cap.read()
                if ret and frame is not None:
                    return cap

                cap.release()
        except Exception as e:
            logger.warning(f"Error opening physical camera index {self.config.device_index}: {e}")

        return None

    def _open_video_source(self) -> Tuple[Union[cv2.VideoCapture, SyntheticCamera], bool]:
        """
        Attempts to open hardware camera. Returns (capture_obj, is_synthetic).
        """
        if self._is_forced_synthetic or self.config.backend == CameraBackend.SYNTHETIC:
            return self._create_synthetic_source(), True

        hw_cap = self._open_hardware_device()
        if hw_cap is not None:
            return hw_cap, False

        # If we reach here, hardware camera could not be opened
        if self.config.enable_synthetic_fallback:
            logger.warning(
                f"Physical camera (index {self.config.device_index}) unavailable. "
                "Engaging synthetic test pattern fallback generator."
            )
            return self._create_synthetic_source(), True
        else:
            raise RuntimeError(
                f"Unable to open physical camera at index {self.config.device_index} and fallback is disabled."
            )

    def _create_synthetic_source(self) -> SyntheticCamera:
        """Instantiates synthetic test pattern generator."""
        return SyntheticCamera(
            width=self.config.width,
            height=self.config.height,
            fps=self.config.fps,
            pattern=self.config.synthetic_pattern,
            realtime_pacing=True,
        )

    def _on_capture_error(self, consecutive_errors: int) -> None:
        """
        Invoked by CameraCaptureThread when consecutive read errors reach threshold.
        """
        with self._lock:
            if not self._is_running:
                return

            if not self.config.enable_synthetic_fallback:
                logger.error(
                    f"Camera read failed {consecutive_errors} consecutive times! "
                    "Synthetic fallback is disabled."
                )
                if self.config.auto_reconnect:
                    self._reconnect_event.set()
                return

            if self._is_synthetic:
                return

            logger.error(
                f"Camera read failed {consecutive_errors} consecutive times! "
                "Triggering failover to synthetic fallback generator."
            )
            self._is_synthetic = True

            # Swap to synthetic camera in capture thread
            synthetic_cam = self._create_synthetic_source()
            if self._capture_thread:
                self._capture_thread.update_capture_source(synthetic_cam, "synthetic_fallback")
            self._active_cap = synthetic_cam

            # Awaken reconnect worker immediately
            self._reconnect_event.set()

    def _attempt_reconnect_to_hardware(self) -> bool:
        """
        Attempts to probe and reconnect to physical camera hardware.
        Returns True if hardware was successfully restored.
        """
        if self._is_forced_synthetic or self.config.backend == CameraBackend.SYNTHETIC or not self._is_running:
            return False

        test_cap = self._open_hardware_device()
        if test_cap is not None:
            with self._lock:
                if self._capture_thread and self._is_running and not self._is_forced_synthetic:
                    logger.info(
                        f"Physical camera {self.config.device_index} reconnected successfully! "
                        "Restoring hardware video stream."
                    )
                    self._capture_thread.update_capture_source(
                        test_cap, f"cam_{self.config.device_index}"
                    )
                    self._active_cap = test_cap
                    self._is_synthetic = False
                    test_cap = None  # Ownership successfully transferred
                    return True

            # If not adopted (e.g., service was stopped in the interim), release device
            if test_cap is not None:
                try:
                    test_cap.release()
                except Exception:
                    pass

        return False

    def _reconnect_worker(self) -> None:
        """
        Background worker that periodically probes for camera reconnection
        when the system is running in fallback mode.
        """
        while not self._stop_reconnect.is_set():
            # Wait until signaled by error/unforce OR timeout for periodic retry
            signaled = self._reconnect_event.wait(timeout=self.config.reconnect_interval_s)
            self._reconnect_event.clear()

            if self._stop_reconnect.is_set():
                break

            if not self._is_running or not self._is_synthetic or self._is_forced_synthetic:
                continue

            self._attempt_reconnect_to_hardware()

    def get_frame(
        self,
        timeout: Optional[float] = 1.0,
        wait_for_new: bool = False,
        last_frame_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMetadata]]:
        """
        Fetches the freshest available video frame and metadata.
        Pass last_frame_id to guarantee receiving new frames without race conditions.
        """
        if not self._is_running or not self._capture_thread:
            return False, None, None
        return self._capture_thread.get_latest_frame(
            timeout=timeout,
            wait_for_new=wait_for_new,
            last_frame_id=last_frame_id,
        )

    def get_frame_nowait(
        self,
        copy: bool = False,
    ) -> Tuple[bool, Optional[np.ndarray], Optional[FrameMetadata]]:
        """
        Instantaneous non-blocking read of the latest frame.
        """
        if not self._is_running or not self._capture_thread:
            return False, None, None
        return self._capture_thread.get_latest_frame_nowait(copy=copy)

    def set_forced_synthetic(self, enabled: bool) -> None:
        """
        Manually forces or releases synthetic fallback mode for testing failover.
        """
        with self._lock:
            if self._is_forced_synthetic == enabled:
                return
            self._is_forced_synthetic = enabled

            if enabled:
                self._is_synthetic = True
                synthetic_cam = self._create_synthetic_source()
                if self._capture_thread:
                    self._capture_thread.update_capture_source(synthetic_cam, "forced_synthetic")
                self._active_cap = synthetic_cam
            else:
                self._is_synthetic = True  # Remains synthetic until hardware reconnection succeeds

        if not enabled:
            # Immediately attempt to restore hardware stream
            restored = self._attempt_reconnect_to_hardware()
            if not restored:
                # Signal background worker to keep trying
                self._reconnect_event.set()

    def get_stats(self) -> Dict[str, Any]:
        """
        Returns full camera subsystem operational telemetry and metrics.
        """
        thread_stats = self._capture_thread.get_stats() if self._capture_thread else {}
        return {
            "is_running": self._is_running,
            "is_synthetic": self._is_synthetic,
            "is_forced_synthetic": self._is_forced_synthetic,
            "device_index": self.config.device_index,
            "configured_resolution": [self.config.width, self.config.height],
            "configured_fps": self.config.fps,
            "fourcc": self.config.fourcc,
            "fps_actual": thread_stats.get("fps_measured", 0.0),
            "total_frames": thread_stats.get("frame_id", 0),
            "dropped_frames": thread_stats.get("dropped_frames", 0),
            "uptime_seconds": thread_stats.get("uptime_seconds", 0.0),
            "source": thread_stats.get("source", "none"),
        }
