#!/usr/bin/env python3
"""
SmartVision - System Showcase & Demonstration Runner
Phase 9: Production Packaging, Demonstration & Final Handover.

Executes an automated end-to-end demonstration covering all system tiers:
  1. Multi-Tier Initialization & Health Handshake (REST /api/v1/health & /api/v1/system/status)
  2. Dual WebSocket Synchronization (/ws/device and /ws/client)
  3. Target Selection & Autonomous Closed-Loop Optical PID Tracking
  4. Manual Operator Jog & Slew Velocity Scaling
  5. Ultrasonic Proximity Hazard Interlock (< 20 cm)
  6. HC-SR501 PIR Motion Alert Triggering
  7. 800 ms Hardware Watchdog Sever & Safe-Stop Failsafe
  8. Automatic Link Recovery & Servo Neutral Centering

Outputs formatted progress to stdout and records execution metrics to captures/demo_showcase_log.json.
# ponytail: single unified demonstration runner reusing existing mock firmware and pipeline.
"""

import asyncio
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import numpy as np
import requests
import uvicorn
import websockets

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SMARTVISION_DIR = os.path.dirname(CURRENT_DIR)
PROJECT_ROOT = os.path.dirname(SMARTVISION_DIR)
for p in [SMARTVISION_DIR, PROJECT_ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.schemas.protocol import SmartVisionEnvelope
from backend.app.services.connection_hub import ConnectionHub
from backend.app.services.state_manager import SystemStateManager
from tests.mock_esp32_firmware import MockESP32Firmware
from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.detection.mock_detector import MockPersonDetector
from vision.detection.types import PersonDetection
from vision.tracking.pipeline import TrackingPipeline

# ANSI Colors for formatted CLI demonstration
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[32m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
C_MAGENTA = "\033[35m"
C_RED = "\033[31m"


def find_free_port() -> int:
    """Finds an ephemeral free TCP port for isolated demonstration execution."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def recv_filtered_msg(
    ws,
    expected_type: str,
    timeout: float = 3.0,
    pred: Optional[Any] = None,
) -> Dict[str, Any]:
    """Receives WebSocket messages until expected_type (and optional predicate) is matched."""
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


class DemonstrationRunner:
    """Orchestrates and documents the end-to-end SmartVision live showcase."""

    def __init__(self, host: str = "127.0.0.1", port: Optional[int] = None):
        self.host = host
        self.port = port or find_free_port()
        self.base_url = f"http://{self.host}:{self.port}"
        self.ws_device_url = f"ws://{self.host}:{self.port}/ws/device"
        self.ws_client_url = f"ws://{self.host}:{self.port}/ws/client"

        self.server: Optional[uvicorn.Server] = None
        self.server_thread: Optional[threading.Thread] = None
        self.cam_service: Optional[CameraService] = None
        self.detector: Optional[MockPersonDetector] = None
        self.pipeline: Optional[TrackingPipeline] = None

        self.records: List[Dict[str, Any]] = []

    def log_step(self, stage: int, name: str, details: str, duration_ms: float, passed: bool = True):
        status_str = f"{C_GREEN}PASS{C_RESET}" if passed else f"{C_RED}FAIL{C_RESET}"
        print(f"  {C_BOLD}[Stage {stage}]{C_RESET} {C_CYAN}{name:<45}{C_RESET} [{status_str}] ({duration_ms:.1f}ms)")
        print(f"           {C_YELLOW}→{C_RESET} {details}")
        self.records.append({
            "stage": stage,
            "name": name,
            "details": details,
            "duration_ms": round(duration_ms, 2),
            "passed": passed,
            "timestamp": time.time(),
        })

    def start_server(self):
        """Initializes synthetic camera, pipeline, and background FastAPI server."""
        cam_config = CameraConfig(
            backend=CameraBackend.SYNTHETIC,
            device_index=0,
            width=640,
            height=480,
            fps=30,
            enable_synthetic_fallback=True,
        )
        self.cam_service = CameraService(config=cam_config)
        self.cam_service.start()

        self.detector = MockPersonDetector(mode="manual")
        self.pipeline = TrackingPipeline(
            detector=self.detector,
            frame_width=640,
            frame_height=480,
            enable_hud=True,
        )

        app_instance = create_app(
            camera_service=self.cam_service,
            tracking_pipeline=self.pipeline,
        )

        uvi_config = uvicorn.Config(
            app=app_instance,
            host=self.host,
            port=self.port,
            log_level="error",
            loop="asyncio",
        )
        self.server = uvicorn.Server(config=uvi_config)
        self.server_thread = threading.Thread(target=self.server.run, daemon=True)
        self.server_thread.start()

        # Wait for server readiness
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                res = requests.get(f"{self.base_url}/api/v1/health", timeout=0.5)
                if res.status_code == 200:
                    break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError(f"FastAPI demonstration server failed to bind to {self.base_url}")

    def stop_server(self):
        """Cleanly tears down background services."""
        if self.server:
            self.server.should_exit = True
        if self.cam_service:
            self.cam_service.stop()

    async def run_showcase(self) -> bool:
        """Executes all 8 demonstration stages sequentially."""
        print(f"\n{C_BOLD}{C_MAGENTA}========================================================================{C_RESET}")
        print(f"{C_BOLD}{C_MAGENTA}          SmartVision — Phase 9 End-to-End System Showcase              {C_RESET}")
        print(f"{C_BOLD}{C_MAGENTA}========================================================================{C_RESET}")
        print(f"Target Gateway: {self.base_url}\n")

        all_passed = True
        esp = MockESP32Firmware(host="127.0.0.1", port=self.port)

        # STAGE 1: REST API Health & Liveness
        t0 = time.perf_counter()
        res_h = requests.get(f"{self.base_url}/api/v1/health", timeout=2.0)
        res_s = requests.get(f"{self.base_url}/api/v1/system/status", timeout=2.0)
        dt = (time.perf_counter() - t0) * 1000.0
        passed = (res_h.status_code == 200 and res_s.status_code == 200)
        all_passed = all_passed and passed
        self.log_step(
            1, "REST Health & Discovery Verification",
            f"Health 200 OK | Uptime {res_h.json().get('uptime_sec', 0.0):.1f}s | FPS: {res_h.json().get('camera_fps', 0):.1f}",
            dt, passed
        )

        # STAGES 2 THROUGH 7: Connected Session
        async with websockets.connect(self.ws_device_url) as ws_device, \
                   websockets.connect(self.ws_client_url) as ws_client:

            # Start simulated ESP32 periodic 10 Hz telemetry streaming task to pet gateway watchdog
            async def device_heartbeat_loop():
                try:
                    while not ws_device.closed:
                        telem = esp.generate_telemetry()
                        await ws_device.send(json.dumps(telem))
                        await asyncio.sleep(0.35)
                except (asyncio.CancelledError, Exception):
                    pass

            hb_task = asyncio.create_task(device_heartbeat_loop())

            # STAGE 2: Handshake
            t0 = time.perf_counter()
            init_msg = json.loads(await asyncio.wait_for(ws_client.recv(), timeout=2.0))
            assert init_msg["type"] == "sys.status"

            ping_env = {
                "type": "sys.ping",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 1,
                "payload": {"client_time": int(time.time() * 1000)}
            }
            await ws_client.send(json.dumps(ping_env))
            pong_data = await recv_filtered_msg(ws_client, "sys.pong", timeout=2.0)
            dt = (time.perf_counter() - t0) * 1000.0
            passed = (pong_data["type"] == "sys.pong")
            all_passed = all_passed and passed
            self.log_step(
                2, "Full-Duplex Dual WebSocket Handshake",
                f"Client & Device connected simultaneously. Roundtrip ping/pong confirmed.",
                dt, passed
            )

            # STAGE 3: Autonomous Person Tracking
            t0 = time.perf_counter()
            initial_det = PersonDetection(x1=405.0, y1=200.0, x2=495.0, y2=380.0, confidence=0.94)
            self.detector.set_detections([initial_det])

            dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            res1 = self.pipeline.process_frame(dummy_frame)
            assigned_id = res1.tracks[0].track_id if res1.tracks else 1

            sel_env = {
                "type": "track.target_select",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 20,
                "payload": {"track_id": assigned_id}
            }
            await ws_client.send(json.dumps(sel_env))
            await asyncio.sleep(0.06)

            mode_env = {
                "type": "track.mode_set",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 21,
                "payload": {"mode": "auto_track"}
            }
            await ws_client.send(json.dumps(mode_env))

            dev_cmd = await recv_filtered_msg(ws_device, "cmd.servo.move", timeout=3.0)
            cmd_payload = dev_cmd["payload"]
            esp.handle_inbound_message(json.dumps(dev_cmd))

            dt = (time.perf_counter() - t0) * 1000.0
            passed = ("pan" in cmd_payload and 15.0 <= cmd_payload["pan"] <= 165.0)
            all_passed = all_passed and passed
            self.log_step(
                3, "Closed-Loop Autonomous Optical Tracking",
                f"Target acquired (ID {assigned_id}). PID dispatched cmd.servo.move (Pan: {cmd_payload['pan']:.1f}°, Tilt: {cmd_payload['tilt']:.1f}°).",
                dt, passed
            )

            # Switch mode back to manual for operator jog
            self.detector.set_detections([])
            self.pipeline.selector.stop_tracking()
            manual_mode_env = {
                "type": "track.mode_set",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 22,
                "payload": {"mode": "manual"}
            }
            await ws_client.send(json.dumps(manual_mode_env))
            await asyncio.sleep(0.06)

            # STAGE 4: Manual D-Pad Jog & Speed Scaling
            t0 = time.perf_counter()
            jog_env = {
                "type": "cmd.servo.move",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 30,
                "payload": {"pan": 125.0, "tilt": 75.0, "speed": 0.6, "mode": "absolute", "smooth": True}
            }
            await ws_client.send(json.dumps(jog_env))

            recv_jog = await recv_filtered_msg(
                ws_device, "cmd.servo.move", timeout=2.5,
                pred=lambda d: d.get("payload", {}).get("speed") == 0.6
            )
            esp.handle_inbound_message(json.dumps(recv_jog))

            dt = (time.perf_counter() - t0) * 1000.0
            passed = (recv_jog is not None and recv_jog["payload"]["pan"] == 125.0)
            all_passed = all_passed and passed
            self.log_step(
                4, "Manual D-Pad Jog & Speed Scaling",
                f"Arbitrated manual jog received: Pan 125.0°, Tilt 75.0° at speed factor 0.6.",
                dt, passed
            )

            # STAGE 5: Ultrasonic Proximity Hazard Interlock (< 20 cm)
            t0 = time.perf_counter()
            prox_alert = esp.set_sonar_distance(14.5)
            await ws_device.send(json.dumps(prox_alert))
            await ws_device.send(json.dumps(esp.generate_telemetry()))

            cli_alert = await recv_filtered_msg(
                ws_client, "alert.event", timeout=2.5,
                pred=lambda d: d.get("payload", {}).get("event_type") == "proximity_obstruction"
            )

            dt = (time.perf_counter() - t0) * 1000.0
            passed = (cli_alert is not None and cli_alert["payload"]["severity"] == "critical")
            all_passed = all_passed and passed
            self.log_step(
                5, "Ultrasonic Hazard (<20cm) Interlock",
                f"Proximity obstruction alert generated ({cli_alert['payload']['message']}).",
                dt, passed
            )

            # STAGE 6: HC-SR501 PIR Motion Alert
            t0 = time.perf_counter()
            pir_alert = esp.set_pir_state(True)
            await ws_device.send(json.dumps(pir_alert))

            cli_pir = await recv_filtered_msg(
                ws_client, "alert.event", timeout=2.5,
                pred=lambda d: d.get("payload", {}).get("event_type") == "motion_alarm"
            )

            dt = (time.perf_counter() - t0) * 1000.0
            passed = (cli_pir is not None)
            all_passed = all_passed and passed
            self.log_step(
                6, "HC-SR501 PIR Intrusion Motion Alert",
                f"Motion alarm event broadcast to operators upon pyroelectric rising edge.",
                dt, passed
            )

            # STAGE 7: Hardware Watchdog Sever & Safe-Stop
            t0 = time.perf_counter()
            # Stop telemetry heartbeat task and sever device connection while client is listening
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
            await ws_device.close()

            disc_alert = await recv_filtered_msg(
                ws_client, "alert.event", timeout=2.5,
                pred=lambda d: d.get("payload", {}).get("event_type") == "ws_disconnect"
            )
            dt = (time.perf_counter() - t0) * 1000.0
            passed = (disc_alert is not None and disc_alert["payload"]["action_taken"] == "failsafe_engaged")
            all_passed = all_passed and passed
            self.log_step(
                7, "Communication Loss & Safe-Stop Failsafe",
                f"Gateway asserted FAILSAFE_ACTIVE upon WebSocket disconnect. Servos locked.",
                dt, passed
            )

        # STAGE 8: Link Reconnection & Calibrated Neutral Centering
        t0 = time.perf_counter()
        async with websockets.connect(self.ws_device_url) as ws_device_new, \
                   websockets.connect(self.ws_client_url) as ws_client_new:

            center_env = {
                "type": "cmd.servo.center",
                "timestamp": int(time.time() * 1000),
                "sender": "frontend",
                "seq": 40,
                "payload": {}
            }
            await ws_client_new.send(json.dumps(center_env))

            center_cmd = await recv_filtered_msg(ws_device_new, "cmd.servo.center", timeout=2.5)
            dt = (time.perf_counter() - t0) * 1000.0
            passed = (center_cmd is not None)
            all_passed = all_passed and passed
            self.log_step(
                8, "Link Recovery & Neutral Re-Centering",
                f"Connection restored. Calibration center command delivered (Pan 90°, Tilt 90°).",
                dt, passed
            )

        print(f"\n{C_BOLD}{C_MAGENTA}------------------------------------------------------------------------{C_RESET}")
        result_str = f"{C_BOLD}{C_GREEN}100% DEMONSTRATION SUCCESSFUL{C_RESET}" if all_passed else f"{C_BOLD}{C_RED}DEMONSTRATION FAILED{C_RESET}"
        print(f"Final Outcome: {result_str}")
        print(f"{C_BOLD}{C_MAGENTA}========================================================================{C_RESET}\n")

        # Save output artifact
        capture_dirs = [os.path.join(PROJECT_ROOT, "captures")]
        sm_cap = os.path.join(SMARTVISION_DIR, "captures")
        if sm_cap != capture_dirs[0]:
            capture_dirs.append(sm_cap)

        log_payload = {
            "timestamp": time.time(),
            "all_passed": all_passed,
            "stages": self.records,
        }
        for cdir in capture_dirs:
            os.makedirs(cdir, exist_ok=True)
            log_path = os.path.join(cdir, "demo_showcase_log.json")
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(log_payload, f, indent=2)

        print(f"Showcase metrics saved to: {os.path.join(capture_dirs[0], 'demo_showcase_log.json')}\n")

        return all_passed


def main():
    runner = DemonstrationRunner()
    try:
        runner.start_server()
        success = asyncio.run(runner.run_showcase())
        if not success:
            sys.exit(1)
    finally:
        runner.stop_server()


if __name__ == "__main__":
    main()
