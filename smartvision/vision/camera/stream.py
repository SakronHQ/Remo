"""
SmartVision - Low-Latency MJPEG Video Stream Generator
Encodes video frames to JPEG and formats multipart HTTP boundary chunks
for direct integration with FastAPI StreamingResponse.
"""

import asyncio
from datetime import datetime
import time
from typing import AsyncIterator, Iterator, Optional

import cv2
import numpy as np

from vision.camera.service import CameraService


def draw_hud_overlay(frame: np.ndarray, stats: dict) -> np.ndarray:
    """
    Renders telemetry HUD (FPS, resolution, timestamp, dropped frames) onto a frame copy.
    """
    annotated = frame.copy()
    h, w = annotated.shape[:2]

    # Semi-transparent HUD top bar
    bar_h = 28
    overlay = annotated.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (16, 16, 16), -1)
    cv2.addWeighted(overlay, 0.65, annotated, 0.35, 0, annotated)

    # Telemetry text
    fps = stats.get("fps_actual", 0.0)
    source = stats.get("source", "camera")
    is_synth = stats.get("is_synthetic", False)
    status_label = "SYNTHETIC" if is_synth else "UVC_HARDWARE"
    status_color = (0, 200, 255) if is_synth else (0, 255, 0)

    hud_text = f"FPS: {fps:4.1f} | {w}x{h} | [{status_label}] | DROP: {stats.get('dropped_frames', 0)}"
    cv2.putText(annotated, hud_text, (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, status_color, 1, cv2.LINE_AA)

    time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    cv2.putText(annotated, time_str, (w - 110, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
    return annotated


def get_mjpeg_stream(
    camera_service: CameraService,
    quality: int = 80,
    fps_limit: Optional[float] = None,
    overlay_hud: bool = False,
    boundary: str = "frame",
) -> Iterator[bytes]:
    """
    Synchronous generator producing multipart MJPEG chunks for FastAPI StreamingResponse:

    Example:
        @app.get("/api/v1/stream/video.mjpeg")
        def video_feed():
            return StreamingResponse(
                get_mjpeg_stream(camera_service, quality=80),
                media_type="multipart/x-mixed-replace; boundary=frame"
            )
    """
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, quality))]
    frame_interval = 1.0 / fps_limit if fps_limit and fps_limit > 0 else 0.0
    last_yield_time = 0.0

    boundary_bytes = boundary.encode("ascii")
    last_frame_id: Optional[int] = None

    try:
        while camera_service.is_running:
            # Block until next fresh frame arrives (guarantees multi-client frame delivery)
            success, frame, metadata = camera_service.get_frame(
                timeout=0.5,
                last_frame_id=last_frame_id,
            )
            if not success or frame is None or metadata is None:
                continue
            last_frame_id = metadata.frame_id

            # Optional FPS throttling
            now = time.time()
            if frame_interval > 0.0 and (now - last_yield_time) < frame_interval:
                continue
            last_yield_time = now

            # Optional HUD overlay
            if overlay_hud:
                stats = camera_service.get_stats()
                frame = draw_hud_overlay(frame, stats)

            # JPEG encode
            ret, jpeg_buffer = cv2.imencode(".jpg", frame, encode_params)
            if not ret or jpeg_buffer is None:
                continue

            jpeg_bytes = jpeg_buffer.tobytes()
            content_length = len(jpeg_bytes)

            chunk = (
                b"--" + boundary_bytes + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(content_length).encode("ascii") + b"\r\n\r\n"
                + jpeg_bytes + b"\r\n"
            )
            yield chunk

    except (GeneratorExit, StopIteration):
        # Client disconnected cleanly
        pass


async def async_get_mjpeg_stream(
    camera_service: CameraService,
    quality: int = 80,
    fps_limit: Optional[float] = None,
    overlay_hud: bool = False,
    boundary: str = "frame",
) -> AsyncIterator[bytes]:
    """
    Asynchronous generator producing multipart MJPEG chunks.
    Yields chunks without blocking the async event loop.
    """
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(10, min(100, quality))]
    frame_interval = 1.0 / fps_limit if fps_limit and fps_limit > 0 else 0.0
    last_yield_time = 0.0
    boundary_bytes = boundary.encode("ascii")
    last_frame_id: Optional[int] = None

    try:
        while camera_service.is_running:
            # Offload frame fetch to worker thread to avoid blocking asyncio loop
            success, frame, metadata = await asyncio.to_thread(
                camera_service.get_frame,
                timeout=0.5,
                last_frame_id=last_frame_id,
            )
            if not success or frame is None or metadata is None:
                await asyncio.sleep(0.005)
                continue
            last_frame_id = metadata.frame_id

            now = time.time()
            if frame_interval > 0.0 and (now - last_yield_time) < frame_interval:
                await asyncio.sleep(0.002)
                continue
            last_yield_time = now

            if overlay_hud:
                stats = camera_service.get_stats()
                frame = draw_hud_overlay(frame, stats)

            ret, jpeg_buffer = cv2.imencode(".jpg", frame, encode_params)
            if not ret or jpeg_buffer is None:
                continue

            jpeg_bytes = jpeg_buffer.tobytes()
            content_length = len(jpeg_bytes)

            chunk = (
                b"--" + boundary_bytes + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(content_length).encode("ascii") + b"\r\n\r\n"
                + jpeg_bytes + b"\r\n"
            )
            yield chunk

    except (GeneratorExit, asyncio.CancelledError):
        pass
