"""
SmartVision - REST API Router
Provides /api/v1/ endpoints for system status, tracking configuration,
manual camera control, emergency stop arbitration, and buzzer diagnostics.
"""

import time
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import verify_api_key
from ..config import settings
from ..schemas.rest import (
    BuzzerTestRequest,
    CameraControlRequest,
    EstopRequest,
    HealthResponse,
    StandardResponse,
    SystemStatusResponse,
    TargetSelectRequest,
    TrackingModeRequest,
)

router = APIRouter(prefix="/api/v1", tags=["REST API"], dependencies=[Depends(verify_api_key)])


def get_services(request: Request):
    """Retrieves singletons injected into FastAPI app.state."""
    app_state = request.app.state
    return (
        app_state.state_manager,
        app_state.connection_hub,
        app_state.tracking_pipeline,
        app_state.failsafe_service,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request):
    """Basic health check and uptime probe."""
    state_mgr, _, _, _ = get_services(request)
    now = time.time()
    return HealthResponse(
        status="ok",
        uptime_s=round(now - state_mgr.start_time, 2),
        timestamp=int(now * 1000),
        version=settings.APP_VERSION,
    )


@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(request: Request):
    """Returns comprehensive aggregated system health and telemetry."""
    state_mgr, _, _, _ = get_services(request)
    return state_mgr.get_status_snapshot()


@router.post("/tracking/target", response_model=StandardResponse)
async def select_tracking_target(request: Request, body: TargetSelectRequest):
    """
    Selects or locks onto a target by screen coordinates (click-to-track),
    direct track ID, or heuristic strategy.
    """
    state_mgr, hub, pipeline, _ = get_services(request)

    if state_mgr.estop_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot select target while Emergency Stop is active",
        )

    locked_id = None
    if body.click_to_track is not None:
        x, y = body.click_to_track
        locked_id = pipeline.click_to_track(x, y)
        if locked_id is None:
            return StandardResponse(
                status="warning",
                message=f"No detected person found near ({x:.1f}, {y:.1f})",
                data={"track_id": None},
            )
        msg = f"Locked target ID {locked_id} via click-to-track"

    elif body.track_id is not None:
        ok = pipeline.select_track_id(body.track_id)
        if not ok:
            return StandardResponse(
                status="warning",
                message=f"Track ID {body.track_id} is not currently active",
                data={"track_id": body.track_id, "locked": False},
            )
        locked_id = body.track_id
        msg = f"Locked target ID {locked_id}"

    elif body.strategy is not None:
        locked_id = pipeline.auto_track_first(strategy=body.strategy)
        if locked_id is None:
            return StandardResponse(
                status="warning",
                message=f"No suitable person detected using strategy '{body.strategy}'",
                data={"track_id": None},
            )
        msg = f"Locked target ID {locked_id} using strategy '{body.strategy}'"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No target parameter provided")

    return StandardResponse(status="ok", message=msg, data={"track_id": locked_id, "locked": True})


@router.post("/tracking/mode", response_model=StandardResponse)
async def set_tracking_mode(request: Request, body: TrackingModeRequest):
    """Configures the operating tracking mode ('auto_track', 'manual', 'idle', 'patrol')."""
    state_mgr, hub, pipeline, _ = get_services(request)

    pipeline.set_mode(body.mode)
    state_mgr.set_tracking_mode(body.mode)

    # Broadcast mode update to all connected frontend clients
    mode_msg = hub.create_envelope(
        msg_type="track.mode_set",
        payload={"mode": body.mode},
    )
    await hub.broadcast_to_clients(mode_msg)

    return StandardResponse(
        status="ok",
        message=f"Tracking mode changed to '{body.mode}'",
        data={"mode": body.mode},
    )


@router.post("/camera/control", response_model=StandardResponse)
async def control_camera(request: Request, body: CameraControlRequest):
    """
    Manual pan/tilt servo actuation, jogging, or centering.
    Validates boundary constraints [15°, 165°] Pan, [60°, 135°] Tilt.
    """
    state_mgr, hub, pipeline, _ = get_services(request)

    if body.action == "speed":
        speed = body.speed if body.speed is not None else settings.DEFAULT_SPEED
        settings.DEFAULT_SPEED = speed
        return StandardResponse(
            status="ok",
            message=f"Default camera speed set to {speed}",
            data={"speed": speed},
        )

    if state_mgr.estop_active or state_mgr.failsafe_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot control camera servos while Emergency Stop or Failsafe is active",
        )

    if body.action == "center":
        pipeline.stop_tracking()
        center_msg = hub.create_envelope(
            msg_type="cmd.servo.center",
            payload={"speed": body.speed or 0.4},
        )
        await hub.send_to_device(center_msg)
        return StandardResponse(status="ok", message="Center command dispatched to ESP32")

    elif body.action == "move":
        pan = body.pan if body.pan is not None else state_mgr.servo_data.get("pan_angle", settings.PAN_HOME)
        tilt = body.tilt if body.tilt is not None else state_mgr.servo_data.get("tilt_angle", settings.TILT_HOME)

        # Boundary enforcement
        if not settings.is_pan_valid(pan):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pan angle {pan}° is outside allowable bounds [{settings.PAN_MIN}°, {settings.PAN_MAX}°]",
            )
        if not settings.is_tilt_valid(tilt):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Tilt angle {tilt}° is outside allowable bounds [{settings.TILT_MIN}°, {settings.TILT_MAX}°]",
            )

        move_msg = hub.create_envelope(
            msg_type="cmd.servo.move",
            payload={
                "mode": "absolute",
                "pan": round(pan, 1),
                "tilt": round(tilt, 1),
                "speed": body.speed or 0.5,
                "smooth": True,
            },
        )
        await hub.send_to_device(move_msg)
        return StandardResponse(
            status="ok",
            message=f"Move command to pan={pan:.1f}°, tilt={tilt:.1f}° dispatched",
            data={"pan": pan, "tilt": tilt},
        )

    elif body.action == "jog":
        delta_p = body.delta_pan or 0.0
        delta_t = body.delta_tilt or 0.0

        jog_msg = hub.create_envelope(
            msg_type="cmd.jog",
            payload={
                "delta_pan": round(delta_p, 1),
                "delta_tilt": round(delta_t, 1),
                "speed": body.speed or settings.DEFAULT_SPEED,
            },
        )
        await hub.send_to_device(jog_msg)
        return StandardResponse(
            status="ok",
            message=f"Jog command (d_pan={delta_p:.1f}°, d_tilt={delta_t:.1f}°) dispatched",
            data={"delta_pan": delta_p, "delta_tilt": delta_t},
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported action")


@router.post("/system/estop", response_model=StandardResponse)
async def emergency_stop(request: Request, body: EstopRequest):
    """Engages or clears system-wide hardware Emergency Stop."""
    state_mgr, hub, pipeline, failsafe = get_services(request)

    if body.action in ("resume", "reset"):
        await failsafe.reset_estop()
        return StandardResponse(status="ok", message="Emergency Stop cleared; normal operation resumed")
    else:
        pipeline.stop_tracking()
        await failsafe.trigger_estop(reason=body.reason or "operator_e_stop", action=body.action)
        return StandardResponse(
            status="ok",
            message=f"Emergency Stop engaged ({body.action}): motion frozen",
            data={"estop_active": True},
        )


@router.post("/buzzer/test", response_model=StandardResponse)
async def test_buzzer(request: Request, body: BuzzerTestRequest):
    """Triggers acoustic test cadences (beep, chirp, alarm, pulse, off)."""
    _, hub, _, _ = get_services(request)

    buzzer_msg = hub.create_envelope(
        msg_type="cmd.buzzer",
        payload={
            "action": body.action,
            "duration_ms": body.duration_ms,
            "count": body.count,
            "interval_ms": body.interval_ms,
        },
    )
    await hub.send_to_device(buzzer_msg)
    return StandardResponse(
        status="ok",
        message=f"Buzzer command '{body.action}' sent to ESP32",
        data={"action": body.action},
    )
