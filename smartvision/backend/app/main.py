"""
SmartVision - Central Gateway Application Entrypoint
FastAPI application with lifespan lifecycle management, background tracking loop,
Dual WebSocket routing, low-latency MJPEG video streaming, and REST management API.
"""

from contextlib import asynccontextmanager
import logging
import os
import sys
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure smartvision root is in Python module search path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.detection.factory import create_detector
from vision.tracking.pipeline import TrackingPipeline

from .config import settings
from .routers import rest_router, stream_router, ws_router
from .services import ConnectionHub, FailsafeService, SystemStateManager, TrackingWorker

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("SmartVision.Gateway")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    Application lifespan manager handling ordered initialization and graceful teardown
    of the camera capture thread, vision pipeline, background tracking worker, and communication failsafe.
    """
    logger.info(f"Initializing {settings.APP_NAME} v{settings.APP_VERSION}...")

    # 1. Initialize Subsystem Singletons if not already provided (e.g. by test harness)
    if not hasattr(app.state, "camera_service") or app.state.camera_service is None:
        if settings.FORCE_SYNTHETIC:
            cam_backend = CameraBackend.SYNTHETIC
        else:
            try:
                cam_backend = CameraBackend(settings.CAMERA_BACKEND.lower())
            except Exception:
                cam_backend = CameraBackend.AUTO

        cam_config = CameraConfig(
            backend=cam_backend,
            device_index=settings.CAMERA_DEVICE_INDEX,
            width=settings.CAMERA_WIDTH,
            height=settings.CAMERA_HEIGHT,
            fps=settings.CAMERA_FPS,
            enable_synthetic_fallback=True,
        )
        camera_service = CameraService(config=cam_config)
        camera_service.start()
        app.state.camera_service = camera_service
    else:
        camera_service = app.state.camera_service
        if not camera_service.is_running:
            camera_service.start()

    if not hasattr(app.state, "tracking_pipeline") or app.state.tracking_pipeline is None:
        det_mode = settings.DETECTOR_MODE
        if settings.FORCE_SYNTHETIC and det_mode in ("face", "auto"):
            det_mode = "mock"
        detector = create_detector(mode=det_mode)
        pipeline = TrackingPipeline(
            detector=detector,
            frame_width=settings.CAMERA_WIDTH,
            frame_height=settings.CAMERA_HEIGHT,
            enable_hud=settings.ENABLE_HUD,
        )
        app.state.tracking_pipeline = pipeline
    else:
        pipeline = app.state.tracking_pipeline

    if not hasattr(app.state, "state_manager") or app.state.state_manager is None:
        app.state.state_manager = SystemStateManager()

    if hasattr(app.state, "camera_service") and app.state.camera_service:
        app.state.state_manager.update_camera_status(app.state.camera_service.get_stats())

    if not hasattr(app.state, "connection_hub") or app.state.connection_hub is None:
        app.state.connection_hub = ConnectionHub()

    if not hasattr(app.state, "failsafe_service") or app.state.failsafe_service is None:
        app.state.failsafe_service = FailsafeService(
            state_manager=app.state.state_manager,
            hub=app.state.connection_hub,
            tracking_pipeline=app.state.tracking_pipeline,
        )

    if not hasattr(app.state, "tracking_worker") or app.state.tracking_worker is None:
        app.state.tracking_worker = TrackingWorker(
            camera_service=app.state.camera_service,
            tracking_pipeline=app.state.tracking_pipeline,
            state_manager=app.state.state_manager,
            hub=app.state.connection_hub,
        )

    # 2. Start Background Services
    app.state.failsafe_service.start()
    app.state.tracking_worker.start()

    logger.info("SmartVision Gateway successfully started and ready for connections.")

    yield

    # 3. Graceful Teardown
    logger.info("Shutting down SmartVision Gateway services...")
    if hasattr(app.state, "tracking_worker") and app.state.tracking_worker:
        await app.state.tracking_worker.stop()

    if hasattr(app.state, "failsafe_service") and app.state.failsafe_service:
        await app.state.failsafe_service.stop()

    if hasattr(app.state, "camera_service") and app.state.camera_service:
        app.state.camera_service.stop()

    logger.info("SmartVision Gateway shutdown complete.")


def create_app(
    camera_service: Optional[CameraService] = None,
    tracking_pipeline: Optional[TrackingPipeline] = None,
    state_manager: Optional[SystemStateManager] = None,
    connection_hub: Optional[ConnectionHub] = None,
    failsafe_service: Optional[FailsafeService] = None,
    tracking_worker: Optional[TrackingWorker] = None,
) -> FastAPI:
    """Factory creating and configuring the FastAPI instance with optional dependency injection."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="SmartVision Central Vision Gateway, Dual WebSocket Hub & MJPEG Streaming Server",
        lifespan=app_lifespan,
    )

    # Cross-Origin Resource Sharing (CORS) for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Pre-inject custom test dependencies if provided
    app.state.camera_service = camera_service
    app.state.tracking_pipeline = tracking_pipeline
    app.state.state_manager = state_manager
    app.state.connection_hub = connection_hub
    app.state.failsafe_service = failsafe_service
    app.state.tracking_worker = tracking_worker

    # Mount Route Handlers
    app.include_router(rest_router)
    app.include_router(stream_router)
    app.include_router(ws_router)

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/api/v1/health",
            "status": "/api/v1/system/status",
            "stream": "/api/v1/stream/video.mjpeg",
            "ws_device": "/ws/device",
            "ws_client": "/ws/client",
        }

    return app


# Default application instance for Uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
