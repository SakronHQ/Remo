"""
SmartVision - Asynchronous Tracking Worker
Continuously captures video frames from CameraService, runs YOLO person detection,
ByteTrack association, target selection, and dual-axis PID control.
Dispatches servo actuation commands to ESP32-S3 and broadcasts live telemetry to operators.
"""

import asyncio
import logging
import time
from typing import Optional

import cv2
import numpy as np

from vision.camera.service import CameraService
from vision.tracking.pipeline import TrackingPipeline, TrackingPipelineResult
from vision.tracking.target_selector import TargetState

from ..config import settings
from .connection_hub import ConnectionHub
from .state_manager import SystemStateManager

logger = logging.getLogger("SmartVision.TrackingWorker")


class TrackingWorker:
    """
    Decoupled asynchronous worker driving the closed-loop computer vision pipeline.
    """

    def __init__(
        self,
        camera_service: CameraService,
        tracking_pipeline: TrackingPipeline,
        state_manager: SystemStateManager,
        hub: ConnectionHub,
    ):
        self.camera_service = camera_service
        self.pipeline = tracking_pipeline
        self.state = state_manager
        self.hub = hub

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_frame_id: Optional[int] = None
        self._last_servo_cmd_time = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Starts background tracking loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._worker_loop(), name="VisionTrackingWorker")
            logger.info("Vision tracking worker started")

    async def stop(self) -> None:
        """Stops background tracking loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Vision tracking worker stopped")

    async def _worker_loop(self) -> None:
        """Main async vision processing loop."""
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), settings.MJPEG_QUALITY]

        while self._running:
            try:
                if not self.camera_service.is_running:
                    await asyncio.sleep(0.05)
                    continue

                # 1. Fetch fresh frame from CameraService without blocking asyncio loop
                success, frame, metadata = await asyncio.to_thread(
                    self.camera_service.get_frame,
                    timeout=0.05,
                    last_frame_id=self._last_frame_id,
                )

                if not success or frame is None or metadata is None:
                    await asyncio.sleep(0.01)
                    continue

                self._last_frame_id = metadata.frame_id
                ts_sec = getattr(metadata, "timestamp_captured", getattr(metadata, "timestamp_utc", time.time()))
                ts_ms = ts_sec * 1000.0

                # 2. Process frame through full vision & tracking pipeline in thread pool
                result: TrackingPipelineResult = await asyncio.to_thread(
                    self.pipeline.process_frame,
                    frame=frame,
                    timestamp_captured_ms=ts_ms,
                )

                # 3. Encode annotated frame for MJPEG distribution
                annotated = result.frame_annotated
                ret, jpeg_buf = await asyncio.to_thread(cv2.imencode, ".jpg", annotated, encode_params)
                if ret:
                    self.state.set_frame(jpeg_buf.tobytes(), metadata.frame_id)

                # 4. Synchronize camera metrics
                cam_stats = self.camera_service.get_stats()
                self.state.update_camera_status(cam_stats)

                # 5. Update central state manager
                telem_payload = result.telemetry_message.get("payload", {})
                target_locked = result.target_result.state in (TargetState.TRACKING, TargetState.COASTING)
                self.state.update_tracking_state(
                    mode=self.pipeline.selector.mode,
                    locked=target_locked,
                    active_track_id=result.target_result.locked_track_id,
                    tracks_count=len(result.tracks),
                    inference_ms=result.inference_ms,
                    fps=result.fps,
                    active_target=telem_payload.get("active_target"),
                    all_detections=telem_payload.get("all_detections", []),
                )

                # 6. Dispatch servo actuation if auto_track is active and not E-Stop/Failsafe
                now = time.time()
                is_stale = (now - ts_sec) > settings.STALE_TRACKING_TIMEOUT_S

                # Command dispatch condition:
                # 1. Mode is auto_track
                # 2. ESP32 is connected
                # 3. Neither E-Stop nor Failsafe is active
                # 4. Vision frame is not stale (< 300 ms)
                # 5. PID controller determined a command should be dispatched (respects deadband suppression & auto-center)
                # 6. Enforces 20 Hz (50 ms) command rate
                if (
                    self.pipeline.selector.mode == "auto_track"
                    and not self.state.estop_active
                    and not self.state.failsafe_active
                    and self.state.esp32_connected
                    and not is_stale
                    and result.control_output.should_dispatch_command
                    and (now - self._last_servo_cmd_time >= 0.045)
                ):
                    out = result.control_output
                    pan = settings.clamp_pan(out.pan_angle)
                    tilt = settings.clamp_tilt(out.tilt_angle)

                    servo_msg = self.hub.create_envelope(
                        msg_type="cmd.servo.move",
                        payload={
                            "mode": "absolute",
                            "pan": round(pan, 1),
                            "tilt": round(tilt, 1),
                            "speed": round(settings.DEFAULT_SPEED, 2),
                            "smooth": True,
                        },
                    )
                    sent = await self.hub.send_to_device(servo_msg)
                    if sent:
                        self._last_servo_cmd_time = now

                # 7. Broadcast tracking telemetry to all connected web operators
                await self.hub.broadcast_to_clients(result.telemetry_message)

                # Yield control briefly to ensure network I/O responsiveness
                await asyncio.sleep(0.001)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in tracking worker loop: {e}", exc_info=True)
                await asyncio.sleep(0.05)
