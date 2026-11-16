"""
SmartVision - Central System State Manager
Thread-safe and asyncio-aware centralized state repository. Maintains real-time
telemetry snapshots, sensor states, tracking outputs, camera status, and frame buffers.
"""

import asyncio
from collections import deque
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..config import settings


class SystemStateManager:
    """
    Central state container coordinating telemetry, sensor readings,
    autonomous tracking results, manual control arbitration, and video frame distribution.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()

        # ESP32-S3 Firmware Connection & Telemetry
        self.esp32_connected = False
        self.esp32_ip: Optional[str] = None
        self.esp32_connected_at_ms: Optional[int] = None
        self.esp32_last_heartbeat_ms: Optional[int] = None
        self.esp32_rtt_ms: Optional[int] = None
        self.failsafe_active = False
        self.estop_active = False

        # Sensor readings (from ESP32 telem.sensors)
        self.sonar_data: Dict[str, Any] = {
            "distance_cm": -1.0,
            "valid": False,
            "status": "waiting_data",
        }
        self.pir_data: Dict[str, Any] = {
            "motion_detected": False,
            "trigger_count": 0,
            "last_trigger_ms": 0,
        }
        self.servo_data: Dict[str, Any] = {
            "pan_angle": settings.PAN_HOME,
            "tilt_angle": settings.TILT_HOME,
            "pan_target": settings.PAN_HOME,
            "tilt_target": settings.TILT_HOME,
            "is_moving": False,
        }
        self.buzzer_data: Dict[str, Any] = {
            "active": False,
            "pattern": "off",
        }
        self.esp32_system_data: Dict[str, Any] = {
            "uptime_ms": 0,
            "rssi_dbm": 0,
            "free_heap_bytes": 0,
            "psram_free_bytes": 0,
            "cpu_temp_c": 0.0,
        }

        # Camera subsystem status
        self.camera_running = False
        self.camera_fps = 0.0
        self.camera_is_synthetic = False
        self.camera_width = settings.CAMERA_WIDTH
        self.camera_height = settings.CAMERA_HEIGHT
        self.camera_dropped_frames = 0

        # Computer Vision & Tracking Engine State
        self.tracking_mode = "idle"  # idle, auto_track, manual, patrol
        self.target_locked = False
        self.active_track_id: Optional[int] = None
        self.tracks_count = 0
        self.inference_ms = 0.0
        self.tracking_fps = 0.0
        self.active_target: Optional[Dict[str, Any]] = None
        self.all_detections: List[Dict[str, Any]] = []

        # Recent alerts ring buffer
        self.alerts: Deque[Dict[str, Any]] = deque(maxlen=50)

        # Video frame caching for MJPEG streamer
        self.latest_jpeg_bytes: Optional[bytes] = None
        self.latest_frame_id: int = 0
        self._frame_condition: Optional[asyncio.Condition] = None
        self._new_frame_event = asyncio.Event()

    def _get_condition(self) -> asyncio.Condition:
        if self._frame_condition is None:
            self._frame_condition = asyncio.Condition()
        return self._frame_condition

    def update_esp32_connection(self, connected: bool, ip: Optional[str] = None) -> None:
        """Updates hardware connection status and timestamps."""
        with self._lock:
            self.esp32_connected = connected
            now_ms = int(time.time() * 1000)
            if connected:
                self.esp32_ip = ip
                self.esp32_connected_at_ms = now_ms
                self.esp32_last_heartbeat_ms = now_ms
                self.failsafe_active = False
            else:
                self.esp32_last_heartbeat_ms = None
                self.esp32_rtt_ms = None
                self.failsafe_active = True

    def record_heartbeat(self) -> None:
        """Pets communication watchdog timestamp."""
        with self._lock:
            self.esp32_last_heartbeat_ms = int(time.time() * 1000)
            if self.failsafe_active:
                self.failsafe_active = False

    def update_esp32_pong(self, echo_ts: int, rtt_ms: int) -> None:
        """Updates latency measurement from sys.pong response."""
        with self._lock:
            self.esp32_last_heartbeat_ms = int(time.time() * 1000)
            self.esp32_rtt_ms = rtt_ms

    def update_esp32_telemetry(self, payload: Dict[str, Any]) -> None:
        """Ingests telem.sensors payload from ESP32."""
        with self._lock:
            self.esp32_last_heartbeat_ms = int(time.time() * 1000)
            if "sonar" in payload:
                self.sonar_data = payload["sonar"]
            if "pir" in payload:
                self.pir_data = payload["pir"]
            if "servos" in payload:
                self.servo_data = payload["servos"]
            if "buzzer" in payload:
                self.buzzer_data = payload["buzzer"]
            if "system" in payload:
                sys_payload = payload["system"]
                self.esp32_system_data = sys_payload
                if "failsafe_active" in sys_payload:
                    self.failsafe_active = sys_payload["failsafe_active"]
                if "estop_active" in sys_payload:
                    self.estop_active = sys_payload["estop_active"]

    def update_camera_status(self, stats: Dict[str, Any]) -> None:
        """Updates camera diagnostic metrics."""
        with self._lock:
            self.camera_running = stats.get("is_running", self.camera_running)
            self.camera_fps = stats.get("fps_actual", self.camera_fps)
            self.camera_is_synthetic = stats.get("is_synthetic", self.camera_is_synthetic)
            self.camera_dropped_frames = stats.get("dropped_frames", self.camera_dropped_frames)

    def update_tracking_state(
        self,
        mode: str,
        locked: bool,
        active_track_id: Optional[int],
        tracks_count: int,
        inference_ms: float,
        fps: float,
        active_target: Optional[Dict[str, Any]],
        all_detections: List[Dict[str, Any]],
    ) -> None:
        """Updates computer vision and tracking metrics."""
        with self._lock:
            self.tracking_mode = mode
            self.target_locked = locked
            self.active_track_id = active_track_id
            self.tracks_count = tracks_count
            self.inference_ms = inference_ms
            self.tracking_fps = fps
            self.active_target = active_target
            self.all_detections = all_detections

    def set_estop(self, active: bool, reason: str = "") -> None:
        """Sets or resets emergency stop."""
        with self._lock:
            self.estop_active = active
            if active:
                self.add_alert_unlocked({
                    "event_id": f"estop_{int(time.time()*1000)}",
                    "event_type": "estop_activated",
                    "severity": "critical",
                    "source": "backend",
                    "message": f"Emergency Stop Triggered: {reason or 'operator command'}",
                    "timestamp": int(time.time() * 1000),
                })

    def set_tracking_mode(self, mode: str) -> None:
        """Updates tracking operating mode."""
        with self._lock:
            self.tracking_mode = mode

    def add_alert(self, alert: Dict[str, Any]) -> None:
        """Records an alert in the ring buffer."""
        with self._lock:
            self.add_alert_unlocked(alert)

    def add_alert_unlocked(self, alert: Dict[str, Any]) -> None:
        """Internal helper to add alert assuming lock is held."""
        if "timestamp" not in alert:
            alert["timestamp"] = int(time.time() * 1000)
        self.alerts.append(alert)

    def set_frame(self, jpeg_bytes: bytes, frame_id: int) -> None:
        """Stores the latest encoded JPEG frame and signals waiting MJPEG streams."""
        with self._lock:
            self.latest_jpeg_bytes = jpeg_bytes
            self.latest_frame_id = frame_id
        # Signal async listeners outside lock
        self._new_frame_event.set()
        self._new_frame_event.clear()

        # Signal condition variable
        try:
            loop = asyncio.get_running_loop()
            cond = self._get_condition()

            async def _notify():
                async with cond:
                    cond.notify_all()

            loop.create_task(_notify())
        except RuntimeError:
            pass

    async def wait_for_frame(self, last_frame_id: int = -1, timeout: float = 0.5) -> Tuple[Optional[bytes], int]:
        """
        Awaits the arrival of a newly processed video frame newer than last_frame_id.
        If a newer frame is already cached, returns immediately without waiting.
        """
        with self._lock:
            if self.latest_frame_id > last_frame_id and self.latest_jpeg_bytes is not None:
                return self.latest_jpeg_bytes, self.latest_frame_id

        cond = self._get_condition()
        start_t = time.monotonic()
        try:
            async with cond:
                while True:
                    with self._lock:
                        if self.latest_frame_id > last_frame_id and self.latest_jpeg_bytes is not None:
                            return self.latest_jpeg_bytes, self.latest_frame_id

                    remaining = timeout - (time.monotonic() - start_t)
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(cond.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        break

            with self._lock:
                return self.latest_jpeg_bytes, self.latest_frame_id
        except Exception:
            with self._lock:
                return self.latest_jpeg_bytes, self.latest_frame_id

    async def wait_for_next_frame(self, timeout: float = 0.5) -> Optional[bytes]:
        """Async generator helper that awaits the arrival of a newly processed video frame."""
        frame_bytes, _ = await self.wait_for_frame(last_frame_id=-1, timeout=timeout)
        return frame_bytes

    def get_status_snapshot(self) -> Dict[str, Any]:
        """Produces a JSON-serializable snapshot of overall system health."""
        with self._lock:
            now = time.time()
            uptime_s = round(now - self.start_time, 2)
            now_ms = int(now * 1000)

            return {
                "timestamp": now_ms,
                "uptime_s": uptime_s,
                "estop_active": self.estop_active,
                "esp32": {
                    "connected": self.esp32_connected,
                    "ip": self.esp32_ip,
                    "connected_at_ms": self.esp32_connected_at_ms,
                    "last_heartbeat_ms": self.esp32_last_heartbeat_ms,
                    "rtt_ms": self.esp32_rtt_ms,
                    "failsafe_active": self.failsafe_active,
                    "estop_active": self.estop_active,
                },
                "camera": {
                    "running": self.camera_running,
                    "fps": round(self.camera_fps, 1),
                    "synthetic": self.camera_is_synthetic,
                    "width": self.camera_width,
                    "height": self.camera_height,
                    "dropped_frames": self.camera_dropped_frames,
                },
                "tracking": {
                    "mode": self.tracking_mode,
                    "locked": self.target_locked,
                    "active_track_id": self.active_track_id,
                    "tracks_count": self.tracks_count,
                    "inference_ms": round(self.inference_ms, 1),
                    "fps": round(self.tracking_fps, 1),
                    "active_target": self.active_target,
                },
                "sensors": {
                    "sonar": self.sonar_data,
                    "pir": self.pir_data,
                    "servos": self.servo_data,
                    "buzzer": self.buzzer_data,
                    "system": self.esp32_system_data,
                },
            }
