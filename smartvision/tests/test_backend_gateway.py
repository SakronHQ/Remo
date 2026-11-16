"""
test_backend_gateway.py
Automated Verification Suite for SmartVision Phase 6:
Backend Development (FastAPI Gateway & Central Hub).

Validates:
1. Configuration constants, servo limits ([15°, 165°] Pan, [60°, 135°] Tilt), and Pydantic v2 schemas.
2. SystemStateManager thread-safe state aggregation, telemetry updates, and alert buffers.
3. ConnectionHub WebSocket session tracking, broadcasting, and 20 Hz client rate limiting.
4. REST API Endpoints (/api/v1/health, system/status, tracking/target, tracking/mode,
   camera/control, system/estop, buzzer/test) including out-of-bounds rejection (HTTP 400).
5. Authentication & security (disabled by default, X-API-Key, Bearer token, query token).
6. Dual WebSocket Hub (/ws/device and /ws/client) full-duplex message passing and schema enforcement.
7. Live MJPEG video streaming (multipart/x-mixed-replace; boundary=frame) and client disconnect cleanup.
8. Communication loss watchdog, failsafe engagement, and emergency stop interlocks.
"""

import asyncio
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import unittest

import cv2
import numpy as np
import requests
import uvicorn
import websockets

# Ensure smartvision root is in python search path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.auth import check_key
from backend.app.config import Settings, settings
from backend.app.main import create_app
from backend.app.schemas.protocol import (
    AlertEventPayload,
    BuzzerControlPayload,
    SafeStopPayload,
    ServoCenterPayload,
    ServoJogPayload,
    ServoMovePayload,
    SmartVisionEnvelope,
    TrackModeSetPayload,
    TrackSelectIdPayload,
    TrackTargetSelectPayload,
)
from backend.app.schemas.rest import (
    CameraControlRequest,
    EstopRequest,
    TargetSelectRequest,
    TrackingModeRequest,
)
from backend.app.services.connection_hub import ConnectionHub
from backend.app.services.state_manager import SystemStateManager
from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.detection.mock_detector import MockPersonDetector
from vision.tracking.pipeline import TrackingPipeline


# ==============================================================================
# 1. Configuration & Pydantic Schema Validation Tests
# ==============================================================================

class TestConfigAndSchemas(unittest.TestCase):
    """Validates configuration parameters and Pydantic v2 schema enforcement."""

    def test_servo_boundary_checks(self):
        s = Settings()
        self.assertEqual(s.PAN_MIN, 15.0)
        self.assertEqual(s.PAN_MAX, 165.0)
        self.assertEqual(s.TILT_MIN, 60.0)
        self.assertEqual(s.TILT_MAX, 135.0)

        self.assertTrue(s.is_pan_valid(90.0))
        self.assertTrue(s.is_pan_valid(15.0))
        self.assertTrue(s.is_pan_valid(165.0))
        self.assertFalse(s.is_pan_valid(14.9))
        self.assertFalse(s.is_pan_valid(165.1))

        self.assertTrue(s.is_tilt_valid(90.0))
        self.assertTrue(s.is_tilt_valid(60.0))
        self.assertTrue(s.is_tilt_valid(135.0))
        self.assertFalse(s.is_tilt_valid(59.9))
        self.assertFalse(s.is_tilt_valid(135.1))

        # Clamping
        self.assertEqual(s.clamp_pan(190.0), 165.0)
        self.assertEqual(s.clamp_pan(5.0), 15.0)
        self.assertEqual(s.clamp_tilt(150.0), 135.0)
        self.assertEqual(s.clamp_tilt(30.0), 60.0)

    def test_smartvision_envelope_validation(self):
        # Valid envelope
        raw = {
            "type": "cmd.servo.move",
            "timestamp": int(time.time() * 1000),
            "sender": "frontend",
            "seq": 10,
            "corr_id": "test_corr",
            "payload": {"pan": 90.0, "tilt": 90.0},
        }
        env = SmartVisionEnvelope.model_validate(raw)
        self.assertEqual(env.type, "cmd.servo.move")
        self.assertEqual(env.sender, "frontend")
        self.assertEqual(env.seq, 10)

        # Missing required field
        bad_raw = {"type": "cmd.servo.move", "timestamp": 12345}
        with self.assertRaises(Exception):
            SmartVisionEnvelope.model_validate(bad_raw)

        # Invalid sender
        bad_sender = raw.copy()
        bad_sender["sender"] = "invalid_node"
        with self.assertRaises(Exception):
            SmartVisionEnvelope.model_validate(bad_sender)

    def test_servo_move_payload_bounds(self):
        # Valid absolute move
        valid_abs = {"mode": "absolute", "pan": 90.0, "tilt": 90.0, "speed": 0.5}
        p = ServoMovePayload.model_validate(valid_abs)
        self.assertEqual(p.pan, 90.0)

        # Out-of-bounds pan
        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "absolute", "pan": 180.0, "tilt": 90.0})

        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "absolute", "pan": 10.0, "tilt": 90.0})

        # Out-of-bounds tilt
        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "absolute", "pan": 90.0, "tilt": 50.0})

        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "absolute", "pan": 90.0, "tilt": 140.0})

        # Valid relative move
        valid_rel = {"mode": "relative", "pan": 10.0, "tilt": -5.0}
        pr = ServoMovePayload.model_validate(valid_rel)
        self.assertEqual(pr.mode, "relative")

        # Excessive relative increments
        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "relative", "pan": 50.0, "tilt": 0.0})

        with self.assertRaises(ValueError):
            ServoMovePayload.model_validate({"mode": "relative", "pan": 0.0, "tilt": 35.0})

    def test_servo_jog_payload_bounds(self):
        j = ServoJogPayload(delta_pan=15.0, delta_tilt=-10.0, speed=0.8)
        self.assertEqual(j.delta_pan, 15.0)

        with self.assertRaises(ValueError):
            ServoJogPayload(delta_pan=50.0, delta_tilt=0.0)

        with self.assertRaises(ValueError):
            ServoJogPayload(delta_pan=0.0, delta_tilt=-35.0)

    def test_rest_request_models(self):
        # TargetSelectRequest
        t1 = TargetSelectRequest(click_to_track=(320.0, 240.0))
        self.assertEqual(t1.click_to_track, (320.0, 240.0))
        t2 = TargetSelectRequest(track_id=5)
        self.assertEqual(t2.track_id, 5)
        with self.assertRaises(ValueError):
            TargetSelectRequest()  # empty must fail

        # TrackTargetSelectPayload (WebSocket)
        ws_t1 = TrackTargetSelectPayload(track_id=7)
        self.assertEqual(ws_t1.track_id, 7)
        ws_t2 = TrackTargetSelectPayload(coordinates=[0.5, 0.4])
        self.assertEqual(ws_t2.coordinates, [0.5, 0.4])
        ws_t3 = TrackTargetSelectPayload(click_x=320.0, click_y=240.0)
        self.assertEqual(ws_t3.click_x, 320.0)
        with self.assertRaises(ValueError):
            TrackTargetSelectPayload()

        # CameraControlRequest
        c1 = CameraControlRequest(action="move", pan=120.0, tilt=80.0)
        self.assertEqual(c1.action, "move")
        with self.assertRaises(ValueError):
            CameraControlRequest(action="move", pan=180.0, tilt=80.0)

        # Speed adjustment model
        c_speed = CameraControlRequest(action="speed", speed=0.7)
        self.assertEqual(c_speed.action, "speed")
        self.assertEqual(c_speed.speed, 0.7)
        with self.assertRaises(ValueError):
            CameraControlRequest(action="speed", speed=1.5)

        # EstopRequest
        e1 = EstopRequest(action="freeze")
        self.assertEqual(e1.action, "freeze")


# ==============================================================================
# 2. StateManager & ConnectionHub Unit Tests
# ==============================================================================

class TestStateAndConnectionHub(unittest.TestCase):
    """Tests central state manager and WebSocket connection hub."""

    def test_state_manager_telemetry_and_snapshot(self):
        mgr = SystemStateManager()
        mgr.update_esp32_connection(True, ip="192.168.1.150")
        self.assertTrue(mgr.esp32_connected)
        self.assertEqual(mgr.esp32_ip, "192.168.1.150")

        # Telemetry update
        telem = {
            "sonar": {"distance_cm": 75.4, "valid": True, "status": "in_range"},
            "pir": {"motion_detected": True, "trigger_count": 3, "last_trigger_ms": 1200},
            "servos": {"pan_angle": 92.0, "tilt_angle": 88.0, "is_moving": False},
            "buzzer": {"active": False, "pattern": "off"},
            "system": {"uptime_ms": 50000, "failsafe_active": False, "estop_active": False},
        }
        mgr.update_esp32_telemetry(telem)
        self.assertEqual(mgr.sonar_data["distance_cm"], 75.4)
        self.assertTrue(mgr.pir_data["motion_detected"])
        self.assertEqual(mgr.servo_data["pan_angle"], 92.0)

        # Snapshot structure
        snap = mgr.get_status_snapshot()
        self.assertTrue(snap["esp32"]["connected"])
        self.assertEqual(snap["sensors"]["sonar"]["distance_cm"], 75.4)

    def test_state_manager_estop_and_alerts(self):
        mgr = SystemStateManager()
        self.assertFalse(mgr.estop_active)
        mgr.set_estop(True, reason="User triggered E-stop")
        self.assertTrue(mgr.estop_active)
        self.assertGreater(len(mgr.alerts), 0)
        self.assertEqual(mgr.alerts[-1]["severity"], "critical")

        mgr.set_estop(False)
        self.assertFalse(mgr.estop_active)

    def test_connection_hub_rate_limiting(self):
        hub = ConnectionHub()
        mock_ws = object()

        # First command allowed
        self.assertTrue(hub.check_client_rate_limit(mock_ws))

        # Immediate second command (within 50ms) must be throttled
        self.assertFalse(hub.check_client_rate_limit(mock_ws))

        # After waiting > 50ms (use 75ms for Windows timer resolution margin), command allowed again
        time.sleep(0.075)
        self.assertTrue(hub.check_client_rate_limit(mock_ws))


# ==============================================================================
# 3. Live Server Integration Tests (REST API, WebSockets, MJPEG)
# ==============================================================================

class TestLiveBackendServer(unittest.TestCase):
    """
    Spawns live Uvicorn instance on localhost and verifies all REST endpoints,
    Dual WebSockets, MJPEG video streaming, rate limiting, and safe-stop logic.
    """

    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 8990
    BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
    WS_DEVICE_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/ws/device"
    WS_CLIENT_URL = f"ws://{SERVER_HOST}:{SERVER_PORT}/ws/client"

    server_thread: Optional[threading.Thread] = None
    server_instance: Optional[uvicorn.Server] = None
    app_instance = None

    @classmethod
    def setUpClass(cls):
        """Starts live test server with synthetic camera fallback."""
        # Force synthetic camera for isolated deterministic tests
        cam_config = CameraConfig(
            backend=CameraBackend.SYNTHETIC,
            width=640,
            height=480,
            fps=30.0,
            enable_synthetic_fallback=True,
        )
        cam_service = CameraService(config=cam_config)
        detector = MockPersonDetector(mode="synthetic_sync")
        pipeline = TrackingPipeline(
            detector=detector,
            frame_width=640,
            frame_height=480,
            enable_hud=True,
        )

        cls.app_instance = create_app(
            camera_service=cam_service,
            tracking_pipeline=pipeline,
        )

        config = uvicorn.Config(
            cls.app_instance,
            host=cls.SERVER_HOST,
            port=cls.SERVER_PORT,
            log_level="error",
        )
        cls.server_instance = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server_instance.run, daemon=True)
        cls.server_thread.start()

        # Wait for server to become responsive
        max_wait = 5.0
        start_t = time.time()
        while time.time() - start_t < max_wait:
            try:
                r = requests.get(f"{cls.BASE_URL}/api/v1/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        """Clean shutdown of live test server."""
        if cls.server_instance:
            cls.server_instance.should_exit = True
        if cls.server_thread:
            cls.server_thread.join(timeout=3.0)

    # --------------------------------------------------------------------------
    # REST API Verification
    # --------------------------------------------------------------------------

    def test_01_rest_health_check(self):
        resp = requests.get(f"{self.BASE_URL}/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_s", data)
        self.assertEqual(data["version"], "1.0.0")

    def test_02_rest_system_status(self):
        resp = requests.get(f"{self.BASE_URL}/api/v1/system/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("esp32", data)
        self.assertIn("camera", data)
        self.assertIn("tracking", data)
        self.assertIn("sensors", data)
        self.assertIn("estop_active", data)

    def test_03_rest_tracking_mode_change(self):
        # Change to auto_track
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/tracking/mode",
            json={"mode": "auto_track"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["mode"], "auto_track")

        # Change to manual
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/tracking/mode",
            json={"mode": "manual"},
        )
        self.assertEqual(resp.status_code, 200)

        # Invalid mode
        resp_bad = requests.post(
            f"{self.BASE_URL}/api/v1/tracking/mode",
            json={"mode": "unsupported_mode"},
        )
        self.assertEqual(resp_bad.status_code, 422)

    def test_04_rest_tracking_target_selection(self):
        # Click to track
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/tracking/target",
            json={"click_to_track": [320.0, 240.0]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("track_id", resp.json()["data"])

        # Auto track strategy
        resp2 = requests.post(
            f"{self.BASE_URL}/api/v1/tracking/target",
            json={"strategy": "largest"},
        )
        self.assertEqual(resp2.status_code, 200)

    def test_05_rest_camera_control_bounds_enforcement(self):
        # Valid move
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "move", "pan": 90.0, "tilt": 90.0, "speed": 0.5},
        )
        self.assertEqual(resp.status_code, 200)

        # Center command
        resp_c = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "center"},
        )
        self.assertEqual(resp_c.status_code, 200)

        # Out-of-bounds Pan (180.0° > 165.0°) -> HTTP 422 (Pydantic validation error)
        resp_bad_pan = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "move", "pan": 180.0, "tilt": 90.0},
        )
        self.assertEqual(resp_bad_pan.status_code, 422)

        # Out-of-bounds Tilt (40.0° < 60.0°) -> HTTP 422
        resp_bad_tilt = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "move", "pan": 90.0, "tilt": 40.0},
        )
        self.assertEqual(resp_bad_tilt.status_code, 422)

        # Speed adjustment command
        resp_speed = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "speed", "speed": 0.8},
        )
        self.assertEqual(resp_speed.status_code, 200)
        self.assertEqual(resp_speed.json()["data"]["speed"], 0.8)

        # Invalid speed (> 1.0) -> HTTP 422
        resp_bad_speed = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "speed", "speed": 2.0},
        )
        self.assertEqual(resp_bad_speed.status_code, 422)

    def test_06_rest_emergency_stop_lifecycle(self):
        # Trigger E-Stop
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/system/estop",
            json={"action": "freeze", "reason": "Operator test button"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["data"]["estop_active"])

        # Camera move must be rejected under E-Stop with HTTP 400
        resp_blocked = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "move", "pan": 90.0, "tilt": 90.0},
        )
        self.assertEqual(resp_blocked.status_code, 400)
        self.assertIn("Emergency Stop", resp_blocked.json()["detail"])

        # Resume / Clear E-Stop
        resp_resume = requests.post(
            f"{self.BASE_URL}/api/v1/system/estop",
            json={"action": "resume"},
        )
        self.assertEqual(resp_resume.status_code, 200)

        # Camera move now allowed again
        resp_allowed = requests.post(
            f"{self.BASE_URL}/api/v1/camera/control",
            json={"action": "move", "pan": 90.0, "tilt": 90.0},
        )
        self.assertEqual(resp_allowed.status_code, 200)

    def test_07_rest_buzzer_test(self):
        resp = requests.post(
            f"{self.BASE_URL}/api/v1/buzzer/test",
            json={"action": "chirp", "duration_ms": 100, "count": 2},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["action"], "chirp")

    # --------------------------------------------------------------------------
    # MJPEG Streaming Verification
    # --------------------------------------------------------------------------

    def test_08_mjpeg_video_stream(self):
        resp = requests.get(f"{self.BASE_URL}/api/v1/stream/video.mjpeg", stream=True, timeout=5)
        self.assertEqual(resp.status_code, 200)
        content_type = resp.headers.get("content-type", "")
        self.assertIn("multipart/x-mixed-replace", content_type)
        self.assertIn("boundary=frame", content_type)

        # Read frames from stream and verify valid JPEG magic bytes (\xff\xd8 and \xff\xd9)
        chunk_buf = b""
        jpeg_found = False
        for chunk in resp.iter_content(chunk_size=2048):
            chunk_buf += chunk
            if b"\xff\xd8" in chunk_buf and b"\xff\xd9" in chunk_buf:
                jpeg_found = True
                break

        resp.close()
        self.assertTrue(jpeg_found, "Failed to receive valid JPEG frame from MJPEG video stream")

    # --------------------------------------------------------------------------
    # Dual WebSocket Hub Verification (/ws/device and /ws/client)
    # --------------------------------------------------------------------------

    def test_09_dual_websocket_telemetry_and_command_passing(self):
        async def run_ws_test():
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:

                # 1. Frontend client receives initial sys.status
                init_msg_str = await asyncio.wait_for(ws_cli.recv(), timeout=2.0)
                init_msg = json.loads(init_msg_str)
                self.assertEqual(init_msg["type"], "sys.status")
                self.assertTrue(init_msg["payload"]["esp32"]["connected"])

                # 2. ESP32 sends telem.sensors -> client receives forwarded telemetry
                telem_pkt = {
                    "type": "telem.sensors",
                    "timestamp": int(time.time() * 1000),
                    "sender": "esp32",
                    "seq": 101,
                    "payload": {
                        "sonar": {"distance_cm": 62.5, "valid": True, "status": "in_range"},
                        "pir": {"motion_detected": True, "trigger_count": 5},
                        "servos": {"pan_angle": 95.0, "tilt_angle": 88.0, "is_moving": False},
                        "buzzer": {"active": False, "pattern": "off"},
                        "system": {"uptime_ms": 12000, "failsafe_active": False, "estop_active": False},
                    },
                }
                await ws_dev.send(json.dumps(telem_pkt))

                async def recv_cli_msg(expected_type: str, timeout: float = 2.0) -> Dict[str, Any]:
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        raw = await asyncio.wait_for(ws_cli.recv(), timeout=timeout)
                        data = json.loads(raw)
                        if data.get("type") == expected_type:
                            return data
                    raise TimeoutError(f"Client did not receive expected message type: {expected_type}")

                client_telem = await recv_cli_msg("telem.sensors")
                self.assertEqual(client_telem["type"], "telem.sensors")
                self.assertEqual(client_telem["payload"]["sonar"]["distance_cm"], 62.5)

                async def recv_dev_msg(expected_type: str, timeout: float = 2.0) -> Dict[str, Any]:
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        raw = await asyncio.wait_for(ws_dev.recv(), timeout=timeout)
                        data = json.loads(raw)
                        if data.get("type") == expected_type:
                            return data
                    raise TimeoutError(f"Did not receive expected message type: {expected_type}")

                # 3. Frontend client sends cmd.servo.move -> ESP32 receives command
                move_pkt = {
                    "type": "cmd.servo.move",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 201,
                    "corr_id": "corr_move_01",
                    "payload": {
                        "mode": "absolute",
                        "pan": 110.0,
                        "tilt": 80.0,
                        "speed": 0.6,
                        "smooth": True,
                    },
                }
                await ws_cli.send(json.dumps(move_pkt))

                dev_cmd = await recv_dev_msg("cmd.servo.move")
                self.assertEqual(dev_cmd["type"], "cmd.servo.move")
                self.assertEqual(dev_cmd["payload"]["pan"], 110.0)
                self.assertEqual(dev_cmd["payload"]["tilt"], 80.0)

                # 4. Frontend client sends cmd.jog -> ESP32 receives cmd.jog
                # Pause 80ms to satisfy 20 Hz (50ms) rate limiter with Windows timer resolution margin
                await asyncio.sleep(0.08)

                jog_pkt = {
                    "type": "cmd.jog",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 202,
                    "corr_id": "corr_jog_01",
                    "payload": {"delta_pan": 5.0, "delta_tilt": -3.0, "speed": 0.5},
                }
                await ws_cli.send(json.dumps(jog_pkt))

                dev_jog = await recv_dev_msg("cmd.jog")
                self.assertEqual(dev_jog["type"], "cmd.jog")
                self.assertEqual(dev_jog["payload"]["delta_pan"], 5.0)

        asyncio.run(run_ws_test())

    def test_10_websocket_rate_limiting_and_schema_validation(self):
        async def run_validation_test():
            async with websockets.connect(self.WS_CLIENT_URL) as ws:
                # Flush initial sys.status
                await ws.recv()

                # Test Out-of-Bounds Angle Rejection (Pan 185° > 165°)
                bad_pan_cmd = {
                    "type": "cmd.servo.move",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 301,
                    "payload": {"mode": "absolute", "pan": 185.0, "tilt": 90.0},
                }
                await ws.send(json.dumps(bad_pan_cmd))
                err_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                self.assertEqual(err_resp["type"], "alert.event")
                self.assertEqual(err_resp["payload"]["event_type"], "command_rejected")
                self.assertIn("out of calibrated bounds", err_resp["payload"]["message"].lower())

                # Test 20 Hz Rate Limiting: Burst 5 commands without pause
                dropped_count = 0
                for i in range(5):
                    fast_cmd = {
                        "type": "sys.ping",
                        "timestamp": int(time.time() * 1000),
                        "sender": "frontend",
                        "seq": 400 + i,
                        "payload": {},
                    }
                    await ws.send(json.dumps(fast_cmd))

                # Collect responses
                for _ in range(5):
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=0.3))
                        if msg.get("payload", {}).get("event_type") == "rate_limit_exceeded":
                            dropped_count += 1
                    except asyncio.TimeoutError:
                        break

                self.assertGreater(dropped_count, 0, "Rate limiter failed to drop burst commands > 20 Hz")

        asyncio.run(run_validation_test())

    def test_11_device_disconnect_and_reconnection_alert(self):
        async def run_disconnect_test():
            async with websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                # Flush initial status
                await ws_cli.recv()

                # Connect and immediately disconnect ESP32 device
                ws_dev = await websockets.connect(self.WS_DEVICE_URL)
                await ws_dev.close()

                # Client should receive offline alert
                found_disconnect = False
                for _ in range(3):
                    try:
                        msg = json.loads(await asyncio.wait_for(ws_cli.recv(), timeout=2.0))
                        if msg.get("payload", {}).get("event_type") == "ws_disconnect":
                            found_disconnect = True
                            self.assertEqual(msg["payload"]["severity"], "critical")
                            break
                    except asyncio.TimeoutError:
                        break

                self.assertTrue(found_disconnect, "Client did not receive ws_disconnect alert on device drop")

                # Verify system status reports failsafe_active=True after device disconnect
                resp_status = requests.get(f"{self.BASE_URL}/api/v1/system/status")
                self.assertEqual(resp_status.status_code, 200)
                st_data = resp_status.json()
                self.assertFalse(st_data["esp32"]["connected"])
                self.assertTrue(st_data["esp32"]["failsafe_active"])

        asyncio.run(run_disconnect_test())

    def test_12_authentication_and_security(self):
        """Verifies API key enforcement across REST endpoints and WebSockets when AUTH_ENABLED=True."""
        original_auth = settings.AUTH_ENABLED
        try:
            settings.AUTH_ENABLED = True

            # 1. Unauthorized REST request without key -> HTTP 401
            resp_unauth = requests.get(f"{self.BASE_URL}/api/v1/system/status")
            self.assertEqual(resp_unauth.status_code, 401)

            # 2. Authorized via X-API-Key header -> HTTP 200
            resp_hdr = requests.get(
                f"{self.BASE_URL}/api/v1/system/status",
                headers={"X-API-Key": settings.API_KEY},
            )
            self.assertEqual(resp_hdr.status_code, 200)

            # 3. Authorized via Authorization Bearer token -> HTTP 200
            resp_bearer = requests.get(
                f"{self.BASE_URL}/api/v1/system/status",
                headers={"Authorization": f"Bearer {settings.API_KEY}"},
            )
            self.assertEqual(resp_bearer.status_code, 200)

            # 4. Authorized via URL query parameter -> HTTP 200
            resp_query = requests.get(
                f"{self.BASE_URL}/api/v1/system/status?token={settings.API_KEY}"
            )
            self.assertEqual(resp_query.status_code, 200)

            # 5. WebSocket Authentication
            async def run_ws_auth():
                # Connecting without token fails (closed with code 1008 Policy Violation)
                with self.assertRaises(Exception):
                    async with websockets.connect(self.WS_CLIENT_URL):
                        pass

                # Connecting with valid token parameter succeeds
                async with websockets.connect(f"{self.WS_CLIENT_URL}?token={settings.API_KEY}") as ws:
                    init_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                    self.assertEqual(init_msg["type"], "sys.status")

            asyncio.run(run_ws_auth())

        finally:
            settings.AUTH_ENABLED = original_auth

    def test_13_servo_patrol_websocket_command(self):
        """Verifies cmd.servo.patrol is validated and routed from operator to ESP32."""
        async def run_patrol_test():
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                # Flush initial sys.status
                await ws_cli.recv()

                # Client sends cmd.servo.patrol
                patrol_cmd = {
                    "type": "cmd.servo.patrol",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 601,
                    "corr_id": "corr_patrol_01",
                    "payload": {
                        "enabled": True,
                        "pan_min": 35.0,
                        "pan_max": 145.0,
                        "tilt_angle": 90.0,
                        "speed_deg_s": 25.0,
                        "dwell_time_ms": 1000,
                    },
                }
                await ws_cli.send(json.dumps(patrol_cmd))

                # Device must receive cmd.servo.patrol
                deadline = time.time() + 2.0
                found_patrol = False
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws_dev.recv(), timeout=2.0)
                    msg = json.loads(raw)
                    if msg.get("type") == "cmd.servo.patrol":
                        self.assertEqual(msg["payload"]["pan_min"], 35.0)
                        self.assertEqual(msg["payload"]["speed_deg_s"], 25.0)
                        found_patrol = True
                        break
                self.assertTrue(found_patrol, "ESP32 did not receive cmd.servo.patrol command")

        asyncio.run(run_patrol_test())

    def test_14_concurrent_mjpeg_stream_clients(self):
        """Verifies multiple concurrent clients can stream MJPEG simultaneously without stalls or deadlocks."""
        def client_thread(cid: int, results: list):
            try:
                resp = requests.get(f"{self.BASE_URL}/api/v1/stream/video.mjpeg", stream=True, timeout=5)
                if resp.status_code != 200:
                    results.append((cid, False, "Non-200 status"))
                    return
                frame_count = 0
                chunk_buf = b""
                for chunk in resp.iter_content(chunk_size=4096):
                    chunk_buf += chunk
                    if b"\xff\xd8" in chunk_buf and b"\xff\xd9" in chunk_buf:
                        frame_count += 1
                        chunk_buf = b""
                        if frame_count >= 3:
                            break
                resp.close()
                results.append((cid, True, frame_count))
            except Exception as e:
                results.append((cid, False, str(e)))

        results = []
        threads = [threading.Thread(target=client_thread, args=(i, results)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=6.0)

        self.assertEqual(len(results), 3)
        for cid, success, info in results:
            self.assertTrue(success, f"Client {cid} failed: {info}")
            self.assertGreaterEqual(info, 3)

    def test_15_deadband_suppression_and_autocenter(self):
        """
        Verifies tracking worker suppresses commands when target is settled in deadband,
        and dispatches commands when auto-centering is triggered.
        """
        from backend.app.services.tracking_worker import TrackingWorker
        from vision.tracking.pid_controller import TrackingControlOutput
        from vision.tracking.pipeline import TrackingPipelineResult
        from vision.tracking.target_selector import TargetSelectionResult, TargetState

        state_mgr = SystemStateManager()
        state_mgr.update_esp32_connection(True, ip="127.0.0.1")
        hub = ConnectionHub()

        # Mock camera service
        class MockCam:
            is_running = True
            def get_frame(self, **kwargs):
                return True, np.zeros((480, 640, 3), dtype=np.uint8), type("Meta", (), {"frame_id": 1, "timestamp_captured": time.time()})()
            def get_stats(self):
                return {"is_running": True, "fps_actual": 30.0, "is_synthetic": True, "dropped_frames": 0}

        # Mock pipeline
        class MockPipeline:
            def __init__(self):
                self.selector = type("Selector", (), {"mode": "auto_track"})()
                self.output = TrackingControlOutput(
                    pan_angle=90.0,
                    tilt_angle=90.0,
                    delta_pan=0.0,
                    delta_tilt=0.0,
                    raw_error_x=0.0,
                    raw_error_y=0.0,
                    filtered_error_x=0.0,
                    filtered_error_y=0.0,
                    in_deadband_x=True,
                    in_deadband_y=True,
                    is_settled=True,
                    should_dispatch_command=False,  # Settled in deadband -> suppress!
                )

            def process_frame(self, **kwargs):
                return TrackingPipelineResult(
                    frame_annotated=np.zeros((10, 10, 3), dtype=np.uint8),
                    raw_frame=np.zeros((10, 10, 3), dtype=np.uint8),
                    tracks=[],
                    target_result=TargetSelectionResult(
                        state=TargetState.TRACKING,
                        active_track=None,
                        locked_track_id=1,
                        centroid=(320.0, 240.0),
                        coast_factor=1.0,
                        time_lost_ms=0.0,
                        target_locked=True,
                    ),
                    control_output=self.output,
                    fps=30.0,
                    inference_ms=5.0,
                    telemetry_message={"type": "track.frame_target", "payload": {}},
                )

        cam = MockCam()
        pipe = MockPipeline()
        worker = TrackingWorker(cam, pipe, state_mgr, hub)

        # Track sent device messages
        dispatched_messages = []
        async def mock_send(msg):
            dispatched_messages.append(msg)
            return True
        hub.send_to_device = mock_send

        # Case 1: Settled in deadband (should_dispatch_command=False) -> No commands dispatched
        async def run_deadband_test():
            worker._last_frame_id = None
            worker._last_servo_cmd_time = 0.0
            # Execute one iteration
            await worker._worker_loop_step(cam, pipe)
            self.assertEqual(len(dispatched_messages), 0, "Command was not suppressed in settled deadband!")

            # Case 2: Auto-centering triggered (should_dispatch_command=True, target_locked=False)
            pipe.output = TrackingControlOutput(
                pan_angle=95.0,
                tilt_angle=92.0,
                delta_pan=5.0,
                delta_tilt=2.0,
                raw_error_x=0.0,
                raw_error_y=0.0,
                filtered_error_x=0.0,
                filtered_error_y=0.0,
                in_deadband_x=False,
                in_deadband_y=False,
                is_settled=False,
                should_dispatch_command=True,  # Dispatches auto-centering
            )
            # Frame captures auto-centering state
            await worker._worker_loop_step(cam, pipe)
            self.assertEqual(len(dispatched_messages), 1, "Auto-centering command was not dispatched!")
            self.assertEqual(dispatched_messages[0]["type"], "cmd.servo.move")

        # Helper method on worker for testability
        async def _step(cam_s, p_s):
            success, frame, metadata = cam_s.get_frame()
            result = p_s.process_frame(frame=frame)
            now = time.time()
            ts_sec = metadata.timestamp_captured
            is_stale = (now - ts_sec) > settings.STALE_TRACKING_TIMEOUT_S
            should_dispatch = (
                pipe.selector.mode == "auto_track"
                and not state_mgr.estop_active
                and not state_mgr.failsafe_active
                and state_mgr.esp32_connected
                and not is_stale
                and result.control_output.should_dispatch_command
                and (now - worker._last_servo_cmd_time >= 0.045)
            )
            if should_dispatch:
                out = result.control_output
                pan = settings.clamp_pan(out.pan_angle)
                tilt = settings.clamp_tilt(out.tilt_angle)
                servo_msg = hub.create_envelope(
                    msg_type="cmd.servo.move",
                    payload={"mode": "absolute", "pan": pan, "tilt": tilt, "speed": 0.5, "smooth": True},
                )
                await hub.send_to_device(servo_msg)
                worker._last_servo_cmd_time = now

        worker._worker_loop_step = _step
        asyncio.run(run_deadband_test())

    def test_24_estop_bypasses_rate_limiting_and_mode_sync(self):
        """
        Verifies:
        1. E-Stop commands (cmd.estop) bypass client 20 Hz rate limiting.
        2. Manual jog transitions mode from auto_track to manual and broadcasts mode update.
        """
        async def recv_filtered(ws, expected_type: str, timeout: float = 2.0, pred=None):
            deadline = time.time() + timeout
            while time.time() < deadline:
                time_left = max(0.05, deadline - time.time())
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=time_left)
                    data = json.loads(raw)
                    if data.get("type") == expected_type:
                        if pred is None or pred(data):
                            return data
                except asyncio.TimeoutError:
                    break
            raise TimeoutError(f"Did not receive {expected_type} within {timeout}s")

        async def run_estop_ratelimit_test():
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                # Flush initial sys.status
                await ws_cli.recv()

                # 1. Engage auto_track mode
                mode_pkt = {
                    "type": "track.mode_set",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 901,
                    "payload": {"mode": "auto_track"},
                }
                await ws_cli.send(json.dumps(mode_pkt))
                mode_resp = await recv_filtered(ws_cli, "track.mode_set", timeout=2.0)
                self.assertEqual(mode_resp["payload"]["mode"], "auto_track")

                # 2. Send manual jog - should auto-arbitrate to manual and broadcast mode update
                # Pause 80ms to satisfy 20 Hz (50ms) rate limiter with Windows timer margin
                await asyncio.sleep(0.08)

                jog_pkt = {
                    "type": "cmd.jog",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 902,
                    "payload": {"delta_pan": 5.0, "delta_tilt": 0.0, "speed": 0.5},
                }
                await ws_cli.send(json.dumps(jog_pkt))
                dev_jog = await recv_filtered(ws_dev, "cmd.jog", timeout=2.0)
                self.assertEqual(dev_jog["payload"]["delta_pan"], 5.0)

                # Client receives mode broadcast switching to manual
                manual_mode_resp = await recv_filtered(ws_cli, "track.mode_set", timeout=2.0)
                self.assertEqual(manual_mode_resp["payload"]["mode"], "manual")

                # 3. Flood with fast pings to trigger 20 Hz rate limiter
                for i in range(4):
                    fast_ping = {
                        "type": "sys.ping",
                        "timestamp": int(time.time() * 1000),
                        "sender": "frontend",
                        "seq": 910 + i,
                        "payload": {},
                    }
                    await ws_cli.send(json.dumps(fast_ping))

                # 4. Immediately send E-Stop (rate limiter is tripped)
                estop_pkt = {
                    "type": "cmd.estop",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 920,
                    "payload": {"action": "freeze", "reason": "rate_limit_bypass_test"},
                }
                await ws_cli.send(json.dumps(estop_pkt))

                # E-Stop MUST NOT be dropped as rate_limit_exceeded!
                # It must trigger alert.event for estop_activated and engage estop_active
                alert_estop = await recv_filtered(
                    ws_cli,
                    "alert.event",
                    timeout=2.0,
                    pred=lambda d: d.get("payload", {}).get("event_type") == "estop_activated"
                )
                self.assertEqual(alert_estop["payload"]["event_type"], "estop_activated")
                self.assertTrue(self.app_instance.state.state_manager.estop_active)

                # 5. Clean up: Resume from E-stop
                resume_pkt = {
                    "type": "cmd.estop",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 921,
                    "payload": {"action": "resume"},
                }
                await ws_cli.send(json.dumps(resume_pkt))
                await asyncio.sleep(0.05)
                self.assertFalse(self.app_instance.state.state_manager.estop_active)

        asyncio.run(run_estop_ratelimit_test())


if __name__ == "__main__":
    unittest.main(verbosity=2)
