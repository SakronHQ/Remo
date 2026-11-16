#!/usr/bin/env python3
"""
SmartVision - Automated Closed-Loop System Convergence Simulator
Simulates the entire software and control pipeline without physical hardware:
- Generates synthetic camera frames and optical target coordinates
- Applies Hysteresis Deadband (±15px / ±25px) and EMA Low-Pass Filter (α=0.35)
- Executes Dual-Axis PID tracking controller with anti-windup
- Dispatches and validates JSON `cmd.servo.move` messages to Virtual ESP32 firmware
- Simulates PCA9685 slew inertia and closed-loop optical feedback
- Asserts mathematical tracking convergence, deadband jitter suppression, and fail-safe triggers
"""

import json
import math
import sys
import time
from typing import Dict, List, Tuple

# Import our mock interfaces
from mock_backend_client import ProtocolValidator
from mock_esp32_firmware import MockESP32Firmware, VirtualPCA9685Servos


class PIDController:
    """Discrete-time Dual-Axis PID Controller with Anti-Windup and Velocity Limiting."""

    def __init__(
        self,
        kp: float = 0.025,
        ki: float = 0.0005,
        kd: float = 0.001,
        i_max: float = 1.0,
        max_step_deg: float = 3.0,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.i_max = i_max
        self.max_step_deg = max_step_deg

        self.integral = 0.0
        self.prev_error = 0.0

    def reset(self):
        self.integral = 0.0
        self.prev_error = 0.0

    def update(self, error: float, dt: float, is_settled: bool = False) -> float:
        if dt <= 0.0:
            return 0.0

        # Integral term with anti-windup clamping and deadband bleed/reset
        if is_settled or abs(error) < 1e-4:
            self.integral = 0.0
        elif abs(error) < 1.0:
            # Bleed integral term when error is below 1 pixel
            self.integral *= 0.8
        else:
            self.integral += self.ki * error * dt
            self.integral = max(-self.i_max, min(self.i_max, self.integral))

        # Proportional term
        p_term = self.kp * error

        # Derivative term
        derivative = (error - self.prev_error) / dt
        d_term = self.kd * derivative
        self.prev_error = error

        # If explicitly settled, suppress residual command output
        if is_settled:
            return 0.0

        # Total control delta
        output = p_term + self.integral + d_term

        # Clamp output to max allowable angular change per step
        return max(-self.max_step_deg, min(self.max_step_deg, output))


class MotionSmoothingFilter:
    """Dual-threshold Hysteresis Deadband and Exponential Moving Average filter."""

    def __init__(self, inner_deadband: float = 15.0, outer_deadband: float = 25.0, alpha: float = 0.35):
        self.inner_db = inner_deadband
        self.outer_db = outer_deadband
        self.alpha = alpha

        self.in_deadband_x = True
        self.in_deadband_y = True
        self.filtered_x = 0.0
        self.filtered_y = 0.0

    def reset(self):
        self.in_deadband_x = True
        self.in_deadband_y = True
        self.filtered_x = 0.0
        self.filtered_y = 0.0

    def filter(self, raw_err_x: float, raw_err_y: float) -> Tuple[float, float, bool]:
        # Hysteresis Deadband for X
        abs_x = abs(raw_err_x)
        if self.in_deadband_x:
            if abs_x >= self.outer_db:
                self.in_deadband_x = False
                active_err_x = raw_err_x
            else:
                active_err_x = 0.0
        else:
            if abs_x <= self.inner_db:
                self.in_deadband_x = True
                active_err_x = 0.0
            else:
                active_err_x = raw_err_x

        # Hysteresis Deadband for Y
        abs_y = abs(raw_err_y)
        if self.in_deadband_y:
            if abs_y >= self.outer_db:
                self.in_deadband_y = False
                active_err_y = raw_err_y
            else:
                active_err_y = 0.0
        else:
            if abs_y <= self.inner_db:
                self.in_deadband_y = True
                active_err_y = 0.0
            else:
                active_err_y = raw_err_y

        # Exponential Moving Average Low-Pass Filter
        self.filtered_x = self.alpha * active_err_x + (1.0 - self.alpha) * self.filtered_x
        self.filtered_y = self.alpha * active_err_y + (1.0 - self.alpha) * self.filtered_y

        is_settled = self.in_deadband_x and self.in_deadband_y
        return self.filtered_x, self.filtered_y, is_settled


class ClosedLoopSimEnvironment:
    """
    Closed-loop physical optical simulation:
    Maps servo angular displacement to pixel coordinate displacement on the camera sensor.
    """

    FRAME_WIDTH = 640
    FRAME_HEIGHT = 480
    OPTICAL_CENTER_X = 320.0
    OPTICAL_CENTER_Y = 240.0

    # Approx 60° horizontal FOV and 45° vertical FOV for a standard 640x480 webcam
    PIXELS_PER_DEG_X = 640.0 / 60.0  # ~10.67 px/deg
    PIXELS_PER_DEG_Y = 480.0 / 45.0  # ~10.67 px/deg

    def __init__(self):
        self.esp = MockESP32Firmware()
        self.pid_pan = PIDController(kp=0.025, ki=0.0005, kd=0.001, i_max=1.0, max_step_deg=3.0)
        self.pid_tilt = PIDController(kp=0.025, ki=0.0005, kd=0.001, i_max=1.0, max_step_deg=2.0)
        self.filter = MotionSmoothingFilter(inner_deadband=15.0, outer_deadband=25.0, alpha=0.35)

    def compute_sensor_coords(self, target_world_x: float, target_world_y: float) -> Tuple[float, float]:
        """
        Calculates pixel coordinate of a stationary world target as the camera rotates.
        As Pan servo angle increases (panning right), the target appears further to the left (smaller X).
        """
        pan_delta_deg = self.esp.servos.current_pan - 90.0
        tilt_delta_deg = self.esp.servos.current_tilt - 90.0

        pixel_x = target_world_x - (pan_delta_deg * self.PIXELS_PER_DEG_X)
        pixel_y = target_world_y + (tilt_delta_deg * self.PIXELS_PER_DEG_Y)

        return pixel_x, pixel_y


def run_convergence_simulation() -> bool:
    print("======================================================================")
    print("  SmartVision Automated Closed-Loop Tracking Convergence Simulator   ")
    print("======================================================================")

    env = ClosedLoopSimEnvironment()
    dt = 0.04  # 25 FPS vision / control cycle (40 ms)

    # -------------------------------------------------------------------------
    # TEST 1: Displaced Target Closed-Loop Convergence
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Verifying Closed-Loop Convergence on Displaced Target:")
    # Place a target in the world such that initially, at Pan=90°, it appears at x=480, y=280
    target_world_x = 480.0
    target_world_y = 280.0

    initial_px, initial_py = env.compute_sensor_coords(target_world_x, target_world_y)
    initial_err_x = initial_px - env.OPTICAL_CENTER_X
    initial_err_y = initial_py - env.OPTICAL_CENTER_Y

    print(f"  Target Initial Position: ({initial_px:.1f}, {initial_py:.1f}) px")
    print(f"  Initial Error: X = {initial_err_x:+.1f} px, Y = {initial_err_y:+.1f} px")

    sim_time = 0.0
    max_duration = 2.0  # seconds
    converged = False
    convergence_time = 0.0
    step = 0

    print("  Iterating control loop at 25 Hz...")
    while sim_time < max_duration:
        step += 1
        sim_time += dt

        # 1. Optical sensor acquires current target coordinates
        px, py = env.compute_sensor_coords(target_world_x, target_world_y)
        raw_err_x = px - env.OPTICAL_CENTER_X
        raw_err_y = py - env.OPTICAL_CENTER_Y

        # 2. Deadband & EMA filtering
        filt_err_x, filt_err_y, is_settled = env.filter.filter(raw_err_x, raw_err_y)

        # 3. PID computation
        delta_pan = env.pid_pan.update(filt_err_x, dt, is_settled=env.filter.in_deadband_x)
        delta_tilt = env.pid_tilt.update(filt_err_y, dt, is_settled=env.filter.in_deadband_y)

        # 4. Command issuance to virtual ESP32 with Tier 1 angle clamping
        new_target_pan = max(ProtocolValidator.PAN_MIN, min(ProtocolValidator.PAN_MAX, env.esp.servos.current_pan + delta_pan))
        new_target_tilt = max(ProtocolValidator.TILT_MIN, min(ProtocolValidator.TILT_MAX, env.esp.servos.current_tilt - delta_tilt))

        cmd_payload = {"mode": "absolute", "pan": new_target_pan, "tilt": new_target_tilt, "speed": 0.6}
        ok, err_msg = ProtocolValidator.validate_servo_move(cmd_payload)
        assert ok, f"Protocol validation failed: {err_msg}"

        env.esp.handle_inbound_message(
            json.dumps({"type": "cmd.servo.move", "timestamp": int(time.time() * 1000), "payload": cmd_payload})
        )

        # 5. Virtual ESP32 physical slew update (simulates motor inertia at 50 Hz)
        env.esp.servos.update(dt)

        if step % 5 == 0:
            print(
                f"  t={sim_time:.2f}s | Sensor: ({px:5.1f}, {py:5.1f}) | "
                f"Err: ({raw_err_x:+5.1f}, {raw_err_y:+5.1f}) px | "
                f"Servos: ({env.esp.servos.current_pan:5.1f}°, {env.esp.servos.current_tilt:5.1f}°)"
            )

        # Check convergence criteria (inside deadband +/- 15px)
        if abs(raw_err_x) <= 15.0 and abs(raw_err_y) <= 15.0 and not converged:
            converged = True
            convergence_time = sim_time

    print(f"\n  Convergence Achieved: {converged}")
    print(f"  Time to Enter Deadband: {convergence_time:.2f} s (Requirement: < 1.50 s)")
    assert converged, "PID controller failed to converge target within deadband"
    assert convergence_time < 1.50, f"Convergence took {convergence_time:.2f}s, exceeding 1.50s requirement"

    # -------------------------------------------------------------------------
    # TEST 2: Jitter Suppression in Central Deadband
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Verifying Central Deadband Acoustic Jitter Suppression:")
    # Reset filter and PID state
    env.filter.reset()
    env.pid_pan.reset()
    env.pid_tilt.reset()
    # Simulate stationary target with coordinate noise (+/- 4 px)
    jitter_inputs = [320.0, 323.0, 318.0, 324.0, 317.0, 321.0]
    jitter_deltas = []

    for jx in jitter_inputs:
        raw_x = jx - 320.0
        fx, _, _ = env.filter.filter(raw_x, 0.0)
        d_pan = env.pid_pan.update(fx, dt)
        jitter_deltas.append(d_pan)

    max_jitter_delta = max(abs(d) for d in jitter_deltas)
    print(f"  Inputs around center (320px): {jitter_inputs}")
    print(f"  Output commanded deltas:      {jitter_deltas}")
    print(f"  Max Angular Correction:       {max_jitter_delta:.4f}°")
    assert max_jitter_delta == 0.0, "Deadband filter failed: emitted non-zero servo motion for central jitter"
    print("  -> PASS: Central jitter completely suppressed. Zero servo buzzing.")

    # -------------------------------------------------------------------------
    # TEST 3: Hardware Watchdog Fail-Safe Trigger
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Verifying 800ms Hardware Watchdog Timeout:")
    # Simulate communication silence for 850 ms
    time.sleep(0.85)
    triggered = env.esp.check_watchdog()
    print(f"  Watchdog triggered after 850ms: {triggered}")
    print(f"  ESP32 Failsafe State Active:   {env.esp.failsafe_active}")
    print(f"  Buzzer Warning Alarm Active:   {env.esp.buzzer_active}")
    assert env.esp.failsafe_active, "ESP32 failsafe was not engaged by watchdog"
    print("  -> PASS: Hardware watchdog engaged within 800ms threshold.")

    # -------------------------------------------------------------------------
    # TEST 4: Mechanical Limit Clamping
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Verifying Mechanical Travel Limit Clamping:")
    # Target way off to the right (x = 1200 px), demanding > 180° pan
    extreme_pan = 210.0
    extreme_tilt = 40.0
    print(f"  Commanding Extreme Out-of-Bounds Angles: Pan = {extreme_pan}°, Tilt = {extreme_tilt}°")

    env.esp.servos.set_target(extreme_pan, extreme_tilt, 1.0)
    print(f"  Clamped Target Pan:  {env.esp.servos.target_pan:.1f}° (Limit: {VirtualPCA9685Servos.PAN_MAX}°)")
    print(f"  Clamped Target Tilt: {env.esp.servos.target_tilt:.1f}° (Limit: {VirtualPCA9685Servos.TILT_MIN}°)")

    assert env.esp.servos.target_pan == VirtualPCA9685Servos.PAN_MAX
    assert env.esp.servos.target_tilt == VirtualPCA9685Servos.TILT_MIN
    print("  -> PASS: Physical hardware boundaries strictly enforced.")

    # -------------------------------------------------------------------------
    # TEST 5: Tier 1 Clamping on Extreme World Target Displacements
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Verifying Tier 1 Clamping on Out-of-Bounds Displaced Target:")
    env = ClosedLoopSimEnvironment()
    target_out_x = 1200.0  # Far right, requiring > 165° pan
    target_out_y = 640.0   # Far bottom, requiring > 135° tilt
    print(f"  Simulating target at world ({target_out_x}, {target_out_y}) demanding travel past physical limits...")

    for _ in range(50):
        px, py = env.compute_sensor_coords(target_out_x, target_out_y)
        fx, fy, _ = env.filter.filter(px - env.OPTICAL_CENTER_X, py - env.OPTICAL_CENTER_Y)
        dp = env.pid_pan.update(fx, dt, is_settled=env.filter.in_deadband_x)
        dtilt = env.pid_tilt.update(fy, dt, is_settled=env.filter.in_deadband_y)

        # Tier 1 clamping must prevent out-of-bounds angles before validator check
        new_pan = max(ProtocolValidator.PAN_MIN, min(ProtocolValidator.PAN_MAX, env.esp.servos.current_pan + dp))
        new_tilt = max(ProtocolValidator.TILT_MIN, min(ProtocolValidator.TILT_MAX, env.esp.servos.current_tilt - dtilt))

        cmd = {"mode": "absolute", "pan": new_pan, "tilt": new_tilt, "speed": 0.6}
        ok, err = ProtocolValidator.validate_servo_move(cmd)
        assert ok, f"Protocol validation unexpectedly failed: {err}"

        env.esp.servos.set_target(new_pan, new_tilt, 0.6)
        env.esp.servos.update(dt)

    print(f"  Final Clamped Pan:  {env.esp.servos.current_pan:.1f}° (Limit: {ProtocolValidator.PAN_MAX}°)")
    print(f"  Final Clamped Tilt: {env.esp.servos.current_tilt:.1f}° (Limit: {ProtocolValidator.TILT_MAX}°)")
    assert env.esp.servos.current_pan <= ProtocolValidator.PAN_MAX
    assert env.esp.servos.current_tilt <= ProtocolValidator.TILT_MAX
    print("  -> PASS: Tier 1 clamping safely prevented protocol validator assertion crash.")

    # -------------------------------------------------------------------------
    # TEST 6: Deadband Limit-Cycle Hunting Elimination
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Verifying Elimination of Deadband Limit-Cycle Hunting:")
    env = ClosedLoopSimEnvironment()
    stationary_x = 480.0
    stationary_y = 280.0
    print("  Running 500 steps (20.0s) on stationary target to verify zero deadband drift...")

    settled_samples = []
    for step_idx in range(500):
        px, py = env.compute_sensor_coords(stationary_x, stationary_y)
        rx = px - env.OPTICAL_CENTER_X
        ry = py - env.OPTICAL_CENTER_Y
        fx, fy, is_settled = env.filter.filter(rx, ry)
        dp = env.pid_pan.update(fx, dt, is_settled=env.filter.in_deadband_x)
        dtilt = env.pid_tilt.update(fy, dt, is_settled=env.filter.in_deadband_y)

        new_pan = max(ProtocolValidator.PAN_MIN, min(ProtocolValidator.PAN_MAX, env.esp.servos.current_pan + dp))
        new_tilt = max(ProtocolValidator.TILT_MIN, min(ProtocolValidator.TILT_MAX, env.esp.servos.current_tilt - dtilt))

        env.esp.servos.set_target(new_pan, new_tilt, 0.6)
        env.esp.servos.update(dt)

        if step_idx >= 100:  # After initial convergence
            settled_samples.append((env.esp.servos.current_pan, env.pid_pan.integral, dp, rx))

    pan_positions = [s[0] for s in settled_samples]
    pan_integrals = [s[1] for s in settled_samples]
    pan_deltas = [s[2] for s in settled_samples]
    pan_drift = max(pan_positions) - min(pan_positions)

    print(f"  Pan Position Range: min={min(pan_positions):.3f}°, max={max(pan_positions):.3f}°, drift={pan_drift:.4f}°")
    print(f"  Max Absolute Integral in Deadband: {max(abs(i) for i in pan_integrals):.6f}")
    print(f"  Max Absolute Commanded Delta in Deadband: {max(abs(d) for d in pan_deltas):.6f}°")

    assert pan_drift < 0.05, f"Limit-cycle hunting detected: pan drifted {pan_drift:.4f}° in deadband"
    assert max(abs(i) for i in pan_integrals) == 0.0, "Non-zero integral accumulated while in deadband"
    assert max(abs(d) for d in pan_deltas) == 0.0, "Non-zero motion delta commanded while settled"
    print("  -> PASS: Limit-cycle hunting completely eliminated. Servo position is stable.")

    print("\n======================================================================")
    print("  ALL CLOSED-LOOP SYSTEM CONVERGENCE TESTS PASSED!                   ")
    print("======================================================================")
    return True


if __name__ == "__main__":
    success = run_convergence_simulation()
    sys.exit(0 if success else 1)
