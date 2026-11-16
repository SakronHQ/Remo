"""
SmartVision - Backend Configuration & Global Settings
Centralized configuration parameters, mechanical boundary constants,
watchdog timers, security options, and camera presets.
"""

import os
from typing import Optional
from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Global system configuration model."""

    # Server binding
    HOST: str = Field(default_factory=lambda: os.getenv("SMARTVISION_HOST", "0.0.0.0"))
    PORT: int = Field(default_factory=lambda: int(os.getenv("SMARTVISION_PORT", "8000")))
    DEBUG: bool = Field(default_factory=lambda: os.getenv("SMARTVISION_DEBUG", "false").lower() == "true")
    APP_NAME: str = "SmartVision Central Gateway"
    APP_VERSION: str = "1.0.0"

    # Authentication & Security
    AUTH_ENABLED: bool = Field(
        default_factory=lambda: os.getenv("SMARTVISION_AUTH_ENABLED", "false").lower() == "true"
    )
    API_KEY: str = Field(
        default_factory=lambda: os.getenv("SMARTVISION_API_KEY", "smartvision-secret-key")
    )

    # Mechanical Pan/Tilt Servo Limits (Degrees)
    PAN_MIN: float = 15.0
    PAN_MAX: float = 165.0
    PAN_HOME: float = 90.0

    TILT_MIN: float = 60.0
    TILT_MAX: float = 135.0
    TILT_HOME: float = 90.0

    # Velocity / Slew Settings
    SPEED_MIN: float = 0.1
    SPEED_MAX: float = 1.0
    DEFAULT_SPEED: float = 0.5

    # Operator Client Throttling
    CLIENT_MAX_RATE_HZ: float = 20.0  # 50 ms minimum period between operator commands
    CLIENT_MIN_INTERVAL_S: float = 1.0 / 20.0

    # Watchdogs & Timing (Seconds)
    ESP32_PING_INTERVAL_S: float = 0.5      # Send sys.ping every 500 ms
    ESP32_WATCHDOG_TIMEOUT_S: float = 1.2    # Mark disconnect if no message for 1200 ms
    STALE_TRACKING_TIMEOUT_S: float = 0.3    # Clamp PID if tracking frame older than 300 ms

    # Camera & Vision Pipeline
    CAMERA_BACKEND: str = Field(default_factory=lambda: os.getenv("SMARTVISION_CAMERA_BACKEND", "auto"))
    CAMERA_DEVICE_INDEX: int = Field(default_factory=lambda: int(os.getenv("SMARTVISION_CAMERA_INDEX", "0")))
    CAMERA_WIDTH: int = 640
    CAMERA_HEIGHT: int = 480
    CAMERA_FPS: int = 30
    FORCE_SYNTHETIC: bool = Field(
        default_factory=lambda: os.getenv("SMARTVISION_FORCE_SYNTHETIC", "false").lower() == "true"
    )
    DETECTOR_MODE: str = Field(default_factory=lambda: os.getenv("SMARTVISION_DETECTOR_MODE", "face"))
    ENABLE_HUD: bool = True
    MJPEG_QUALITY: int = 80

    def is_pan_valid(self, pan: float) -> bool:
        """Checks if pan angle is within physical safety limits."""
        return self.PAN_MIN <= pan <= self.PAN_MAX

    def is_tilt_valid(self, tilt: float) -> bool:
        """Checks if tilt angle is within physical safety limits."""
        return self.TILT_MIN <= tilt <= self.TILT_MAX

    def clamp_pan(self, pan: float) -> float:
        """Clamps pan angle to safe bounds [15.0, 165.0]."""
        return max(self.PAN_MIN, min(self.PAN_MAX, float(pan)))

    def clamp_tilt(self, tilt: float) -> float:
        """Clamps tilt angle to safe bounds [60.0, 135.0]."""
        return max(self.TILT_MIN, min(self.TILT_MAX, float(tilt)))


# Global singleton instance
settings = Settings()
