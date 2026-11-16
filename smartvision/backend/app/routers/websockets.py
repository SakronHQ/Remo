"""
SmartVision - Dual WebSocket Router
Provides full-duplex communication channels for:
- /ws/device: Embedded ESP32-S3 microcontroller
- /ws/client: Next.js operator frontend dashboards
Enforces 20 Hz client rate limiting, Pydantic schema validation, and safe-stop failsafes.
"""

import json
import logging
import time
from typing import Any, Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from ..auth import authenticate_websocket
from ..config import settings
from ..schemas.protocol import (
    AlertEventPayload,
    BuzzerControlPayload,
    ClickToTrackPayload,
    SafeStopPayload,
    ServoCenterPayload,
    ServoJogPayload,
    ServoMovePayload,
    ServoPatrolPayload,
    SmartVisionEnvelope,
    TrackModeSetPayload,
    TrackSelectIdPayload,
    TrackTargetSelectPayload,
)

logger = logging.getLogger("SmartVision.WebSockets")

router = APIRouter(tags=["WebSockets"])


# ==============================================================================
# /ws/device: ESP32-S3 Firmware Bridge
# ==============================================================================

@router.websocket("/ws/device")
async def websocket_device_endpoint(websocket: WebSocket):
    """
    Bi-directional bridge for the ESP32-S3 embedded controller:
    - Ingests 10 Hz telem.sensors, sys.pong, telem.status, and alert.event
    - Dispatches motion commands (cmd.servo.move, cmd.jog, cmd.center, cmd.estop)
    - Monitors link liveness and safe-stop on disconnect
    """
    if not authenticate_websocket(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket.accept()

    app_state = websocket.app.state
    state_mgr = app_state.state_manager
    hub = app_state.connection_hub

    client_ip = websocket.client.host if websocket.client else "unknown"
    await hub.register_device(websocket)
    state_mgr.update_esp32_connection(True, ip=client_ip)

    # Broadcast notification to all connected web operators that ESP32 came online
    device_online_msg = hub.create_envelope(
        msg_type="alert.event",
        payload={
            "event_id": f"esp32_online_{int(time.time()*1000)}",
            "event_type": "device_connected",
            "severity": "info",
            "source": "backend",
            "message": f"ESP32-S3 embedded controller connected from {client_ip}",
        },
    )
    await hub.broadcast_to_clients(device_online_msg)

    try:
        while True:
            data_str = await websocket.receive_text()
            try:
                data = json.loads(data_str)
            except Exception:
                continue

            msg_type = data.get("type", "")
            payload = data.get("payload") or {}

            # Pet watchdog timestamp on every incoming packet
            state_mgr.record_heartbeat()

            if msg_type == "telem.sensors":
                # Ingest sensor readings and forward to operators
                state_mgr.update_esp32_telemetry(payload)
                await hub.broadcast_to_clients(data)

            elif msg_type in ("telem.status", "sys.status"):
                state_mgr.record_heartbeat()
                await hub.broadcast_to_clients(data)

            elif msg_type == "alert.event":
                state_mgr.add_alert(payload)
                await hub.broadcast_to_clients(data)

            elif msg_type == "sys.pong":
                echo_ts = payload.get("echo_timestamp", 0)
                rtt = payload.get("rtt_ms", 0)
                state_mgr.update_esp32_pong(echo_ts=echo_ts, rtt_ms=rtt)

            elif msg_type in ("sys.ping", "ping"):
                pong = hub.create_envelope(
                    msg_type="sys.pong",
                    payload={"echo_timestamp": data.get("timestamp", 0)},
                    corr_id=data.get("corr_id"),
                )
                await hub.send_to_device(pong)

    except WebSocketDisconnect:
        logger.info("ESP32-S3 disconnected from /ws/device")
    except Exception as e:
        logger.warning(f"ESP32-S3 session error: {e}")
    finally:
        await hub.unregister_device(websocket)
        state_mgr.update_esp32_connection(False)
        if hasattr(app_state, "tracking_pipeline") and app_state.tracking_pipeline:
            app_state.tracking_pipeline.stop_tracking()

        # Notify operators of disconnect
        offline_alert = hub.create_envelope(
            msg_type="alert.event",
            payload={
                "event_id": f"esp32_offline_{int(time.time()*1000)}",
                "event_type": "ws_disconnect",
                "severity": "critical",
                "source": "backend",
                "message": "ESP32-S3 communication link severed",
                "action_taken": "failsafe_engaged",
                "buzzer_activated": False,
            },
        )
        state_mgr.add_alert(offline_alert["payload"])
        await hub.broadcast_to_clients(offline_alert)


# ==============================================================================
# /ws/client: Frontend Web Operator Bridge
# ==============================================================================

@router.websocket("/ws/client")
async def websocket_client_endpoint(websocket: WebSocket):
    """
    Bi-directional bridge for authorized Next.js operator dashboards:
    - Broadcasts aggregated state: detection boxes, active target, sensor telemetry, alerts
    - Accepts operator commands: target select, mode changes, manual pan/tilt jog, estop
    - Enforces 20 Hz client rate limiting and Pydantic validation
    """
    if not authenticate_websocket(websocket):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")
        return

    await websocket.accept()

    app_state = websocket.app.state
    state_mgr = app_state.state_manager
    hub = app_state.connection_hub
    pipeline = app_state.tracking_pipeline
    failsafe = app_state.failsafe_service

    await hub.register_client(websocket)

    # Send initial full system state snapshot
    initial_snapshot = hub.create_envelope(
        msg_type="sys.status",
        payload=state_mgr.get_status_snapshot(),
    )
    await hub.send_to_client(websocket, initial_snapshot)

    try:
        while True:
            data_str = await websocket.receive_text()

            # 1. Parse JSON envelope first
            try:
                data = json.loads(data_str)
                envelope = SmartVisionEnvelope.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                err_msg = str(e)
                error_env = hub.create_envelope(
                    msg_type="alert.event",
                    payload={
                        "event_id": f"valerr_{int(time.time()*1000)}",
                        "event_type": "invalid_command_schema",
                        "severity": "warning",
                        "source": "backend",
                        "message": f"Message schema validation failed: {err_msg}",
                    },
                )
                await hub.send_to_client(websocket, error_env)
                continue

            msg_type = envelope.type
            payload = envelope.payload
            corr_id = envelope.corr_id

            # 2. Enforce 20 Hz rate limiting (safety-critical E-Stop bypasses rate limiter)
            if msg_type not in ("cmd.estop", "sys.safestop"):
                if not hub.check_client_rate_limit(websocket):
                    error_env = hub.create_envelope(
                        msg_type="alert.event",
                        payload={
                            "event_id": f"ratelimit_{int(time.time()*1000)}",
                            "event_type": "rate_limit_exceeded",
                            "severity": "warning",
                            "source": "backend",
                            "message": "Client command rate exceeded 20 Hz threshold. Command dropped.",
                        },
                    )
                    await hub.send_to_client(websocket, error_env)
                    continue

            # 3. Route operator commands
            if msg_type in ("cmd.servo.move", "cmd.move"):
                try:
                    move_p = ServoMovePayload.model_validate(payload)
                except ValidationError as ve:
                    await _send_error(hub, websocket, f"Out of bounds or invalid move parameters: {ve}", corr_id)
                    continue

                if state_mgr.estop_active or state_mgr.failsafe_active:
                    await _send_error(hub, websocket, "Cannot move servos while E-Stop or Failsafe is active", corr_id)
                    continue

                prev_mode = state_mgr.tracking_mode
                pipeline.stop_tracking()
                pipeline.set_mode("manual")
                state_mgr.set_tracking_mode("manual")
                if prev_mode != "manual":
                    mode_env = hub.create_envelope(
                        msg_type="track.mode_set",
                        payload={"mode": "manual", "target_selection": "primary"},
                        corr_id=corr_id,
                    )
                    await hub.broadcast_to_clients(mode_env)

                # Forward validated move to ESP32
                cmd_out = hub.create_envelope(
                    msg_type="cmd.servo.move",
                    payload=move_p.model_dump(),
                    corr_id=corr_id,
                )
                await hub.send_to_device(cmd_out)

            elif msg_type in ("cmd.jog", "cmd.servo.jog"):
                try:
                    jog_p = ServoJogPayload.model_validate(payload)
                except ValidationError as ve:
                    await _send_error(hub, websocket, f"Invalid jog parameters: {ve}", corr_id)
                    continue

                if state_mgr.estop_active or state_mgr.failsafe_active:
                    await _send_error(hub, websocket, "Cannot jog servos while E-Stop or Failsafe is active", corr_id)
                    continue

                prev_mode = state_mgr.tracking_mode
                pipeline.stop_tracking()
                pipeline.set_mode("manual")
                state_mgr.set_tracking_mode("manual")
                if prev_mode != "manual":
                    mode_env = hub.create_envelope(
                        msg_type="track.mode_set",
                        payload={"mode": "manual", "target_selection": "primary"},
                        corr_id=corr_id,
                    )
                    await hub.broadcast_to_clients(mode_env)

                cmd_out = hub.create_envelope(
                    msg_type="cmd.jog",
                    payload=jog_p.model_dump(),
                    corr_id=corr_id,
                )
                await hub.send_to_device(cmd_out)

            elif msg_type in ("cmd.servo.center", "cmd.center"):
                try:
                    center_p = ServoCenterPayload.model_validate(payload)
                except ValidationError as ve:
                    await _send_error(hub, websocket, f"Invalid center parameters: {ve}", corr_id)
                    continue

                if state_mgr.estop_active or state_mgr.failsafe_active:
                    await _send_error(hub, websocket, "Cannot center servos while E-Stop or Failsafe is active", corr_id)
                    continue

                prev_mode = state_mgr.tracking_mode
                pipeline.stop_tracking()
                pipeline.set_mode("manual")
                state_mgr.set_tracking_mode("manual")
                if prev_mode != "manual":
                    mode_env = hub.create_envelope(
                        msg_type="track.mode_set",
                        payload={"mode": "manual", "target_selection": "primary"},
                        corr_id=corr_id,
                    )
                    await hub.broadcast_to_clients(mode_env)

                cmd_out = hub.create_envelope(
                    msg_type="cmd.servo.center",
                    payload=center_p.model_dump(),
                    corr_id=corr_id,
                )
                await hub.send_to_device(cmd_out)

            elif msg_type in ("cmd.servo.patrol", "cmd.patrol"):
                try:
                    patrol_p = ServoPatrolPayload.model_validate(payload)
                except ValidationError as ve:
                    await _send_error(hub, websocket, f"Invalid patrol parameters: {ve}", corr_id)
                    continue

                if state_mgr.estop_active or state_mgr.failsafe_active:
                    await _send_error(hub, websocket, "Cannot start patrol while E-Stop or Failsafe is active", corr_id)
                    continue

                pipeline.stop_tracking()
                new_mode = "patrol" if patrol_p.enabled else "idle"
                pipeline.set_mode(new_mode)
                state_mgr.set_tracking_mode(new_mode)
                mode_env = hub.create_envelope(
                    msg_type="track.mode_set",
                    payload={"mode": new_mode, "target_selection": "primary"},
                    corr_id=corr_id,
                )
                await hub.broadcast_to_clients(mode_env)

                cmd_out = hub.create_envelope(
                    msg_type="cmd.servo.patrol",
                    payload=patrol_p.model_dump(),
                    corr_id=corr_id,
                )
                await hub.send_to_device(cmd_out)

            elif msg_type in ("cmd.estop", "sys.safestop"):
                stop_p = SafeStopPayload.model_validate(payload)
                if stop_p.action in ("resume", "reset", "clear"):
                    await failsafe.reset_estop()
                else:
                    pipeline.stop_tracking()
                    await failsafe.trigger_estop(
                        reason=stop_p.reason or "operator_e_stop",
                        action=stop_p.action or "freeze",
                    )

            elif msg_type == "track.mode_set":
                mode_p = TrackModeSetPayload.model_validate(payload)
                if state_mgr.estop_active or (state_mgr.failsafe_active and mode_p.mode == "auto_track"):
                    await _send_error(hub, websocket, "Cannot engage tracking mode while E-Stop or Failsafe is active", corr_id)
                    continue
                if mode_p.mode == "idle":
                    pipeline.stop_tracking()
                elif mode_p.mode == "auto_track":
                    pipeline.set_mode("auto_track")
                else:
                    pipeline.stop_tracking()
                    pipeline.set_mode(mode_p.mode)
                state_mgr.set_tracking_mode(mode_p.mode)
                # Broadcast mode update
                await hub.broadcast_to_clients(envelope.model_dump())

            elif msg_type == "track.select_id":
                if state_mgr.estop_active:
                    await _send_error(hub, websocket, "Cannot select target while E-Stop is engaged", corr_id)
                    continue
                sel_p = TrackSelectIdPayload.model_validate(payload)
                pipeline.select_track_id(sel_p.track_id)

            elif msg_type == "track.target_select":
                if state_mgr.estop_active:
                    await _send_error(hub, websocket, "Cannot select target while E-Stop is engaged", corr_id)
                    continue
                try:
                    tgt_p = TrackTargetSelectPayload.model_validate(payload)
                except ValidationError as ve:
                    await _send_error(hub, websocket, f"Invalid target_select parameters: {ve}", corr_id)
                    continue

                if tgt_p.track_id is not None:
                    pipeline.select_track_id(tgt_p.track_id)
                elif tgt_p.coordinates is not None:
                    cx, cy = float(tgt_p.coordinates[0]), float(tgt_p.coordinates[1])
                    if 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0:
                        frame_w = getattr(pipeline, "frame_width", 640)
                        frame_h = getattr(pipeline, "frame_height", 480)
                        px = cx * frame_w
                        py = cy * frame_h
                    else:
                        px, py = cx, cy
                    pipeline.click_to_track(px, py)
                elif tgt_p.click_x is not None and tgt_p.click_y is not None:
                    pipeline.click_to_track(tgt_p.click_x, tgt_p.click_y)

            elif msg_type == "track.click_to_track":
                if state_mgr.estop_active:
                    await _send_error(hub, websocket, "Cannot select target while E-Stop is engaged", corr_id)
                    continue
                clk_p = ClickToTrackPayload.model_validate(payload)
                pipeline.click_to_track(clk_p.click_x, clk_p.click_y)

            elif msg_type == "cmd.tracking.config":
                if "invert_pan" in payload:
                    pipeline.controller.invert_pan = bool(payload["invert_pan"])
                if "invert_tilt" in payload:
                    pipeline.controller.invert_tilt = bool(payload["invert_tilt"])
                if "preset" in payload:
                    pipeline.controller.set_preset(str(payload["preset"]))
                ack = hub.create_envelope(
                    msg_type="status.tracking.config",
                    payload={
                        "invert_pan": pipeline.controller.invert_pan,
                        "invert_tilt": pipeline.controller.invert_tilt,
                        "preset": getattr(pipeline.controller, "current_preset", "normal"),
                    },
                    corr_id=corr_id,
                )
                await hub.send_to_client(websocket, ack)

            elif msg_type == "cmd.buzzer":
                buz_p = BuzzerControlPayload.model_validate(payload)
                cmd_out = hub.create_envelope(
                    msg_type="cmd.buzzer",
                    payload=buz_p.model_dump(),
                    corr_id=corr_id,
                )
                await hub.send_to_device(cmd_out)

            elif msg_type in ("sys.ping", "ping"):
                pong = hub.create_envelope(
                    msg_type="sys.pong",
                    payload={"echo_timestamp": envelope.timestamp},
                    corr_id=corr_id,
                )
                await hub.send_to_client(websocket, pong)

    except WebSocketDisconnect:
        logger.info("Frontend operator disconnected from /ws/client")
    except Exception as e:
        logger.warning(f"Frontend operator session error: {e}")
    finally:
        await hub.unregister_client(websocket)


async def _send_error(hub, ws: WebSocket, message: str, corr_id: Any) -> None:
    """Helper to send structured error alert envelope to client."""
    err_env = hub.create_envelope(
        msg_type="alert.event",
        payload={
            "event_id": f"err_{int(time.time()*1000)}",
            "event_type": "command_rejected",
            "severity": "warning",
            "source": "backend",
            "message": message,
        },
        corr_id=corr_id,
    )
    await hub.send_to_client(ws, err_env)
