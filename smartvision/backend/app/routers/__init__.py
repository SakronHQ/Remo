"""
SmartVision Backend Routers
"""

from .rest_api import router as rest_router
from .stream import router as stream_router
from .websockets import router as ws_router

__all__ = ["rest_router", "stream_router", "ws_router"]
