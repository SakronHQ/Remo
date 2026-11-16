"""
test_system_integration_e2e.py
Automated End-to-End System Integration Test Suite for SmartVision Phase 8.

Verifies complete multi-tier orchestration across all 4 system tiers:
  Tier 1: Embedded Hardware / Virtual ESP32-S3 Firmware (servos, PCA9685, HC-SR04 sonar, HC-SR501 PIR, buzzer)
  Tier 2: PC Camera Subsystem (Synthetic test pattern / capture service)
  Tier 3: Computer Vision & Tracking Engine (YOLO / Mock detector, ByteTrack, Dual-Axis PID controller)
  Tier 4: Central FastAPI Gateway (Dual WebSockets /ws/device & /ws/client, MJPEG stream, REST API)
  Tier 5: Operator Client (Full protocol validation, command routing, telemetry ingestion)

Test Scenarios:
  Test 1: Full multi-tier lifecycle startup & handshake.
  Test 2: Manual camera control & speed responsiveness.
  Test 3: Multi-person detection & ByteTrack ID persistence across frames.
  Test 4: Target selection & autonomous closed-loop pan/tilt tracking.
  Test 5: Sensor telemetry ingestion & proximity alerts (HC-SR04 < 20 cm & HC-SR501 PIR).
  Test 6: Network disconnection, 800 ms hardware watchdog trip, and safe-stop failsafe.
  Test 7: Automatic recovery and re-centering upon connection restoration.
  Test 8: Long-running stress test (continuous closed-loop tracking, memory leak & queue check).
"""

import asyncio
import json
import logging
import math
import os
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
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

from backend.app.config import Settings, settings
from backend.app.main import create_app
from backend.app.schemas.protocol import SmartVisionEnvelope
from backend.app.services.connection_hub import ConnectionHub
from backend.app.services.state_manager import SystemStateManager
from tests.mock_esp32_firmware import MockESP32Firmware, VirtualPCA9685Servos
from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.detection.mock_detector import MockPersonDetector
from vision.detection.types import PersonDetection
from vision.tracking.bytetrack import TrackState
from vision.tracking.pid_controller import DualAxisTrackingController
from vision.tracking.pipeline import TrackingPipeline, TrackingPipelineResult
from vision.tracking.target_selector import TargetState

logger = logging.getLogger("SmartVision.E2ETest")


def find_free_port() -> int:
    """Finds an ephemeral free TCP port for test isolation."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def recv_filtered_msg(
    ws,
    expected_type: str,
    timeout: float = 3.0,
    pred: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Receives WebSocket messages until a message matching expected_type (and optional predicate)
    is received, ignoring intermediate telemetry packets.
    """
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
    raise TimeoutError(f"Did not receive expected message type '{expected_type}' within {timeout:.1f}s")


class TestSystemIntegrationE2E(unittest.TestCase):
    """
    Automated Phase 8 End-to-End System Integration Test Suite.
    Runs the full multi-tier stack and executes all 8 field verification scenarios.
    """

    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 0
    BASE_URL = ""
    WS_DEVICE_URL = ""
    WS_CLIENT_URL = ""

    server_instance: Optional[uvicorn.Server] = None
    server_thread: Optional[threading.Thread] = None
    cam_service: Optional[CameraService] = None
    detector: Optional[MockPersonDetector] = None
    pipeline: Optional[TrackingPipeline] = None
    app_instance: Optional[Any] = None

    # Performance benchmarks collected across tests
    benchmarks: Dict[str, Any] = {}

    @classmethod
    def setUpClass(cls):
        """Starts live Gateway with SyntheticCamera and TrackingPipeline on an ephemeral port."""
        cls.SERVER_PORT = find_free_port()
        cls.BASE_URL = f"http://{cls.SERVER_HOST}:{cls.SERVER_PORT}"
        cls.WS_DEVICE_URL = f"ws://{cls.SERVER_HOST}:{cls.SERVER_PORT}/ws/device"
        cls.WS_CLIENT_URL = f"ws://{cls.SERVER_HOST}:{cls.SERVER_PORT}/ws/client"

        # 1. Initialize Synthetic Camera
        cam_config = CameraConfig(
            backend=CameraBackend.SYNTHETIC,
            device_index=0,
            width=640,
            height=480,
            fps=30,
            enable_synthetic_fallback=True,
        )
        cls.cam_service = CameraService(config=cam_config)
        cls.cam_service.start()

        # 2. Initialize Detection & Tracking Pipeline
        cls.detector = MockPersonDetector(mode="manual")
        cls.pipeline = TrackingPipeline(
            detector=cls.detector,
            frame_width=640,
            frame_height=480,
            enable_hud=True,
        )

        # 3. Create FastAPI app with injected test singletons
        cls.app_instance = create_app(
            camera_service=cls.cam_service,
            tracking_pipeline=cls.pipeline,
        )

        # 4. Start Uvicorn in background thread
        config = uvicorn.Config(
            cls.app_instance,
            host=cls.SERVER_HOST,
            port=cls.SERVER_PORT,
            log_level="error",
        )
        cls.server_instance = uvicorn.Server(config)
        cls.server_thread = threading.Thread(target=cls.server_instance.run, daemon=True)
        cls.server_thread.start()

        # 5. Wait for server readiness
        max_wait = 6.0
        start_t = time.time()
        while time.time() - start_t < max_wait:
            try:
                r = requests.get(f"{cls.BASE_URL}/api/v1/health", timeout=0.5)
                if r.status_code == 200:
                    break
            except Exception:
                time.sleep(0.08)

    @classmethod
    def tearDownClass(cls):
        """Clean shutdown of live test server and camera capture thread."""
        if cls.server_instance:
            cls.server_instance.should_exit = True
        if cls.server_thread:
            cls.server_thread.join(timeout=3.0)
        if cls.cam_service:
            cls.cam_service.stop()

    def setUp(self):
        """Reset detector and pipeline state prior to each test scenario."""
        if self.detector:
            self.detector.set_detections(None)
            self.detector.set_mode("manual")
        if self.pipeline:
            self.pipeline.reset()

    # ==========================================================================
    # TEST 1: Full Multi-Tier Lifecycle Startup & Handshake
    # ==========================================================================
    def test_01_full_multi_tier_lifecycle_startup_and_handshake(self):
        """
        Scenario 1: Connect all tiers simultaneously.
        Verifies CameraService capture, TrackingPipeline, Gateway startup,
        ESP32-S3 /ws/device registration, Web client /ws/client subscription,
        initial state snapshot broadcasting, and sys.ping/sys.pong RTT synchronization.
        """
        async def run_lifecycle_test():
            t0 = time.perf_counter()
            async with websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                # 1. Web client receives initial sys.status snapshot
                snapshot_raw = await asyncio.wait_for(ws_cli.recv(), timeout=2.5)
                snapshot = json.loads(snapshot_raw)
                self.assertEqual(snapshot["type"], "sys.status")
                payload = snapshot["payload"]

                # Assert 5-field outer envelope structure
                for field in ("type", "timestamp", "sender", "seq", "payload"):
                    self.assertIn(field, snapshot)

                # Verify sub-tier states in snapshot
                self.assertTrue(payload["camera"]["running"])
                self.assertTrue(payload["camera"]["synthetic"])
                self.assertEqual(payload["tracking"]["mode"], "idle")
                self.assertFalse(payload["estop_active"])

                # 2. Connect ESP32 device -> client receives 'device_connected' alert event
                async with websockets.connect(self.WS_DEVICE_URL) as ws_dev:
                    conn_alert = await recv_filtered_msg(
                        ws_cli, "alert.event", timeout=2.5,
                        pred=lambda d: d.get("payload", {}).get("event_type") == "device_connected",
                    )
                    self.assertEqual(conn_alert["payload"]["event_type"], "device_connected")
                    self.assertEqual(conn_alert["payload"]["severity"], "info")

                    # 3. Bi-directional Ping/Pong Handshake: Device -> Gateway -> Device
                    ping_ts = int(time.time() * 1000)
                    ping_pkt = {
                        "type": "sys.ping",
                        "timestamp": ping_ts,
                        "sender": "esp32",
                        "seq": 1,
                        "corr_id": "handshake_dev_01",
                        "payload": {},
                    }
                    await ws_dev.send(json.dumps(ping_pkt))
                    pong_dev = await recv_filtered_msg(ws_dev, "sys.pong", timeout=2.0)
                    self.assertEqual(pong_dev["payload"]["echo_timestamp"], ping_ts)
                    self.assertEqual(pong_dev.get("corr_id"), "handshake_dev_01")

                    # 4. Bi-directional Ping/Pong Handshake: Client -> Gateway -> Client
                    cli_ping_ts = int(time.time() * 1000)
                    cli_ping_pkt = {
                        "type": "sys.ping",
                        "timestamp": cli_ping_ts,
                        "sender": "frontend",
                        "seq": 2,
                        "corr_id": "handshake_cli_01",
                        "payload": {},
                    }
                    await ws_cli.send(json.dumps(cli_ping_pkt))
                    pong_cli = await recv_filtered_msg(ws_cli, "sys.pong", timeout=2.0)
                    self.assertEqual(pong_cli["payload"]["echo_timestamp"], cli_ping_ts)
                    self.assertEqual(pong_cli.get("corr_id"), "handshake_cli_01")

                    # 5. Verify REST API endpoints
                    r_health = requests.get(f"{self.BASE_URL}/api/v1/health")
                    self.assertEqual(r_health.status_code, 200)
                    self.assertEqual(r_health.json()["status"], "ok")

                    r_status = requests.get(f"{self.BASE_URL}/api/v1/system/status")
                    self.assertEqual(r_status.status_code, 200)
                    st = r_status.json()
                    self.assertTrue(st["esp32"]["connected"])
                    self.assertTrue(st["camera"]["running"])

                    startup_latency_ms = (time.perf_counter() - t0) * 1000.0
                    TestSystemIntegrationE2E.benchmarks["startup_handshake_ms"] = round(startup_latency_ms, 2)

        asyncio.run(run_lifecycle_test())

    # ==========================================================================
    # TEST 2: Manual Camera Control & Speed Responsiveness
    # ==========================================================================
    def test_02_manual_camera_control_and_speed_responsiveness(self):
        """
        Scenario 2: Manual camera control & speed responsiveness.
        Dispatches D-pad/Joystick manual move and jog commands from Web client.
        Verifies Gateway bounds validation, ESP32 discrete slew interpolation,
        slew rate scaling by speed factor, and telem.sensors position gauge feedback.
        """
        async def run_manual_control_test():
            esp = MockESP32Firmware()
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:

                # Flush initial snapshot
                await ws_cli.recv()

                # 1. Send manual absolute move: Pan 125.0°, Tilt 75.0°, Speed 0.6
                t_cmd_start = time.perf_counter()
                cmd_move = {
                    "type": "cmd.servo.move",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 10,
                    "corr_id": "corr_move_02",
                    "payload": {
                        "mode": "absolute",
                        "pan": 125.0,
                        "tilt": 75.0,
                        "speed": 0.6,
                        "smooth": True,
                    },
                }
                await ws_cli.send(json.dumps(cmd_move))

                # Device receives validated command over /ws/device
                dev_cmd = await recv_filtered_msg(ws_dev, "cmd.servo.move", timeout=2.0)
                cmd_roundtrip_ms = (time.perf_counter() - t_cmd_start) * 1000.0
                TestSystemIntegrationE2E.benchmarks["manual_cmd_roundtrip_ms"] = round(cmd_roundtrip_ms, 2)

                self.assertEqual(dev_cmd["payload"]["pan"], 125.0)
                self.assertEqual(dev_cmd["payload"]["tilt"], 75.0)
                self.assertEqual(dev_cmd["payload"]["speed"], 0.6)

                # 2. ESP32 processes command and applies 50 Hz discrete slew interpolation
                esp.handle_inbound_message(json.dumps(dev_cmd))
                self.assertEqual(esp.servos.target_pan, 125.0)
                self.assertEqual(esp.servos.target_tilt, 75.0)

                # Slew rate at speed=0.6: 10 + (0.6 * 110) = 76.0 deg/s
                self.assertAlmostEqual(esp.servos.slew_rate, 76.0, delta=1.0)

                # Step slew 100ms (5 steps of dt=0.02)
                for _ in range(5):
                    esp.servos.update(0.02)

                # Position slews smoothly toward target rather than jumping immediately
                self.assertGreater(esp.servos.current_pan, 90.0)
                self.assertLess(esp.servos.current_pan, 125.0)
                self.assertLess(esp.servos.current_tilt, 90.0)
                self.assertGreater(esp.servos.current_tilt, 75.0)
                self.assertTrue(esp.servos.is_moving)

                # 3. ESP32 transmits updated telem.sensors back to Gateway
                telem_pkt = esp.generate_telemetry()
                await ws_dev.send(json.dumps(telem_pkt))

                # Client receives forwarded telem.sensors with position gauge feedback
                cli_telem = await recv_filtered_msg(ws_cli, "telem.sensors", timeout=2.0)
                servo_report = cli_telem["payload"]["servos"]
                self.assertEqual(servo_report["pan_target"], 125.0)
                self.assertEqual(servo_report["tilt_target"], 75.0)
                self.assertTrue(servo_report["is_moving"])

                # 4. Speed responsiveness comparison: speed=1.0 vs speed=0.2
                esp.servos.set_target(150.0, 90.0, speed_factor=1.0)
                slew_high = esp.servos.slew_rate
                esp.servos.set_target(150.0, 90.0, speed_factor=0.2)
                slew_low = esp.servos.slew_rate
                self.assertEqual(slew_high, 120.0)
                self.assertEqual(slew_low, 32.0)
                self.assertGreater(slew_high, slew_low)

                # 5. Jog Command Responsiveness (respect 20 Hz client rate limit)
                await asyncio.sleep(0.08)
                cur_p = esp.servos.current_pan
                cur_t = esp.servos.current_tilt
                cmd_jog = {
                    "type": "cmd.jog",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 11,
                    "corr_id": "corr_jog_01",
                    "payload": {"delta_pan": 5.0, "delta_tilt": -4.0, "speed": 0.5},
                }
                await ws_cli.send(json.dumps(cmd_jog))
                dev_jog = await recv_filtered_msg(ws_dev, "cmd.jog", timeout=2.5)
                esp.handle_inbound_message(json.dumps(dev_jog))
                self.assertAlmostEqual(esp.servos.target_pan, cur_p + 5.0, places=1)
                self.assertAlmostEqual(esp.servos.target_tilt, cur_t - 4.0, places=1)

        asyncio.run(run_manual_control_test())

    # ==========================================================================
    # TEST 3: Multi-Person Detection & ByteTrack ID Persistence
    # ==========================================================================
    def test_03_multiperson_detection_and_bytetrack_id_persistence(self):
        """
        Scenario 3: Multi-person detection & ByteTrack ID persistence.
        Injects multi-person synthetic detections into TrackingPipeline across 8 frames.
        Verifies concurrent track creation, persistent ID association without swaps,
        bounding box formatting, and track.frame_target telemetry serialization.
        """
        async def run_detection_test():
            async with websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                await ws_cli.recv()  # flush initial snapshot

                # Synthetic target A (left person) and target B (right person)
                # Tracking across 8 consecutive frames with smooth positional drift
                track_ids_seen: Dict[str, List[int]] = {"A": [], "B": []}
                frame_w, frame_h = 640, 480
                inference_times: List[float] = []

                for i in range(8):
                    # Drift target A from x=160 to x=188; target B from x=460 to x=432
                    cx_a = 160.0 + (i * 3.5)
                    cy_a = 200.0 + (i * 1.0)
                    cx_b = 460.0 - (i * 3.5)
                    cy_b = 220.0 - (i * 1.0)

                    det_a = PersonDetection(
                        x1=cx_a - 45.0, y1=cy_a - 90.0, x2=cx_a + 45.0, y2=cy_a + 90.0,
                        confidence=0.92,
                    )
                    det_b = PersonDetection(
                        x1=cx_b - 45.0, y1=cy_b - 90.0, x2=cx_b + 45.0, y2=cy_b + 90.0,
                        confidence=0.88,
                    )

                    self.detector.set_detections([det_a, det_b])

                    # Process synthetic dummy frame through tracking pipeline
                    dummy_frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
                    t_proc_start = time.perf_counter()
                    res: TrackingPipelineResult = self.pipeline.process_frame(dummy_frame)
                    proc_ms = (time.perf_counter() - t_proc_start) * 1000.0
                    inference_times.append(proc_ms)

                    # Extract active tracks
                    active_tracks = [t for t in res.tracks if t.state == TrackState.Tracked]
                    self.assertEqual(len(active_tracks), 2, f"Frame {i}: Expected 2 active tracks, got {len(active_tracks)}")

                    # Sort tracks by X position to match A (left) and B (right)
                    tracks_sorted = sorted(active_tracks, key=lambda t: t.tlwh[0])
                    track_ids_seen["A"].append(tracks_sorted[0].track_id)
                    track_ids_seen["B"].append(tracks_sorted[1].track_id)

                    # Verify Outer Protocol Envelope compliance
                    telem = res.telemetry_message
                    self.assertEqual(telem["type"], "track.frame_target")
                    self.assertIn("all_detections", telem["payload"])
                    self.assertEqual(len(telem["payload"]["all_detections"]), 2)

                # Assert Persistent ID Stability: Track IDs never swap or change across frames
                self.assertEqual(len(set(track_ids_seen["A"])), 1, "Track A ID changed during movement!")
                self.assertEqual(len(set(track_ids_seen["B"])), 1, "Track B ID changed during movement!")
                self.assertNotEqual(track_ids_seen["A"][0], track_ids_seen["B"][0], "Tracks A and B share identical ID!")

                # Verify client receives streamed track.frame_target telemetry with all detections over /ws/client
                cli_target_telem = await recv_filtered_msg(
                    ws_cli,
                    "track.frame_target",
                    timeout=2.5,
                    pred=lambda d: len(d.get("payload", {}).get("all_detections", [])) == 2,
                )
                self.assertEqual(cli_target_telem["type"], "track.frame_target")
                self.assertIn("all_detections", cli_target_telem["payload"])
                self.assertEqual(len(cli_target_telem["payload"]["all_detections"]), 2)

                avg_proc_ms = sum(inference_times) / len(inference_times)
                TestSystemIntegrationE2E.benchmarks["tracking_inference_avg_ms"] = round(avg_proc_ms, 2)

        asyncio.run(run_detection_test())

    # ==========================================================================
    # TEST 4: Target Selection & Autonomous Closed-Loop Pan/Tilt Tracking
    # ==========================================================================
    def test_04_target_selection_and_autonomous_closed_loop_tracking(self):
        """
        Scenario 4: Target selection & autonomous closed-loop pan/tilt tracking.
        Dispatches click-to-track / track.select_id from Web client.
        Simulates closed-loop optical feedback: off-center target produces PID deltas,
        Gateway dispatches cmd.servo.move, ESP32 slews virtual servos, and optical
        error reduces progressively into the inner deadband (+-15 px) within 1.50s.
        """
        async def run_closed_loop_test():
            esp = MockESP32Firmware()
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:

                await ws_cli.recv()  # flush initial snapshot

                # 1. Establish single off-center target at (x=450, y=300) in world coordinates
                target_world_x = 450.0
                target_world_y = 300.0
                pixels_per_deg_x = 640.0 / 60.0  # ~10.67 px/deg
                pixels_per_deg_y = 480.0 / 45.0  # ~10.67 px/deg

                initial_det = PersonDetection(
                    x1=target_world_x - 45.0, y1=target_world_y - 90.0,
                    x2=target_world_x + 45.0, y2=target_world_y + 90.0,
                    confidence=0.94,
                )
                self.detector.set_detections([initial_det])

                # Process 1 frame to initialize ByteTrack track
                dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                res1 = self.pipeline.process_frame(dummy_frame)
                self.assertEqual(len(res1.tracks), 1)
                assigned_id = res1.tracks[0].track_id

                # 2. Client locks onto target via track.target_select and engages auto_track
                sel_cmd = {
                    "type": "track.target_select",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 20,
                    "payload": {"track_id": assigned_id},
                }
                await ws_cli.send(json.dumps(sel_cmd))

                # Respect 20 Hz client command rate limiting
                await asyncio.sleep(0.08)

                mode_cmd = {
                    "type": "track.mode_set",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 21,
                    "payload": {"mode": "auto_track"},
                }
                await ws_cli.send(json.dumps(mode_cmd))

                # Wait for mode broadcast
                await recv_filtered_msg(ws_cli, "track.mode_set", timeout=2.0)
                self.assertEqual(self.pipeline.selector.mode, "auto_track")

                # 3. Live Gateway TrackingWorker detects target & dispatches cmd.servo.move to ws_dev
                dev_cmd = await recv_filtered_msg(ws_dev, "cmd.servo.move", timeout=3.0)
                self.assertEqual(dev_cmd["type"], "cmd.servo.move")
                cmd_payload = dev_cmd["payload"]
                self.assertIn("pan", cmd_payload)
                self.assertIn("tilt", cmd_payload)
                self.assertTrue(15.0 <= cmd_payload["pan"] <= 165.0)
                self.assertTrue(60.0 <= cmd_payload["tilt"] <= 135.0)

                # Simulated ESP32 executes command received over WebSocket
                esp.handle_inbound_message(json.dumps(dev_cmd))
                self.assertEqual(esp.servos.target_pan, cmd_payload["pan"])
                self.assertEqual(esp.servos.target_tilt, cmd_payload["tilt"])

                # Client receives track.frame_target telemetry confirming active tracking
                cli_frame_telem = await recv_filtered_msg(
                    ws_cli,
                    "track.frame_target",
                    timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("active_target") is not None,
                )
                self.assertIsNotNone(cli_frame_telem["payload"].get("active_target"))

                # 4. Simulate Closed-Loop Optical Convergence
                # Control loop runs at 25 Hz (dt=0.04s) up to 1.50 seconds
                dt = 0.04
                sim_time = 0.0
                converged = False
                convergence_time = 0.0
                ctrl = self.pipeline.controller
                initial_error_x = target_world_x - 320.0  # +130 px
                initial_error_y = target_world_y - 240.0  # +60 px

                while sim_time < 2.0:
                    sim_time += dt

                    # Calculate target sensor coordinates from current servo angles
                    pan_delta = ctrl.current_pan - 90.0
                    tilt_delta = ctrl.current_tilt - 90.0
                    sensor_x = target_world_x - (pan_delta * pixels_per_deg_x)
                    sensor_y = target_world_y + (tilt_delta * pixels_per_deg_y)

                    out = ctrl.update((sensor_x, sensor_y), dt=dt)

                    # Actuate simulated servos with commanded angles
                    esp.servos.set_target(out.pan_angle, out.tilt_angle, speed_factor=0.6)
                    esp.servos.update(dt)

                    err_x = sensor_x - 320.0
                    err_y = sensor_y - 240.0

                    # Convergence condition: optical centroid within inner deadband (+-15 px)
                    if abs(err_x) <= 15.0 and abs(err_y) <= 15.0 and not converged:
                        converged = True
                        convergence_time = sim_time
                        break

                self.assertTrue(converged, f"Optical tracking failed to converge within 1.50s (final error: x={err_x:.1f}, y={err_y:.1f})")
                self.assertLess(convergence_time, 1.50)
                TestSystemIntegrationE2E.benchmarks["tracking_convergence_time_s"] = round(convergence_time, 3)

        asyncio.run(run_closed_loop_test())

    # ==========================================================================
    # TEST 5: Sensor Telemetry Ingestion & Proximity Alerts
    # ==========================================================================
    def test_05_sensor_telemetry_ingestion_and_proximity_alerts(self):
        """
        Scenario 5: Sensor telemetry ingestion & proximity alerts.
        Simulates HC-SR04 obstacle < 20 cm triggering proximity obstruction halt and buzzer alarm.
        Simulates HC-SR501 PIR sensor detecting intruder motion.
        Verifies Gateway state aggregation, Web client alert reception, and proximity interlock.
        """
        async def run_sensor_alerts_test():
            esp = MockESP32Firmware()
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:

                await ws_cli.recv()  # flush initial snapshot

                # 1. Simulate HC-SR04 Obstacle at 14.5 cm (< 20.0 cm threshold)
                prox_alert = esp.set_sonar_distance(14.5)
                self.assertTrue(esp.proximity_halt)
                self.assertTrue(esp.buzzer_active)
                self.assertEqual(esp.buzzer_pattern, "alarm")
                self.assertIsNotNone(prox_alert)

                # Send proximity alert event from ESP32 to Gateway
                await ws_dev.send(json.dumps(prox_alert))

                # Send telem.sensors packet with obstacle distance
                telem_sonar = esp.generate_telemetry()
                await ws_dev.send(json.dumps(telem_sonar))

                # 2. Client receives 'proximity_obstruction' critical alert
                cli_alert = await recv_filtered_msg(
                    ws_cli,
                    "alert.event",
                    timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("event_type") == "proximity_obstruction",
                )
                self.assertEqual(cli_alert["payload"]["event_type"], "proximity_obstruction")
                self.assertEqual(cli_alert["payload"]["severity"], "critical")
                self.assertTrue(cli_alert["payload"]["buzzer_activated"])
                self.assertEqual(cli_alert["payload"]["action_taken"], "motion_inhibited")

                # Client receives telem.sensors confirming < 20 cm distance
                cli_telem = await recv_filtered_msg(
                    ws_cli,
                    "telem.sensors",
                    timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("sonar", {}).get("distance_cm") == 14.5,
                )
                self.assertEqual(cli_telem["payload"]["sonar"]["distance_cm"], 14.5)
                self.assertTrue(cli_telem["payload"]["buzzer"]["active"])

                # 3. Verify Hardware Proximity Interlock on ESP32:
                # Inbound move command from client via Gateway must be inhibited while obstacle < 20 cm
                esp.servos.current_pan = 90.0
                esp.servos.current_tilt = 90.0
                cmd_move_req = {
                    "type": "cmd.servo.move",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 50,
                    "payload": {"mode": "absolute", "pan": 115.0, "tilt": 80.0, "speed": 0.5, "smooth": True},
                }
                await ws_cli.send(json.dumps(cmd_move_req))
                dev_move = await recv_filtered_msg(ws_dev, "cmd.servo.move", timeout=2.5)
                esp.handle_inbound_message(json.dumps(dev_move))
                # Servos must remain frozen at neutral, not moving toward target
                self.assertEqual(esp.servos.current_pan, 90.0)
                self.assertEqual(esp.servos.current_tilt, 90.0)
                self.assertFalse(esp.servos.is_moving)

                # 4. Simulate PIR Motion Alarm
                pir_alert = esp.set_pir_state(True)
                self.assertIsNotNone(pir_alert)
                await ws_dev.send(json.dumps(pir_alert))

                # Client receives 'motion_alarm' alert
                cli_pir_alert = await recv_filtered_msg(
                    ws_cli, "alert.event", timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("event_type") == "motion_alarm",
                )
                self.assertEqual(cli_pir_alert["payload"]["event_type"], "motion_alarm")
                self.assertEqual(cli_pir_alert["payload"]["severity"], "warning")

                # 5. Clear Obstacle (> 25 cm hysteresis clearance)
                esp.set_sonar_distance(55.0)
                self.assertFalse(esp.proximity_halt)
                self.assertFalse(esp.buzzer_active)
                await ws_dev.send(json.dumps(esp.generate_telemetry()))

                cli_cleared = await recv_filtered_msg(
                    ws_cli,
                    "telem.sensors",
                    timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("sonar", {}).get("distance_cm") == 55.0,
                )
                self.assertEqual(cli_cleared["payload"]["sonar"]["distance_cm"], 55.0)
                self.assertFalse(cli_cleared["payload"]["buzzer"]["active"])

        asyncio.run(run_sensor_alerts_test())

    # ==========================================================================
    # TEST 6: Network Disconnection, Watchdog Trip & Safe-Stop Failsafe
    # ==========================================================================
    def test_06_network_disconnection_watchdog_and_safe_stop_failsafe(self):
        """
        Scenario 6: Network disconnection, 800 ms hardware watchdog trip, and safe-stop failsafe.
        Abruptly severs ESP32 WebSocket connection.
        Verifies Mock ESP32 triggers hardware watchdog after 800 ms silence,
        freezes virtual servos, activates warning buzzer, and flags failsafe_active=True.
        Verifies Gateway marks esp32_connected=False and broadcasts critical ws_disconnect alert.
        """
        async def run_disconnect_watchdog_test():
            esp = MockESP32Firmware()
            async with websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                await ws_cli.recv()  # flush initial snapshot

                # Connect ESP32
                ws_dev = await websockets.connect(self.WS_DEVICE_URL)
                await recv_filtered_msg(
                    ws_cli, "alert.event", timeout=2.5,
                    pred=lambda d: d.get("payload", {}).get("event_type") == "device_connected",
                )

                # Simulate device moving when link drops
                esp.servos.set_target(130.0, 110.0, speed_factor=0.5)
                esp.servos.update(0.04)
                self.assertTrue(esp.servos.is_moving)

                # Sever link mid-motion
                t_sever = time.time()
                await ws_dev.close()

                # 1. Gateway catches disconnect and broadcasts critical failsafe alert to client
                disc_alert = await recv_filtered_msg(
                    ws_cli, "alert.event", timeout=3.0,
                    pred=lambda d: d.get("payload", {}).get("event_type") == "ws_disconnect",
                )
                self.assertEqual(disc_alert["payload"]["event_type"], "ws_disconnect")
                self.assertEqual(disc_alert["payload"]["severity"], "critical")
                self.assertEqual(disc_alert["payload"]["action_taken"], "failsafe_engaged")

                # Verify Gateway REST status reports failsafe_active=True and connected=False
                st_resp = requests.get(f"{self.BASE_URL}/api/v1/system/status")
                self.assertEqual(st_resp.status_code, 200)
                st = st_resp.json()
                self.assertFalse(st["esp32"]["connected"])
                self.assertTrue(st["esp32"]["failsafe_active"])

                # 2. Mock ESP32 Hardware Watchdog Verification
                # Assert watchdog has NOT tripped before 800ms
                esp.last_rx_timestamp = time.time()
                self.assertFalse(esp.check_watchdog(), "Watchdog triggered prematurely before 800ms timeout")

                # Sleep past 800ms watchdog threshold (0.85s total)
                elapsed_since_sever = time.time() - t_sever
                if elapsed_since_sever < 0.85:
                    await asyncio.sleep(0.85 - elapsed_since_sever)

                triggered = esp.check_watchdog()
                self.assertTrue(triggered)
                self.assertTrue(esp.failsafe_active)
                self.assertFalse(esp.servos.is_moving)
                self.assertTrue(esp.buzzer_active)

                # Telemetry packet flags failsafe_active in system payload
                telem_fs = esp.generate_telemetry()
                self.assertTrue(telem_fs["payload"]["system"]["failsafe_active"])

                # 3. Reject movement command via REST under failsafe
                r_rej = requests.post(
                    f"{self.BASE_URL}/api/v1/camera/control",
                    json={"action": "move", "pan": 90.0, "tilt": 90.0},
                )
                self.assertEqual(r_rej.status_code, 400)
                self.assertIn("Cannot control camera servos while", r_rej.json()["detail"])

                # 4. Reject movement command via WebSocket under failsafe
                cmd_ws_rej = {
                    "type": "cmd.servo.move",
                    "timestamp": int(time.time() * 1000),
                    "sender": "frontend",
                    "seq": 99,
                    "corr_id": "corr_rej_06",
                    "payload": {"mode": "absolute", "pan": 90.0, "tilt": 90.0},
                }
                await ws_cli.send(json.dumps(cmd_ws_rej))
                cli_err = await recv_filtered_msg(
                    ws_cli, "alert.event", timeout=2.5,
                    pred=lambda d: "Cannot move servos" in d.get("payload", {}).get("message", "")
                )
                self.assertIn("Failsafe is active", cli_err["payload"]["message"])

        asyncio.run(run_disconnect_watchdog_test())

    # ==========================================================================
    # TEST 7: Automatic Recovery and Re-Centering upon Connection Restoration
    # ==========================================================================
    def test_07_automatic_recovery_and_recentering(self):
        """
        Scenario 7: Automatic recovery and re-centering upon connection restoration.
        Re-establishes /ws/device connection.
        Verifies Gateway clears failsafe_active, broadcasts device_connected,
        routes cmd.servo.center, and ESP32 returns to calibrated home (90.0°, 90.0°).
        """
        async def run_recovery_test():
            esp = MockESP32Firmware()
            # Start ESP32 in failsafe state
            esp.failsafe_active = True
            esp.buzzer_active = True
            esp.servos.current_pan = 135.0
            esp.servos.current_tilt = 115.0

            async with websockets.connect(self.WS_CLIENT_URL) as ws_cli:
                await ws_cli.recv()  # flush initial snapshot

                # 1. Re-establish ESP32 connection
                async with websockets.connect(self.WS_DEVICE_URL) as ws_dev:
                    # Gateway registers reconnection and notifies operators
                    conn_alert = await recv_filtered_msg(
                        ws_cli,
                        "alert.event",
                        timeout=2.5,
                        pred=lambda d: d.get("payload", {}).get("event_type") == "device_connected",
                    )
                    self.assertEqual(conn_alert["payload"]["event_type"], "device_connected")

                    # Gateway state reflects esp32_connected=True and failsafe_active=False
                    st = requests.get(f"{self.BASE_URL}/api/v1/system/status").json()
                    self.assertTrue(st["esp32"]["connected"])
                    self.assertFalse(st["esp32"]["failsafe_active"])

                    # 2. Client sends cmd.servo.center
                    center_cmd = {
                        "type": "cmd.servo.center",
                        "timestamp": int(time.time() * 1000),
                        "sender": "frontend",
                        "seq": 30,
                        "corr_id": "corr_center_07",
                        "payload": {"speed": 0.5},
                    }
                    await ws_cli.send(json.dumps(center_cmd))

                    # Device receives cmd.servo.center
                    dev_center = await recv_filtered_msg(ws_dev, "cmd.servo.center", timeout=2.5)
                    self.assertEqual(dev_center["type"], "cmd.servo.center")

                    # 3. ESP32 clears failsafe, disarms buzzer, and slews to (90°, 90°)
                    esp.handle_inbound_message(json.dumps(dev_center))
                    self.assertFalse(esp.failsafe_active)
                    self.assertFalse(esp.buzzer_active)
                    self.assertEqual(esp.servos.target_pan, 90.0)
                    self.assertEqual(esp.servos.target_tilt, 90.0)

                    # Simulate slew to completion
                    for _ in range(50):
                        esp.servos.update(0.02)

                    self.assertAlmostEqual(esp.servos.current_pan, 90.0, places=1)
                    self.assertAlmostEqual(esp.servos.current_tilt, 90.0, places=1)
                    self.assertFalse(esp.servos.is_moving)

                    # Device sends telem.sensors confirming neutral centering
                    telem_centered = esp.generate_telemetry()
                    await ws_dev.send(json.dumps(telem_centered))

                    cli_telem = await recv_filtered_msg(ws_cli, "telem.sensors", timeout=2.5)
                    self.assertAlmostEqual(cli_telem["payload"]["servos"]["pan_angle"], 90.0, delta=0.5)
                    self.assertAlmostEqual(cli_telem["payload"]["servos"]["tilt_angle"], 90.0, delta=0.5)
                    self.assertFalse(cli_telem["payload"]["system"]["failsafe_active"])

        asyncio.run(run_recovery_test())

    # ==========================================================================
    # TEST 8: Long-Running Stress Test (Memory, Tasks, Queue Stability)
    # ==========================================================================
    def test_08_long_running_stress_and_queue_stability(self):
        """
        Scenario 8: Long-running stress test.
        Executes 60 consecutive closed-loop iterations under continuous load:
        - Synthetic frame generation & TrackingPipeline execution
        - 10 Hz ESP32 sensor telemetry streaming over WebSocket
        - Web client telemetry reception & 20 Hz rate limiter stress verification
        - Asserts 0 crashes, memory stability, no task leaks, and computes latency metrics.
        """
        async def run_stress_test():
            esp = MockESP32Firmware()
            async with websockets.connect(self.WS_DEVICE_URL) as ws_dev, \
                       websockets.connect(self.WS_CLIENT_URL) as ws_cli:

                await ws_cli.recv()  # flush initial snapshot

                iterations = 60
                frame_w, frame_h = 640, 480
                cycle_latencies: List[float] = []
                frame_data = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)

                # Pre-test memory baseline check
                try:
                    import psutil
                    proc = psutil.Process()
                    rss_before = proc.memory_info().rss
                except ImportError:
                    proc = None
                    rss_before = 0

                active_tasks_before = len(asyncio.all_tasks())

                for i in range(iterations):
                    t_iter_start = time.perf_counter()

                    # 1. Pipeline execution with moving target
                    cx = 320.0 + 80.0 * math.sin(i * 0.15)
                    cy = 240.0 + 50.0 * math.cos(i * 0.15)
                    det = PersonDetection(x1=cx - 40, y1=cy - 80, x2=cx + 40, y2=cy + 80, confidence=0.91)
                    self.detector.set_detections([det])

                    res = self.pipeline.process_frame(frame_data)
                    self.assertEqual(len(res.tracks), 1)

                    # 2. ESP32 telemetry transmission
                    esp.update_sensors(0.04)
                    esp.servos.update(0.04)
                    telem = esp.generate_telemetry()
                    await ws_dev.send(json.dumps(telem))

                    # 3. Client receives forwarded telemetry
                    recvd = await recv_filtered_msg(ws_cli, "telem.sensors", timeout=1.5)
                    self.assertEqual(recvd["type"], "telem.sensors")

                    # 4. Stress Rate Limiter: Send 3 back-to-back jog commands within 10ms
                    # The 20 Hz rate limiter should drop bursts cleanly without throwing exceptions
                    for j in range(3):
                        rapid_jog = {
                            "type": "cmd.jog",
                            "timestamp": int(time.time() * 1000),
                            "sender": "frontend",
                            "seq": 1000 + (i * 10) + j,
                            "payload": {"delta_pan": 1.0, "delta_tilt": 0.0, "speed": 0.5},
                        }
                        await ws_cli.send(json.dumps(rapid_jog))

                    # Drain any command forwarded to device queue to avoid buffer bloat
                    try:
                        while True:
                            dev_msg_raw = await asyncio.wait_for(ws_dev.recv(), timeout=0.01)
                            esp.handle_inbound_message(dev_msg_raw)
                    except asyncio.TimeoutError:
                        pass

                    cycle_latencies.append((time.perf_counter() - t_iter_start) * 1000.0)

                # Post-test assertions
                self.assertEqual(len(cycle_latencies), iterations)
                avg_cycle_ms = sum(cycle_latencies) / len(cycle_latencies)
                max_cycle_ms = max(cycle_latencies)
                min_cycle_ms = min(cycle_latencies)

                TestSystemIntegrationE2E.benchmarks["stress_avg_cycle_ms"] = round(avg_cycle_ms, 2)
                TestSystemIntegrationE2E.benchmarks["stress_max_cycle_ms"] = round(max_cycle_ms, 2)
                TestSystemIntegrationE2E.benchmarks["stress_min_cycle_ms"] = round(min_cycle_ms, 2)
                TestSystemIntegrationE2E.benchmarks["stress_total_iterations"] = iterations

                # Check task leakage
                active_tasks_after = len(asyncio.all_tasks())
                self.assertLessEqual(
                    active_tasks_after - active_tasks_before, 3,
                    f"Possible async task leak: before={active_tasks_before}, after={active_tasks_after}"
                )

                # Check memory stability
                if proc is not None:
                    rss_after = proc.memory_info().rss
                    delta_mb = (rss_after - rss_before) / (1024 * 1024)
                    TestSystemIntegrationE2E.benchmarks["stress_rss_delta_mb"] = round(delta_mb, 2)
                    # Assert no runaway memory growth (> 35 MB over 60 cycles)
                    self.assertLess(delta_mb, 35.0, f"Excessive memory growth during stress test: {delta_mb:.2f} MB")

        asyncio.run(run_stress_test())


if __name__ == "__main__":
    unittest.main()
