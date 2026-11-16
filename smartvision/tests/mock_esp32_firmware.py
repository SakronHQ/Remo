"""
SmartVision - Mock ESP32-S3 Firmware Client
Emulates the embedded ESP32-S3 microcontroller running FreeRTOS:
- Virtual PCA9685 servo angle simulation with 50 Hz slew rate inertia
- Mechanical travel limit clamping (Pan: [15°, 165°], Tilt: [60°, 135°])
- Simulated HC-SR04 ultrasonic distance and HC-SR501 PIR telemetry (10 Hz)
- 800ms communication watchdog failsafe and emergency stop logic
Supports standalone test mode or live WebSocket connection to FastAPI backend.
"""

import argparse
import asyncio
import json
import math
import sys
import time
from typing import Any, Dict, Optional


class VirtualPCA9685Servos:
    """Simulates physical servos with mechanical limits and slew inertia."""

    PAN_MIN = 15.0
    PAN_MAX = 165.0
    PAN_HOME = 90.0

    TILT_MIN = 60.0
    TILT_MAX = 135.0
    TILT_HOME = 90.0

    DEFAULT_SLEW_RATE = 60.0  # degrees per second

    def __init__(self):
        self.current_pan = self.PAN_HOME
        self.current_tilt = self.TILT_HOME
        self.target_pan = self.PAN_HOME
        self.target_tilt = self.TILT_HOME
        self.slew_rate = self.DEFAULT_SLEW_RATE
        self.is_moving = False
        self.last_update = time.time()

    def set_target(self, pan: float, tilt: float, speed_factor: float = 0.5):
        # Enforce two-tier mechanical clamping
        self.target_pan = max(self.PAN_MIN, min(self.PAN_MAX, float(pan)))
        self.target_tilt = max(self.TILT_MIN, min(self.TILT_MAX, float(tilt)))
        # Map speed factor (0.1 - 1.0) to angular velocity (10 - 120 deg/s)
        self.slew_rate = 10.0 + (float(speed_factor) * 110.0)

    def center(self):
        self.set_target(self.PAN_HOME, self.TILT_HOME, 0.4)

    def freeze(self):
        self.target_pan = self.current_pan
        self.target_tilt = self.current_tilt
        self.is_moving = False

    def update(self, dt: float):
        """Discrete-time slew interpolation executed at 50 Hz."""
        max_step = self.slew_rate * dt

        # Update Pan
        diff_pan = self.target_pan - self.current_pan
        if abs(diff_pan) > 0.05:
            step_pan = math.copysign(min(abs(diff_pan), max_step), diff_pan)
            self.current_pan += step_pan
        else:
            self.current_pan = self.target_pan

        # Update Tilt
        diff_tilt = self.target_tilt - self.current_tilt
        if abs(diff_tilt) > 0.05:
            step_tilt = math.copysign(min(abs(diff_tilt), max_step), diff_tilt)
            self.current_tilt += step_tilt
        else:
            self.current_tilt = self.target_tilt

        self.is_moving = (abs(self.target_pan - self.current_pan) > 0.05) or (
            abs(self.target_tilt - self.current_tilt) > 0.05
        )


class MockESP32Firmware:
    """Emulates ESP32-S3 logic, sensor loops, watchdog, and protocol framing."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        self.url = f"ws://{host}:{port}/ws/device"
        self.servos = VirtualPCA9685Servos()

        self.seq_num = 0
        self.last_rx_timestamp = time.time()
        self.watchdog_timeout_s = 0.8  # 800ms
        self.failsafe_active = False
        self.estop_active = False

        # Virtual sensors state
        self.sim_time = 0.0
        self.sonar_distance = 65.0
        self.pir_state = False
        self.buzzer_active = False
        self.buzzer_pattern = "off"
        self.proximity_halt = False
        self.manual_sensors = False
        self.start_time = time.time()

    def set_sonar_distance(self, dist_cm: float) -> Optional[Dict[str, Any]]:
        """Sets simulated ultrasonic distance and evaluates proximity interlock (< 20 cm)."""
        self.manual_sensors = True
        self.sonar_distance = dist_cm
        if 0.0 < dist_cm < 20.0:
            self.proximity_halt = True
            self.buzzer_active = True
            self.buzzer_pattern = "alarm"
            self.servos.freeze()
            return self.generate_proximity_alert(dist_cm)
        elif dist_cm >= 25.0:
            self.proximity_halt = False
            if self.buzzer_pattern == "alarm":
                self.buzzer_active = False
                self.buzzer_pattern = "off"
        return None

    def set_pir_state(self, state: bool) -> Optional[Dict[str, Any]]:
        """Sets simulated PIR motion state and triggers alarm alert when motion detected."""
        self.manual_sensors = True
        self.pir_state = state
        if state:
            return self.generate_pir_alert()
        return None

    def generate_proximity_alert(self, dist_cm: Optional[float] = None) -> Dict[str, Any]:
        """Generates standard alert.event for proximity obstruction."""
        d = dist_cm if dist_cm is not None else self.sonar_distance
        return {
            "type": "alert.event",
            "timestamp": int(time.time() * 1000),
            "sender": "esp32",
            "seq": self.next_seq(),
            "corr_id": None,
            "payload": {
                "event_id": f"evt_prox_{int(time.time()*1000)}",
                "event_type": "proximity_obstruction",
                "severity": "critical",
                "source": "esp32",
                "message": f"Obstacle detected {d:.1f} cm from camera (Threshold: 20.0 cm). Servo motion inhibited.",
                "telemetry_snapshot": {
                    "distance_cm": d,
                    "threshold_cm": 20.0,
                    "pan_angle": round(self.servos.current_pan, 1),
                    "tilt_angle": round(self.servos.current_tilt, 1),
                },
                "action_taken": "motion_inhibited",
                "buzzer_activated": True,
            },
        }

    def generate_pir_alert(self) -> Dict[str, Any]:
        """Generates standard alert.event for PIR motion alarm."""
        return {
            "type": "alert.event",
            "timestamp": int(time.time() * 1000),
            "sender": "esp32",
            "seq": self.next_seq(),
            "corr_id": None,
            "payload": {
                "event_id": f"evt_pir_{int(time.time()*1000)}",
                "event_type": "motion_alarm",
                "severity": "warning",
                "source": "esp32",
                "message": "PIR motion detected in armed sector",
                "action_taken": "wake_tracking",
            },
        }

    def update_sensors(self, dt: float):
        self.sim_time += dt
        if not self.manual_sensors:
            # Smoothly oscillating distance between 15cm and 120cm
            self.sonar_distance = 67.5 + 52.5 * math.sin(2.0 * math.pi * 0.1 * self.sim_time)
            # Periodic PIR trigger every 8 seconds for 2 seconds
            self.pir_state = (self.sim_time % 8.0) < 2.0

    def check_watchdog(self) -> bool:
        """Returns True if watchdog triggered safe-stop."""
        elapsed = time.time() - self.last_rx_timestamp
        if elapsed > self.watchdog_timeout_s and not self.failsafe_active:
            self.failsafe_active = True
            self.servos.freeze()
            self.buzzer_active = True
            self.buzzer_pattern = "chirp"
            return True
        return False

    def handle_inbound_message(self, msg_str: str) -> Optional[Dict[str, Any]]:
        """Parses inbound JSON envelope and executes command."""
        try:
            msg = json.loads(msg_str)
            if not isinstance(msg, dict):
                return None
        except Exception as e:
            print(f"[ESP32] Error decoding JSON: {e}", file=sys.stderr)
            return None

        msg_type = msg.get("type", "")
        payload = msg.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        corr_id = msg.get("corr_id")

        recognized_commands = (
            "cmd.servo.move", "cmd.move",
            "cmd.jog",
            "cmd.servo.center", "cmd.center",
            "sys.ping", "ping",
            "cmd.buzzer",
            "sys.safestop", "cmd.estop"
        )
        if msg_type not in recognized_commands:
            return None

        # Only pet watchdog upon receiving a valid recognized message
        self.last_rx_timestamp = time.time()
        if self.failsafe_active and msg_type in (
            "cmd.servo.move", "cmd.move", "cmd.jog", "cmd.servo.center", "cmd.center", "sys.ping", "ping", "cmd.buzzer"
        ):
            self.failsafe_active = False
            self.buzzer_active = False
            self.buzzer_pattern = "off"

        if msg_type in ("cmd.servo.move", "cmd.move"):
            if self.proximity_halt:
                self.servos.freeze()
                return None
            mode = payload.get("mode", "absolute")
            if mode == "absolute":
                pan = payload.get("pan", self.servos.current_pan)
                tilt = payload.get("tilt", self.servos.current_tilt)
            else:
                pan = self.servos.current_pan + payload.get("pan", 0.0)
                tilt = self.servos.current_tilt + payload.get("tilt", 0.0)

            speed = payload.get("speed", 0.5)
            self.servos.set_target(pan, tilt, speed)

        elif msg_type == "cmd.jog":
            if self.proximity_halt:
                self.servos.freeze()
                return None
            d_p = float(payload.get("delta_pan", payload.get("pan", 0.0)))
            d_t = float(payload.get("delta_tilt", payload.get("tilt", 0.0)))
            speed = float(payload.get("speed", 0.5))
            self.servos.set_target(self.servos.current_pan + d_p, self.servos.current_tilt + d_t, speed)

        elif msg_type in ("cmd.servo.center", "cmd.center"):
            self.estop_active = False
            self.failsafe_active = False
            self.buzzer_active = False
            self.buzzer_pattern = "off"
            self.servos.center()

        elif msg_type == "cmd.buzzer":
            action = payload.get("action", "off").lower()
            if action in ("on", "beep", "chirp", "alarm", "pulse"):
                self.buzzer_active = True
                self.buzzer_pattern = "beep" if action == "on" else action
            else:
                self.buzzer_active = False
                self.buzzer_pattern = "off"

        elif msg_type in ("sys.ping", "ping"):
            return {
                "type": "sys.pong",
                "timestamp": int(time.time() * 1000),
                "sender": "esp32",
                "seq": self.next_seq(),
                "corr_id": corr_id,
                "payload": {
                    "echo_timestamp": msg.get("timestamp", 0),
                    "rtt_ms": int((time.time() * 1000) - msg.get("timestamp", 0)),
                },
            }

        elif msg_type == "cmd.estop":
            action = payload.get("action", "")
            if action in ("resume", "clear", "reset"):
                self.estop_active = False
                self.failsafe_active = False
                self.buzzer_active = False
                self.buzzer_pattern = "off"
            else:
                self.estop_active = True
                self.servos.freeze()

        elif msg_type == "sys.safestop":
            action = payload.get("action", "freeze")
            if action in ("resume", "clear", "reset"):
                self.estop_active = False
                self.failsafe_active = False
            elif action == "center":
                self.estop_active = False
                self.servos.center()
            else:
                self.servos.freeze()
                if payload.get("release_pwm", False):
                    self.estop_active = True

        return None

    def next_seq(self) -> int:
        self.seq_num += 1
        return self.seq_num

    def generate_telemetry(self) -> Dict[str, Any]:
        """Generates standard telem.sensors JSON payload."""
        now_ms = int(time.time() * 1000)
        uptime_ms = int((time.time() - self.start_time) * 1000)

        is_valid = (2.0 <= self.sonar_distance <= 400.0)
        status_str = "in_range" if is_valid else "out_of_range"
        dist_cm = round(self.sonar_distance, 1) if is_valid else -1.0

        return {
            "type": "telem.sensors",
            "timestamp": now_ms,
            "sender": "esp32",
            "seq": self.next_seq(),
            "corr_id": None,
            "payload": {
                "sonar": {
                    "distance_cm": dist_cm,
                    "valid": is_valid,
                    "status": status_str,
                },
                "pir": {
                    "motion_detected": self.pir_state,
                    "trigger_count": int(self.sim_time // 8),
                    "last_trigger_ms": uptime_ms if self.pir_state else 0,
                },
                "servos": {
                    "pan_angle": round(self.servos.current_pan, 1),
                    "tilt_angle": round(self.servos.current_tilt, 1),
                    "pan_target": round(self.servos.target_pan, 1),
                    "tilt_target": round(self.servos.target_tilt, 1),
                    "is_moving": self.servos.is_moving,
                },
                "buzzer": {
                    "active": self.buzzer_active,
                    "pattern": "alarm" if self.failsafe_active else self.buzzer_pattern,
                },
                "system": {
                    "uptime_ms": uptime_ms,
                    "rssi_dbm": -55,
                    "free_heap_bytes": 284100,
                    "psram_free_bytes": 7180200,
                    "cpu_temp_c": 45.2,
                    "failsafe_active": self.failsafe_active,
                    "estop_active": self.estop_active,
                },
            },
        }


def run_standalone_test(duration: float = 4.0):
    """Executes standalone simulation verifying slew, limits, and watchdog."""
    print("=== SmartVision Mock ESP32 Firmware: Standalone Verification ===")
    esp = MockESP32Firmware()

    print("\n1. Testing Servo Slew Interpolation & Clamping:")
    # Command pan to 120° and tilt to 110°
    esp.handle_inbound_message(
        json.dumps(
            {
                "type": "cmd.servo.move",
                "timestamp": int(time.time() * 1000),
                "sender": "backend",
                "seq": 1,
                "payload": {"mode": "absolute", "pan": 120.0, "tilt": 110.0, "speed": 0.5},
            }
        )
    )

    dt = 0.02  # 50 Hz loop
    start = time.time()
    steps = 0
    while time.time() - start < 1.0:
        esp.servos.update(dt)
        esp.update_sensors(dt)
        steps += 1
        time.sleep(dt)

    print(
        f"   After 1.0s slew -> Pan: {esp.servos.current_pan:.1f}° (target {esp.servos.target_pan}°), "
        f"Tilt: {esp.servos.current_tilt:.1f}° (target {esp.servos.target_tilt}°)"
    )
    assert esp.servos.current_pan > 95.0, "Pan did not slew toward target"
    assert esp.servos.current_tilt > 95.0, "Tilt did not slew toward target"

    print("\n2. Testing Out-of-Bounds Angle Clamping:")
    # Attempt to command out of bounds: Pan 190° (limit 165°), Tilt 20° (limit 60°)
    esp.handle_inbound_message(
        json.dumps(
            {
                "type": "cmd.servo.move",
                "timestamp": int(time.time() * 1000),
                "sender": "backend",
                "seq": 2,
                "payload": {"mode": "absolute", "pan": 190.0, "tilt": 20.0, "speed": 1.0},
            }
        )
    )
    print(f"   Requested Pan=190.0°, Clamped to: {esp.servos.target_pan:.1f}° (Max: {esp.servos.PAN_MAX}°)")
    print(f"   Requested Tilt=20.0°,  Clamped to: {esp.servos.target_tilt:.1f}° (Min: {esp.servos.TILT_MIN}°)")
    assert esp.servos.target_pan == esp.servos.PAN_MAX, "Pan was not clamped to PAN_MAX"
    assert esp.servos.target_tilt == esp.servos.TILT_MIN, "Tilt was not clamped to TILT_MIN"

    print("\n3. Testing 800ms Hardware Watchdog Timeout:")
    # Simulate lack of messages for 0.9s
    time.sleep(0.9)
    triggered = esp.check_watchdog()
    print(f"   Watchdog triggered: {triggered} | Failsafe Active: {esp.failsafe_active}")
    assert esp.failsafe_active, "Watchdog failed to trigger failsafe after 800ms silence"

    print("\n4. Generating Sensor Telemetry Packet:")
    telem = esp.generate_telemetry()
    print("   Sample Payload:")
    print("   " + json.dumps(telem["payload"]["servos"]))
    print("   " + json.dumps(telem["payload"]["sonar"]))
    assert "distance_cm" in telem["payload"]["sonar"]

    print("\n5. Testing Defensive JSON Handling & Failsafe Integrity:")
    # Failsafe active: ensure malformed or non-dict JSON does NOT disarm failsafe or pet watchdog
    esp.failsafe_active = True
    esp.buzzer_active = True
    old_rx_ts = esp.last_rx_timestamp

    # 5.1 Syntax error in JSON
    res = esp.handle_inbound_message('{"type": "cmd.servo.move", "payload": {unclosed')
    assert res is None
    assert esp.failsafe_active is True, "Malformed JSON syntax must not clear failsafe"
    assert esp.buzzer_active is True, "Malformed JSON syntax must not clear buzzer"
    assert esp.last_rx_timestamp == old_rx_ts, "Malformed JSON syntax must not pet watchdog"

    # 5.2 Non-dictionary JSON (array, primitive)
    res_list = esp.handle_inbound_message("[1, 2, 3]")
    assert res_list is None
    assert esp.failsafe_active is True, "Non-dict JSON must not clear failsafe"
    assert esp.last_rx_timestamp == old_rx_ts, "Non-dict JSON must not pet watchdog"

    # 5.3 Null payload in command envelope
    res_null = esp.handle_inbound_message('{"type": "cmd.servo.move", "payload": null}')
    assert res_null is None
    assert esp.failsafe_active is False, "Valid recognized command must clear failsafe"
    assert esp.buzzer_active is False, "Valid recognized command must clear buzzer"
    assert esp.last_rx_timestamp > old_rx_ts, "Valid recognized command must pet watchdog"

    # 5.4 Re-arm failsafe and verify valid cmd.servo.center clears it
    esp.failsafe_active = True
    esp.buzzer_active = True
    esp.handle_inbound_message('{"type": "cmd.servo.center", "payload": {}}')
    assert esp.failsafe_active is False, "Valid center command must clear failsafe"
    assert esp.buzzer_active is False

    print("   Defensive JSON parsing and watchdog failsafe integrity verified.")

    print("\nAll Mock ESP32 firmware tests passed successfully!")


async def run_network_client(url: str, interval: float = 0.1, max_retries: Optional[int] = None):
    """Connects to live FastAPI backend at /ws/device with automatic reconnection."""
    print(f"Starting ESP32 network client targeting {url}...")
    esp = MockESP32Firmware()

    try:
        import aiohttp
    except ImportError:
        print("aiohttp not installed. Running in standalone test mode instead.")
        run_standalone_test()
        return

    retry_count = 0
    while max_retries is None or retry_count < max_retries:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as ws:
                    print(f"[ESP32] Connected to backend gateway at {url}")
                    retry_count = 0
                    esp.failsafe_active = False
                    esp.buzzer_active = False

                    async def send_telemetry_loop():
                        while not ws.closed:
                            telem = esp.generate_telemetry()
                            await ws.send_str(json.dumps(telem))
                            await asyncio.sleep(interval)

                    async def servo_loop():
                        while not ws.closed:
                            esp.servos.update(0.02)
                            esp.check_watchdog()
                            await asyncio.sleep(0.02)

                    async def receive_loop():
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    reply = esp.handle_inbound_message(msg.data)
                                    if reply:
                                        await ws.send_str(json.dumps(reply))
                                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    break
                        finally:
                            esp.servos.freeze()
                            esp.failsafe_active = True

                    await asyncio.gather(send_telemetry_loop(), receive_loop(), servo_loop())
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            esp.servos.freeze()
            esp.failsafe_active = True
            retry_count += 1
            backoff = min(2.0, 0.5 * retry_count)
            print(f"[ESP32] Connection dropped/failed ({e}). Safe-stopping servos. Reconnecting in {backoff:.1f}s...")
            await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            esp.servos.freeze()
            esp.failsafe_active = True
            break


def main():
    parser = argparse.ArgumentParser(description="SmartVision Mock ESP32-S3 Firmware Client")
    parser.add_argument("--mode", choices=["standalone", "network"], default="standalone")
    parser.add_argument("--url", type=str, default="ws://localhost:8000/ws/device")
    parser.add_argument("--interval", type=float, default=0.1, help="Telemetry interval in seconds (default 10 Hz)")
    args = parser.parse_args()

    if args.mode == "standalone":
        run_standalone_test()
    else:
        asyncio.run(run_network_client(args.url, args.interval))


if __name__ == "__main__":
    main()
