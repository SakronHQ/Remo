"""
SmartVision - MJPEG Video Streaming Router
Streams multipart/x-mixed-replace annotated video stream with client disconnect cleanup.
"""

import asyncio
import logging
import time
from typing import AsyncIterator, Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from ..auth import verify_api_key
from ..config import settings

logger = logging.getLogger("SmartVision.Stream")

router = APIRouter(prefix="/api/v1/stream", tags=["Streaming"], dependencies=[Depends(verify_api_key)])


async def mjpeg_frame_generator(
    request: Request,
    max_fps: float = 30.0,
    boundary: str = "frame",
) -> AsyncIterator[bytes]:
    """
    Asynchronous generator yielding HTTP multipart chunks for live MJPEG video playback.
    """
    state_mgr = request.app.state.state_manager
    boundary_bytes = boundary.encode("ascii")
    min_interval = 1.0 / max_fps if max_fps > 0 else 0.033
    last_frame_id = -1

    try:
        while True:
            # Check if client has disconnected
            if await request.is_disconnected():
                break

            t_start = time.monotonic()

            # Wait for next annotated frame from the vision pipeline
            jpeg_bytes, frame_id = await state_mgr.wait_for_frame(
                last_frame_id=last_frame_id, timeout=0.20
            )
            if jpeg_bytes is None or frame_id == last_frame_id:
                await asyncio.sleep(0.005)
                continue

            last_frame_id = frame_id

            header = (
                b"--" + boundary_bytes + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg_bytes)).encode("ascii") + b"\r\n\r\n"
            )
            yield header + jpeg_bytes + b"\r\n"

            elapsed = time.monotonic() - t_start
            sleep_time = max(0.001, min_interval - elapsed)
            await asyncio.sleep(sleep_time)

    except asyncio.CancelledError:
        logger.info("MJPEG client stream disconnected cleanly")
    except Exception as e:
        logger.warning(f"MJPEG streaming ended: {e}")


@router.get("/video.mjpeg")
async def get_video_stream(
    request: Request,
    fps: float = Query(30.0, ge=1.0, le=60.0, description="Target frame rate limit"),
):
    """
    Serves multipart/x-mixed-replace video stream consumable directly by standard HTML <img> tags:
    <img src="/api/v1/stream/video.mjpeg" />
    """
    return StreamingResponse(
        mjpeg_frame_generator(request=request, max_fps=fps),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "close",
        },
    )
