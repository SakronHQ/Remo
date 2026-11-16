"""
SmartVision - REST API Request & Response Schemas
Pydantic v2 models for /api/v1/ endpoints with parameter validation and boundary enforcement.
"""

from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import settings


class StandardResponse(BaseModel):
    """Standard generic API response."""
    status: str = "ok"
    message: str
    data: Optional[Dict[str, Any]] = None


class TargetSelectRequest(BaseModel):
    """Request body for POST /api/v1/tracking/target."""
    click_to_track: Optional[Tuple[float, float]] = Field(
        None, description="Image coordinate pair [x, y] to lock onto nearest person"
    )
    track_id: Optional[int] = Field(None, ge=0, description="Direct ByteTrack ID to lock onto")
    strategy: Optional[Literal["largest", "center_closest", "highest_conf"]] = Field(
        None, description="Auto-selection heuristic strategy"
    )

    @model_validator(mode="after")
    def check_at_least_one(self) -> "TargetSelectRequest":
        if self.click_to_track is None and self.track_id is None and self.strategy is None:
            raise ValueError("Must specify at least one of: click_to_track, track_id, or strategy")
        return self


class TrackingModeRequest(BaseModel):
    """Request body for POST /api/v1/tracking/mode."""
    mode: Literal["auto_track", "manual", "idle", "patrol"] = Field(
        ..., description="Desired tracking operating mode"
    )


class CameraControlRequest(BaseModel):
    """Request body for POST /api/v1/camera/control."""
    action: Literal["move", "jog", "center", "speed"] = Field("move", description="Control operation")
    pan: Optional[float] = Field(None, description="Absolute target pan angle [15.0, 165.0]")
    tilt: Optional[float] = Field(None, description="Absolute target tilt angle [60.0, 135.0]")
    delta_pan: Optional[float] = Field(None, description="Relative pan jog increment (max +-45.0)")
    delta_tilt: Optional[float] = Field(None, description="Relative tilt jog increment (max +-30.0)")
    speed: Optional[float] = Field(None, ge=0.1, le=1.0, description="Movement speed factor [0.1, 1.0]")

    @model_validator(mode="after")
    def validate_action_fields(self) -> "CameraControlRequest":
        if self.action == "move":
            if self.pan is not None and not (settings.PAN_MIN <= self.pan <= settings.PAN_MAX):
                raise ValueError(
                    f"Pan angle {self.pan}° is out of calibrated bounds [{settings.PAN_MIN}°, {settings.PAN_MAX}°]"
                )
            if self.tilt is not None and not (settings.TILT_MIN <= self.tilt <= settings.TILT_MAX):
                raise ValueError(
                    f"Tilt angle {self.tilt}° is out of calibrated bounds [{settings.TILT_MIN}°, {settings.TILT_MAX}°]"
                )
            if self.pan is None and self.tilt is None:
                raise ValueError("Must provide at least 'pan' or 'tilt' for 'move' action")

        elif self.action == "jog":
            if self.delta_pan is not None and abs(self.delta_pan) > 45.0:
                raise ValueError(f"Relative pan jog {self.delta_pan}° exceeds maximum +-45.0°")
            if self.delta_tilt is not None and abs(self.delta_tilt) > 30.0:
                raise ValueError(f"Relative tilt jog {self.delta_tilt}° exceeds maximum +-30.0°")
            if self.delta_pan is None and self.delta_tilt is None:
                raise ValueError("Must provide at least 'delta_pan' or 'delta_tilt' for 'jog' action")

        elif self.action == "speed":
            if self.speed is None:
                raise ValueError("Must provide 'speed' factor for 'speed' action")
            if not (settings.SPEED_MIN <= self.speed <= settings.SPEED_MAX):
                raise ValueError(
                    f"Speed factor {self.speed} is outside allowable range [{settings.SPEED_MIN}, {settings.SPEED_MAX}]"
                )

        return self


class EstopRequest(BaseModel):
    """Request body for POST /api/v1/system/estop."""
    action: Literal["freeze", "center", "release_pwm", "resume", "reset"] = Field(
        "freeze", description="Safe-stop action or resume"
    )
    reason: Optional[str] = Field("operator_e_stop", description="Reason for triggering safe stop")
    release_pwm: Optional[bool] = Field(False, description="Depower servo coils")


class BuzzerTestRequest(BaseModel):
    """Request body for POST /api/v1/buzzer/test."""
    action: Literal["beep", "chirp", "alarm", "pulse", "off"] = Field("beep", description="Acoustic pattern")
    duration_ms: Optional[int] = Field(150, ge=10, le=10000, description="Tone duration")
    count: Optional[int] = Field(1, ge=1, le=20, description="Repetition count")
    interval_ms: Optional[int] = Field(100, ge=10, le=2000, description="Pause between repetitions")


class HealthResponse(BaseModel):
    """Response model for GET /api/v1/health."""
    status: str = "ok"
    uptime_s: float
    timestamp: int
    version: str


class ESP32Status(BaseModel):
    connected: bool = False
    ip: Optional[str] = None
    connected_at_ms: Optional[int] = None
    last_heartbeat_ms: Optional[int] = None
    rtt_ms: Optional[int] = None
    failsafe_active: bool = False
    estop_active: bool = False


class CameraStatus(BaseModel):
    running: bool = False
    fps: float = 0.0
    synthetic: bool = False
    width: int = 640
    height: int = 480
    dropped_frames: int = 0


class TrackingStatus(BaseModel):
    mode: str = "idle"
    locked: bool = False
    active_track_id: Optional[int] = None
    tracks_count: int = 0
    inference_ms: float = 0.0
    fps: float = 0.0
    active_target: Optional[Dict[str, Any]] = None


class SystemStatusResponse(BaseModel):
    """Response model for GET /api/v1/system/status."""
    timestamp: int
    uptime_s: float
    estop_active: bool
    esp32: ESP32Status
    camera: CameraStatus
    tracking: TrackingStatus
    sensors: Dict[str, Any]
