#!/usr/bin/env python3
"""
SmartVision - Mock Operator / Frontend Client
Simulates a web browser operator dashboard connecting to FastAPI /ws/client:
- Verifies telemetry ingestion & schema parsing
- Dispatches manual jog commands, centering, and patrol sweeps
- Tests rate limiting & burst command throttling
- Verifies rejection of out-of-bounds movement commands
Supports standalone test mode or live WebSocket connection to FastAPI backend.
"""

import argparse
import asyncio
import json
import math
import sys
import time
from typing import Any, Dict, List, Optional, Tuple


class CommandRateLimiter:
    """Enforces 20 Hz (50 ms) client-side command throttling (leaky bucket)."""

    def __init__(self, max_rate_hz: float = 20.0):
        self.min_interval = 1.0 / max_rate_hz
        self.last_sent_time = 0.0
        self.dropped_bursts = 0
        self.accepted_commands = 0

    def allow_send(self) -> bool:
        now = time.time()
        if now - self.last_sent_time >= self.min_interval:
            self.last_sent_time = now
            self.accepted_commands += 1
            return True
        else:
            self.dropped_bursts += 1
            return False


class ProtocolValidator:
    """Validates message payloads against SmartVision protocol specifications."""

    PAN_MIN = 15.0
    PAN_MAX = 165.0
    TILT_MIN = 60.0
    TILT_MAX = 135.0

    VALID_TYPES = {
        "sys.ping",
        "sys.pong",
        "sys.safestop",
        "sys.status",
        "cmd.servo.move",
        "cmd.servo.center",
        "cmd.servo.patrol",
        "cmd.buzzer",
        "telem.sensors",
        "track.frame_target",
        "track.mode_set",
        "track.select_id",
        "alert.event",
    }
    VALID_SENDERS = {"frontend", "backend", "esp32"}

    @classmethod
    def validate_envelope(cls, envelope: Any) -> Tuple[bool, Optional[str]]:
        """Validates outer 5-field message envelope schema."""
        if not isinstance(envelope, dict):
            return False, f"Envelope must be a JSON object (dictionary), got: {type(envelope).__name__}"

        required_fields = ["type", "timestamp", "sender", "seq", "payload"]
        for field in required_fields:
            if field not in envelope:
                return False, f"Missing required envelope field: '{field}'"

        msg_type = envelope.get("type")
        if not isinstance(msg_type, str) or msg_type not in cls.VALID_TYPES:
            return False, f"Invalid or unrecognized message type: {msg_type!r}"

        timestamp = envelope.get("timestamp")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool) or timestamp < 0:
            return False, f"Timestamp must be a non-negative number, got: {timestamp!r}"

        sender = envelope.get("sender")
        if not isinstance(sender, str) or sender not in cls.VALID_SENDERS:
            return False, f"Invalid sender {sender!r}: must be one of {cls.VALID_SENDERS}"

        seq = envelope.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            return False, f"Sequence number must be a non-negative integer, got: {seq!r}"

        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return False, f"Payload must be a dictionary, got: {type(payload).__name__}"

        return True, None

    @classmethod
    def validate_servo_move(cls, payload: Any) -> Tuple[bool, Optional[str]]:
        """Validates servo move command payload with strict type and range checks."""
        if not isinstance(payload, dict):
            return False, f"Payload must be a dictionary, got: {type(payload).__name__}"

        mode = payload.get("mode", "absolute")
        if mode not in ("absolute", "relative"):
            return False, f"Invalid mode '{mode}': must be 'absolute' or 'relative'"

        if "speed" in payload and payload["speed"] is not None:
            speed = payload["speed"]
            if not isinstance(speed, (int, float)) or isinstance(speed, bool) or math.isnan(speed):
                return False, f"Speed factor must be a valid number, got: {speed!r}"
            if not (0.1 <= speed <= 1.0):
                return False, f"Speed factor {speed} out of bounds [0.1, 1.0]"

        if mode == "absolute":
            pan = payload.get("pan")
            tilt = payload.get("tilt")

            if pan is None:
                return False, "Pan angle is required for absolute mode"
            if not isinstance(pan, (int, float)) or isinstance(pan, bool) or math.isnan(pan):
                return False, f"Pan angle must be a valid number, got: {pan!r}"
            if not (cls.PAN_MIN <= pan <= cls.PAN_MAX):
                return False, f"Pan angle {pan}° out of bounds [{cls.PAN_MIN}°, {cls.PAN_MAX}°]"

            if tilt is None:
                return False, "Tilt angle is required for absolute mode"
            if not isinstance(tilt, (int, float)) or isinstance(tilt, bool) or math.isnan(tilt):
                return False, f"Tilt angle must be a valid number, got: {tilt!r}"
            if not (cls.TILT_MIN <= tilt <= cls.TILT_MAX):
                return False, f"Tilt angle {tilt}° out of bounds [{cls.TILT_MIN}°, {cls.TILT_MAX}°]"

        elif mode == "relative":
            pan_step = payload.get("pan", 0.0)
            tilt_step = payload.get("tilt", 0.0)

            if not isinstance(pan_step, (int, float)) or isinstance(pan_step, bool) or math.isnan(pan_step):
                return False, f"Relative pan step must be a valid number, got: {pan_step!r}"
            if abs(pan_step) > 45.0:
                return False, f"Relative pan step {pan_step}° exceeds max 45.0°"

            if not isinstance(tilt_step, (int, float)) or isinstance(tilt_step, bool) or math.isnan(tilt_step):
                return False, f"Relative tilt step must be a valid number, got: {tilt_step!r}"
            if abs(tilt_step) > 30.0:
                return False, f"Relative tilt step {tilt_step}° exceeds max 30.0°"

        return True, None


class MockBackendClient:
    """Simulates operator actions, stress tests, and message verification."""

    def __init__(self, host: str = "localhost", port: int = 8000):
        self.url = f"ws://{host}:{port}/ws/client"
        self.seq_num = 0
        self.rate_limiter = CommandRateLimiter(max_rate_hz=20.0)
        self.received_telemetry: List[Dict] = []
        self.received_alerts: List[Dict] = []

    def next_seq(self) -> int:
        self.seq_num += 1
        return self.seq_num

    def create_envelope(self, msg_type: str, payload: Dict[str, Any], corr_id: Optional[str] = None) -> Dict[str, Any]:
        return {
            "type": msg_type,
            "timestamp": int(time.time() * 1000),
            "sender": "frontend",
            "seq": self.next_seq(),
            "corr_id": corr_id,
            "payload": payload,
        }

    def create_move_command(self, pan: float, tilt: float, mode: str = "absolute", speed: float = 0.5) -> Dict[str, Any]:
        payload = {"mode": mode, "pan": pan, "tilt": tilt, "speed": speed, "smooth": True}
        return self.create_envelope("cmd.servo.move", payload)

    def create_center_command(self) -> Dict[str, Any]:
        return self.create_envelope("cmd.servo.center", {"speed": 0.4})

    def create_target_select(self, track_id: int) -> Dict[str, Any]:
        return self.create_envelope("track.select_id", {"track_id": track_id})

    def create_safestop(self, reason: str = "operator_e_stop") -> Dict[str, Any]:
        return self.create_envelope("sys.safestop", {"reason": reason, "action": "freeze"})


def run_standalone_test():
    """Executes offline verification of client message construction, throttling, and validation."""
    print("=== SmartVision Mock Operator Client: Standalone Verification ===")
    client = MockBackendClient()

    print("\n1. Testing Message Envelope Construction:")
    move_cmd = client.create_move_command(pan=90.0, tilt=90.0)
    print("   Created Move Envelope:")
    print("   " + json.dumps(move_cmd))
    assert move_cmd["type"] == "cmd.servo.move"
    assert move_cmd["sender"] == "frontend"
    assert "timestamp" in move_cmd
    assert move_cmd["seq"] == 1

    print("\n2. Testing Protocol Boundary Validation:")
    # Envelope validation tests
    valid_env_ok, valid_env_err = ProtocolValidator.validate_envelope(move_cmd)
    assert valid_env_ok, f"Envelope validation failed for valid command: {valid_env_err}"

    bad_env_missing = {"type": "cmd.servo.move", "timestamp": int(time.time() * 1000), "sender": "frontend"}
    bad_ok, _ = ProtocolValidator.validate_envelope(bad_env_missing)
    assert not bad_ok, "Expected failure on missing required envelope fields"

    bad_env_type = {"type": "invalid.type", "timestamp": 12345, "sender": "frontend", "seq": 1, "payload": {}}
    bad_ok, _ = ProtocolValidator.validate_envelope(bad_env_type)
    assert not bad_ok, "Expected failure on invalid message type"

    bad_env_sender = {"type": "cmd.servo.move", "timestamp": 12345, "sender": "unknown_node", "seq": 1, "payload": {}}
    bad_ok, _ = ProtocolValidator.validate_envelope(bad_env_sender)
    assert not bad_ok, "Expected failure on invalid sender"

    bad_env_payload = {"type": "cmd.servo.move", "timestamp": 12345, "sender": "frontend", "seq": 1, "payload": "not_a_dict"}
    bad_ok, _ = ProtocolValidator.validate_envelope(bad_env_payload)
    assert not bad_ok, "Expected failure on non-dict envelope payload"

    # Servo move payload tests
    valid_payload = {"mode": "absolute", "pan": 120.0, "tilt": 85.0}
    ok, err = ProtocolValidator.validate_servo_move(valid_payload)
    print(f"   Validation of Pan=120°, Tilt=85° -> Valid: {ok}")
    assert ok, f"Expected valid, got: {err}"

    # Test out of bounds: Pan = 180° (limit 165°)
    invalid_pan = {"mode": "absolute", "pan": 180.0, "tilt": 85.0}
    ok, err = ProtocolValidator.validate_servo_move(invalid_pan)
    print(f"   Validation of Pan=180° (Limit 165°) -> Rejected: {not ok} | Reason: {err}")
    assert not ok, "Expected validation failure for pan 180°"

    # Test out of bounds: Tilt = 45° (limit 60°)
    invalid_tilt = {"mode": "absolute", "pan": 90.0, "tilt": 45.0}
    ok, err = ProtocolValidator.validate_servo_move(invalid_tilt)
    print(f"   Validation of Tilt=45° (Limit 60°) -> Rejected: {not ok} | Reason: {err}")
    assert not ok, "Expected validation failure for tilt 45°"

    # Test defensive handling: None, non-dict, non-numeric strings, nan, bools
    ok_none, _ = ProtocolValidator.validate_servo_move(None)
    assert not ok_none, "Expected failure on None payload"

    ok_str, _ = ProtocolValidator.validate_servo_move({"mode": "absolute", "pan": "not_a_num", "tilt": 90.0})
    assert not ok_str, "Expected failure on string pan angle"

    ok_nan, _ = ProtocolValidator.validate_servo_move({"mode": "absolute", "pan": float("nan"), "tilt": 90.0})
    assert not ok_nan, "Expected failure on nan pan angle"

    ok_bool, _ = ProtocolValidator.validate_servo_move({"mode": "absolute", "pan": True, "tilt": 90.0})
    assert not ok_bool, "Expected failure on boolean pan angle"

    print("\n3. Testing 20 Hz Command Rate Limiter (Burst Throttling):")
    # Simulate high frequency button spam (100 commands in 100 ms)
    limiter = CommandRateLimiter(max_rate_hz=20.0)
    sent = 0
    dropped = 0
    sim_start = time.time()
    for _ in range(50):
        if limiter.allow_send():
            sent += 1
        else:
            dropped += 1
        time.sleep(0.002)  # 2 ms interval = 500 Hz burst

    print(f"   Burst Test: Total Attempts: 50 | Accepted: {sent} | Throttled/Dropped: {dropped}")
    assert sent < 50, "Rate limiter failed to throttle high-frequency burst"
    assert dropped > 0, "Expected rate limiter to drop burst frames"

    print("\n4. Testing Telemetry Ingestion & Parsing:")
    sample_telem = {
        "type": "telem.sensors",
        "timestamp": int(time.time() * 1000),
        "sender": "esp32",
        "seq": 204,
        "payload": {
            "sonar": {"distance_cm": 42.8, "valid": True, "status": "in_range"},
            "pir": {"motion_detected": True, "trigger_count": 3},
            "servos": {"pan_angle": 90.2, "tilt_angle": 89.8, "is_moving": False},
        },
    }
    sonar_dist = sample_telem["payload"]["sonar"]["distance_cm"]
    pir_state = sample_telem["payload"]["pir"]["motion_detected"]
    pan_angle = sample_telem["payload"]["servos"]["pan_angle"]
    print(f"   Parsed Sonar Distance: {sonar_dist} cm | PIR Motion: {pir_state} | Pan Angle: {pan_angle}°")
    assert sonar_dist == 42.8
    assert pir_state is True

    print("\nAll Mock Operator Client tests passed successfully!")


async def run_network_client(url: str):
    """Connects to live FastAPI backend at /ws/client."""
    print(f"Attempting operator connection to {url}...")
    client = MockBackendClient()

    try:
        import aiohttp
    except ImportError:
        print("aiohttp not installed. Running in standalone test mode.")
        run_standalone_test()
        return

    async with aiohttp.ClientSession() as session:
        try:
            async with session.ws_connect(url) as ws:
                print(f"[Operator] Connected to dashboard gateway at {url}")

                # Send center command
                center_cmd = client.create_center_command()
                await ws.send_str(json.dumps(center_cmd))
                print("[Operator] Dispatched center command")

                async def listener():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            msg_type = data.get("type")
                            if msg_type == "telem.sensors":
                                p = data.get("payload", {})
                                dist = p.get("sonar", {}).get("distance_cm")
                                pan = p.get("servos", {}).get("pan_angle")
                                print(f"[Operator Ingest] Sonar: {dist} cm | Pan: {pan}°")
                            elif msg_type == "alert.event":
                                print(f"[Operator Alert] Event: {data.get('payload', {}).get('message')}")

                await listener()
        except Exception as e:
            print(f"[Operator] Connection failed: {e}. Switching to standalone mode.")
            run_standalone_test()


def main():
    parser = argparse.ArgumentParser(description="SmartVision Mock Operator Client")
    parser.add_argument("--mode", choices=["test", "network"], default="test")
    parser.add_argument("--url", type=str, default="ws://localhost:8000/ws/client")
    args = parser.parse_args()

    if args.mode == "test":
        run_standalone_test()
    else:
        asyncio.run(run_network_client(args.url))


if __name__ == "__main__":
    main()
