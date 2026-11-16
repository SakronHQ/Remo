"""
SmartVision - Protocol Message Schemas
Pydantic v2 data models for WebSocket JSON envelopes and payloads conforming to docs/protocol.md.
Enforces two-tier boundary checks, type safety, and sequence tracking.
"""

from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import settings


class SmartVisionEnvelope(BaseModel):
    """Authoritative 5-field outer WebSocket message envelope."""
    type: str = Field(..., description="Dot-delimited protocol message identifier")
    timestamp: int = Field(..., ge=0, description="UTC Unix epoch timestamp in milliseconds")
    sender: Literal["frontend", "backend", "esp32"] = Field(..., description="Originating node")
    seq: int = Field(..., ge=0, description="Monotonically increasing sequence number")
    corr_id: Optional[str] = Field(None, description="Optional correlation UUID / token")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Type-specific payload body")


class ServoMovePayload(BaseModel):
    """Payload for cmd.servo.move / cmd.move."""
    mode: Literal["absolute", "relative"] = Field("absolute", description="Coordinate reference")
    pan: Optional[float] = Field(None, description="Target or delta pan angle in degrees")
    tilt: Optional[float] = Field(None, description="Target or delta tilt angle in degrees")
    speed: Optional[float] = Field(0.5, ge=0.1, le=1.0, description="Normalized velocity factor [0.1, 1.0]")
    step_deg: Optional[float] = Field(5.0, description="Step size for discrete jogging")
    smooth: Optional[bool] = Field(True, description="Enable slew rate interpolation")

    @model_validator(mode="after")
    def validate_bounds(self) -> "ServoMovePayload":
        if self.mode == "absolute":
            if self.pan is None:
                raise ValueError("Pan angle is required for absolute mode")
            if not (settings.PAN_MIN <= self.pan <= settings.PAN_MAX):
                raise ValueError(
                    f"Pan angle {self.pan}° is out of calibrated bounds [{settings.PAN_MIN}°, {settings.PAN_MAX}°]"
                )
            if self.tilt is None:
                raise ValueError("Tilt angle is required for absolute mode")
            if not (settings.TILT_MIN <= self.tilt <= settings.TILT_MAX):
                raise ValueError(
                    f"Tilt angle {self.tilt}° is out of calibrated bounds [{settings.TILT_MIN}°, {settings.TILT_MAX}°]"
                )
        elif self.mode == "relative":
            if self.pan is not None and abs(self.pan) > 45.0:
                raise ValueError(f"Relative pan increment {self.pan}° exceeds maximum +-45.0°")
            if self.tilt is not None and abs(self.tilt) > 30.0:
                raise ValueError(f"Relative tilt increment {self.tilt}° exceeds maximum +-30.0°")
        return self


class ServoJogPayload(BaseModel):
    """Payload for cmd.jog."""
    delta_pan: float = Field(0.0, description="Relative pan increment in degrees")
    delta_tilt: float = Field(0.0, description="Relative tilt increment in degrees")
    speed: Optional[float] = Field(0.5, ge=0.1, le=1.0)

    @field_validator("delta_pan")
    @classmethod
    def validate_delta_pan(cls, v: float) -> float:
        if abs(v) > 45.0:
            raise ValueError(f"Relative pan jog {v}° exceeds maximum +-45.0°")
        return v

    @field_validator("delta_tilt")
    @classmethod
    def validate_delta_tilt(cls, v: float) -> float:
        if abs(v) > 30.0:
            raise ValueError(f"Relative tilt jog {v}° exceeds maximum +-30.0°")
        return v


class ServoCenterPayload(BaseModel):
    """Payload for cmd.servo.center / cmd.center."""
    speed: Optional[float] = Field(0.4, ge=0.1, le=1.0)


class ServoPatrolPayload(BaseModel):
    """Payload for cmd.servo.patrol."""
    enabled: bool = True
    pan_min: float = Field(30.0, ge=settings.PAN_MIN, le=80.0)
    pan_max: float = Field(150.0, ge=100.0, le=settings.PAN_MAX)
    tilt_angle: float = Field(90.0, ge=settings.TILT_MIN, le=settings.TILT_MAX)
    speed_deg_s: float = Field(20.0, ge=5.0, le=45.0)
    dwell_time_ms: int = Field(1000, ge=0)


class BuzzerControlPayload(BaseModel):
    """Payload for cmd.buzzer."""
    action: str = Field("beep", description="Buzzer pattern: beep, chirp, alarm, pulse, off")
    duration_ms: Optional[int] = Field(150, ge=10, le=10000)
    count: Optional[int] = Field(1, ge=1, le=20)
    interval_ms: Optional[int] = Field(100, ge=10, le=2000)


class SafeStopPayload(BaseModel):
    """Payload for sys.safestop / cmd.estop."""
    reason: Optional[str] = "manual"
    action: Optional[str] = "freeze"  # freeze, center, release_pwm, resume
    release_pwm: Optional[bool] = False
    details: Optional[str] = None


class TrackModeSetPayload(BaseModel):
    """Payload for track.mode_set."""
    mode: str = Field("auto_track", description="'auto_track', 'manual', 'idle', 'patrol'")
    target_selection: Optional[str] = "primary"
    deadband_px: Optional[int] = 20
    smoothing_factor: Optional[float] = 0.35
    reacquisition_timeout_ms: Optional[int] = 3000


class TrackSelectIdPayload(BaseModel):
    """Payload for track.select_id."""
    track_id: int = Field(..., ge=0)


class TrackTargetSelectPayload(BaseModel):
    """Payload for track.target_select."""
    track_id: Optional[int] = Field(None, ge=0, description="Direct ByteTrack ID to lock onto")
    coordinates: Optional[Union[List[float], Tuple[float, float]]] = Field(
        None, description="Normalized [x, y] coordinates [0.0, 1.0] or pixel coordinates"
    )
    click_x: Optional[float] = Field(None, description="Direct pixel x coordinate")
    click_y: Optional[float] = Field(None, description="Direct pixel y coordinate")

    @model_validator(mode="after")
    def validate_target_fields(self) -> "TrackTargetSelectPayload":
        if self.track_id is None and self.coordinates is None and self.click_x is None and self.click_y is None:
            raise ValueError("Must provide at least 'track_id', 'coordinates', or 'click_x'/'click_y'")
        return self


class ClickToTrackPayload(BaseModel):
    """Payload for track.click_to_track."""
    click_x: float = Field(..., ge=0)
    click_y: float = Field(..., ge=0)


class AlertEventPayload(BaseModel):
    """Payload for alert.event."""
    event_id: str
    event_type: str
    severity: Literal["info", "warning", "critical"] = "info"
    source: str = "backend"
    message: str
    telemetry_snapshot: Optional[Dict[str, Any]] = None
    action_taken: Optional[str] = None
    buzzer_activated: Optional[bool] = False
