"""
SmartVision - Closed-Loop Dual-Axis PID Tracking Controller
Adheres to docs/protocol.md and docs/architecture.md.
Features:
- Dual-threshold hysteresis deadband (inner +-15px, outer +-25px) to eliminate servo jitter
- Exponential Moving Average (EMA) low-pass smoothing (alpha = 0.35)
- Discrete PID controller with anti-windup integral clamping and integral bleed
- Physical slew rate limiting (80 deg/s)
- 20 Hz output command rate limiting
- Physical boundary clamping (Pan: 15°–165°, Tilt: 60°–135°)
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional, Tuple


@dataclass
class TrackingControlOutput:
    """Telemetry snapshot produced by the dual-axis tracking controller."""
    pan_angle: float
    tilt_angle: float
    delta_pan: float
    delta_tilt: float
    raw_error_x: float
    raw_error_y: float
    filtered_error_x: float
    filtered_error_y: float
    in_deadband_x: bool
    in_deadband_y: bool
    is_settled: bool
    should_dispatch_command: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pan_angle": round(self.pan_angle, 2),
            "tilt_angle": round(self.tilt_angle, 2),
            "delta_pan": round(self.delta_pan, 3),
            "delta_tilt": round(self.delta_tilt, 3),
            "raw_error_x": round(self.raw_error_x, 1),
            "raw_error_y": round(self.raw_error_y, 1),
            "filtered_error_x": round(self.filtered_error_x, 2),
            "filtered_error_y": round(self.filtered_error_y, 2),
            "in_deadband_x": self.in_deadband_x,
            "in_deadband_y": self.in_deadband_y,
            "is_settled": self.is_settled,
            "should_dispatch_command": self.should_dispatch_command,
        }

    def to_servo_command_payload(self, mode: str = "absolute", speed: float = 0.5) -> Dict[str, Any]:
        """Formats movement payload conforming to docs/protocol.md cmd.servo.move."""
        if mode == "relative":
            return {
                "mode": "relative",
                "pan": round(self.delta_pan, 1),
                "tilt": round(-self.delta_tilt, 1),
                "speed": speed,
                "smooth": True,
            }
        return {
            "mode": "absolute",
            "pan": round(self.pan_angle, 1),
            "tilt": round(self.tilt_angle, 1),
            "speed": speed,
            "smooth": True,
        }


class HysteresisDeadband:
    """
    Dual-threshold hysteresis deadband preventing acoustic buzzing and servo hunt:
    - Inner threshold (+-15 px): boundary to enter deadband (settled)
    - Outer threshold (+-25 px): boundary to break out of deadband (motion resumes)
    """

    def __init__(self, inner: float = 15.0, outer: float = 25.0):
        self.inner = inner
        self.outer = outer
        self.in_deadband = True

    def reset(self) -> None:
        self.in_deadband = True

    def filter(self, raw_error: float) -> Tuple[float, bool]:
        abs_err = abs(raw_error)
        if self.in_deadband:
            if abs_err >= self.outer:
                self.in_deadband = False
                return raw_error, False
            else:
                return 0.0, True
        else:
            if abs_err <= self.inner:
                self.in_deadband = True
                return 0.0, True
            else:
                return raw_error, False


class EMASmoother:
    """
    First-order Exponential Moving Average (EMA) low-pass filter.
    e_filtered[k] = alpha * e[k] + (1 - alpha) * e_filtered[k-1]
    """

    def __init__(self, alpha: float = 0.35):
        self.alpha = max(0.01, min(1.0, alpha))
        self.filtered = 0.0

    def reset(self) -> None:
        self.filtered = 0.0

    def filter(self, value: float) -> float:
        self.filtered = self.alpha * value + (1.0 - self.alpha) * self.filtered
        return self.filtered


class SingleAxisPID:
    """
    Discrete PID controller with anti-windup clamping and integral bleed on settle.
    """

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        i_max: float,
        max_step_deg: float,
    ):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.i_max = i_max
        self.max_step_deg = max_step_deg

        self.integral = 0.0
        self.prev_error = 0.0

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_error = 0.0

    def update(self, error: float, dt: float, is_settled: bool = False) -> float:
        if dt <= 0.0:
            return 0.0

        # Integral anti-windup with deadband reset/bleed
        if is_settled or abs(error) < 1e-4:
            self.integral = 0.0
        elif abs(error) < 1.0:
            self.integral *= 0.80  # bleed integral when error is sub-pixel
        else:
            self.integral += self.ki * error * dt
            self.integral = max(-self.i_max, min(self.i_max, self.integral))

        # Proportional term
        p_term = self.kp * error

        # Derivative term on error
        derivative = (error - self.prev_error) / dt
        d_term = self.kd * derivative
        self.prev_error = error

        if is_settled:
            return 0.0

        output = p_term + self.integral + d_term
        return max(-self.max_step_deg, min(self.max_step_deg, output))


class DualAxisTrackingController:
    """
    Closed-loop Dual-Axis (Pan & Tilt) PID tracking controller.
    Enforces deadband hysteresis, EMA smoothing, 80 deg/s slew limiting,
    20 Hz command rate limiting, and physical boundary clamping.
    """

    # Physical boundary constants from docs/protocol.md
    PAN_MIN = 15.0
    PAN_MAX = 165.0
    PAN_CENTER = 90.0

    TILT_MIN = 60.0
    TILT_MAX = 135.0
    TILT_CENTER = 90.0

    # Max slew rate: 80 degrees/second
    MAX_SLEW_RATE_DEG_S = 80.0

    # Output command rate limit: 20 Hz (50 ms minimum interval)
    MAX_COMMAND_RATE_HZ = 20.0
    MIN_COMMAND_INTERVAL_S = 1.0 / MAX_COMMAND_RATE_HZ

    def __init__(
        self,
        frame_width: int = 640,
        frame_height: int = 480,
        kp_pan: float = 0.04,
        ki_pan: float = 0.005,
        kd_pan: float = 0.008,
        i_max_pan: float = 5.0,
        max_step_pan: float = 3.0,
        kp_tilt: float = 0.03,
        ki_tilt: float = 0.003,
        kd_tilt: float = 0.006,
        i_max_tilt: float = 3.0,
        max_step_tilt: float = 2.0,
        inner_deadband: float = 15.0,
        outer_deadband: float = 25.0,
        alpha_ema: float = 0.35,
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.optical_center_x = frame_width / 2.0
        self.optical_center_y = frame_height / 2.0

        # Current estimated servo shaft angles
        self.current_pan = self.PAN_CENTER
        self.current_tilt = self.TILT_CENTER

        # Sub-controllers
        self.pid_pan = SingleAxisPID(
            kp=kp_pan, ki=ki_pan, kd=kd_pan, i_max=i_max_pan, max_step_deg=max_step_pan
        )
        self.pid_tilt = SingleAxisPID(
            kp=kp_tilt, ki=ki_tilt, kd=kd_tilt, i_max=i_max_tilt, max_step_deg=max_step_tilt
        )

        self.db_x = HysteresisDeadband(inner=inner_deadband, outer=outer_deadband)
        self.db_y = HysteresisDeadband(inner=inner_deadband, outer=outer_deadband)

        self.ema_x = EMASmoother(alpha=alpha_ema)
        self.ema_y = EMASmoother(alpha=alpha_ema)

        self._last_command_time = 0.0
        self._last_update_time = time.time()
        self._last_delta_pan = 0.0
        self._last_delta_tilt = 0.0
        self._was_settled = True

        # Inversion & Dynamic Performance Presets
        self.invert_pan = False
        self.invert_tilt = False
        self.current_preset = "normal"

    PRESETS = {
        "smooth": {
            "kp_pan": 0.035, "kd_pan": 0.003, "kp_tilt": 0.025, "kd_tilt": 0.002,
            "max_slew": 50.0, "ema_alpha": 0.20
        },
        "normal": {
            "kp_pan": 0.055, "kd_pan": 0.006, "kp_tilt": 0.040, "kd_tilt": 0.004,
            "max_slew": 80.0, "ema_alpha": 0.35
        },
        "sports": {
            "kp_pan": 0.085, "kd_pan": 0.010, "kp_tilt": 0.065, "kd_tilt": 0.008,
            "max_slew": 130.0, "ema_alpha": 0.60
        },
    }

    def set_preset(self, preset_name: str) -> None:
        """Applies dynamic PID & smoothing performance preset ('smooth', 'normal', 'sports')."""
        if preset_name in self.PRESETS:
            cfg = self.PRESETS[preset_name]
            self.pid_pan.kp = cfg["kp_pan"]
            self.pid_pan.kd = cfg["kd_pan"]
            self.pid_tilt.kp = cfg["kp_tilt"]
            self.pid_tilt.kd = cfg["kd_tilt"]
            self.MAX_SLEW_RATE_DEG_S = cfg["max_slew"]
            self.ema_x.alpha = cfg["ema_alpha"]
            self.ema_y.alpha = cfg["ema_alpha"]
            self.current_preset = preset_name

    def set_inversion(self, invert_pan: Optional[bool] = None, invert_tilt: Optional[bool] = None) -> None:
        """Sets Pan and Tilt axis motion inversion."""
        if invert_pan is not None:
            self.invert_pan = bool(invert_pan)
        if invert_tilt is not None:
            self.invert_tilt = bool(invert_tilt)

    def reset(self, pan: float = PAN_CENTER, tilt: float = TILT_CENTER) -> None:
        """Resets controller state and re-centers servo coordinates."""
        self.current_pan = max(self.PAN_MIN, min(self.PAN_MAX, pan))
        self.current_tilt = max(self.TILT_MIN, min(self.TILT_MAX, tilt))
        self.pid_pan.reset()
        self.pid_tilt.reset()
        self.db_x.reset()
        self.db_y.reset()
        self.ema_x.reset()
        self.ema_y.reset()
        self._last_command_time = 0.0
        self._last_update_time = time.time()
        self._last_delta_pan = 0.0
        self._last_delta_tilt = 0.0
        self._was_settled = True

        # Inversion & Dynamic Performance Presets
        self.invert_pan = False
        self.invert_tilt = False
        self.current_preset = "normal"

    PRESETS = {
        "smooth": {
            "kp_pan": 0.035, "kd_pan": 0.003, "kp_tilt": 0.025, "kd_tilt": 0.002,
            "max_slew": 50.0, "ema_alpha": 0.20
        },
        "normal": {
            "kp_pan": 0.055, "kd_pan": 0.006, "kp_tilt": 0.040, "kd_tilt": 0.004,
            "max_slew": 80.0, "ema_alpha": 0.35
        },
        "sports": {
            "kp_pan": 0.085, "kd_pan": 0.010, "kp_tilt": 0.065, "kd_tilt": 0.008,
            "max_slew": 130.0, "ema_alpha": 0.60
        },
    }

    def set_preset(self, preset_name: str) -> None:
        """Applies dynamic PID & smoothing performance preset ('smooth', 'normal', 'sports')."""
        if preset_name in self.PRESETS:
            cfg = self.PRESETS[preset_name]
            self.pid_pan.kp = cfg["kp_pan"]
            self.pid_pan.kd = cfg["kd_pan"]
            self.pid_tilt.kp = cfg["kp_tilt"]
            self.pid_tilt.kd = cfg["kd_tilt"]
            self.MAX_SLEW_RATE_DEG_S = cfg["max_slew"]
            self.ema_x.alpha = cfg["ema_alpha"]
            self.ema_y.alpha = cfg["ema_alpha"]
            self.current_preset = preset_name

    def set_inversion(self, invert_pan: Optional[bool] = None, invert_tilt: Optional[bool] = None) -> None:
        """Sets Pan and Tilt axis motion inversion."""
        if invert_pan is not None:
            self.invert_pan = bool(invert_pan)
        if invert_tilt is not None:
            self.invert_tilt = bool(invert_tilt)

    def center(self) -> TrackingControlOutput:
        """Explicitly commands return to neutral calibrated center (90°, 90°)."""
        self.reset(pan=self.PAN_CENTER, tilt=self.TILT_CENTER)
        return TrackingControlOutput(
            pan_angle=self.PAN_CENTER,
            tilt_angle=self.TILT_CENTER,
            delta_pan=0.0,
            delta_tilt=0.0,
            raw_error_x=0.0,
            raw_error_y=0.0,
            filtered_error_x=0.0,
            filtered_error_y=0.0,
            in_deadband_x=True,
            in_deadband_y=True,
            is_settled=True,
            should_dispatch_command=True,
        )

    def update(
        self,
        target_centroid: Optional[Tuple[float, float]],
        dt: Optional[float] = None,
        coast_factor: float = 1.0,
        is_coasting: bool = False,
        auto_center: bool = False,
    ) -> TrackingControlOutput:
        """
        Executes one tracking cycle:
        1. Computes raw pixel error relative to frame center (320, 240)
        2. Applies hysteresis deadband (inner +-15px, outer +-25px)
        3. Applies EMA smoothing filter (alpha = 0.35)
        4. Calculates PID control increments
        5. Enforces slew rate limit (80°/s) and coasting momentum decay
        6. Clamps to physical servo bounds ([15°, 165°] Pan, [60°, 135°] Tilt)
        7. Evaluates 20 Hz output command rate limiter and deadband suppression
        """
        now = time.time()
        if dt is None:
            dt = max(0.001, min(0.20, now - self._last_update_time))
        self._last_update_time = now

        # Case 1: Auto-centering back to neutral (90°, 90°) upon target loss timeout
        if auto_center:
            diff_pan = self.PAN_CENTER - self.current_pan
            diff_tilt = self.TILT_CENTER - self.current_tilt
            max_slew_deg = self.MAX_SLEW_RATE_DEG_S * dt

            if abs(diff_pan) < 0.2 and abs(diff_tilt) < 0.2:
                self.current_pan = self.PAN_CENTER
                self.current_tilt = self.TILT_CENTER
                self._last_delta_pan = 0.0
                self._last_delta_tilt = 0.0
                self._was_settled = True
                return TrackingControlOutput(
                    pan_angle=self.PAN_CENTER,
                    tilt_angle=self.TILT_CENTER,
                    delta_pan=0.0,
                    delta_tilt=0.0,
                    raw_error_x=0.0,
                    raw_error_y=0.0,
                    filtered_error_x=0.0,
                    filtered_error_y=0.0,
                    in_deadband_x=True,
                    in_deadband_y=True,
                    is_settled=True,
                    should_dispatch_command=False,
                )

            delta_pan = max(-max_slew_deg, min(max_slew_deg, diff_pan))
            delta_tilt = max(-max_slew_deg, min(max_slew_deg, diff_tilt))
            self.current_pan = max(self.PAN_MIN, min(self.PAN_MAX, self.current_pan + delta_pan))
            self.current_tilt = max(self.TILT_MIN, min(self.TILT_MAX, self.current_tilt + delta_tilt))
            self._last_delta_pan = delta_pan
            self._last_delta_tilt = delta_tilt
            self._was_settled = False
            should_dispatch = self._evaluate_rate_limit(now)

            return TrackingControlOutput(
                pan_angle=self.current_pan,
                tilt_angle=self.current_tilt,
                delta_pan=delta_pan,
                delta_tilt=delta_tilt,
                raw_error_x=0.0,
                raw_error_y=0.0,
                filtered_error_x=0.0,
                filtered_error_y=0.0,
                in_deadband_x=False,
                in_deadband_y=False,
                is_settled=False,
                should_dispatch_command=should_dispatch,
            )

        # Case 2: Coasting momentum phase (0 < t_lost <= 400ms)
        # Decays last commanded angular velocity by coast_factor without PID phantom windup
        if is_coasting and coast_factor > 0.0:
            delta_pan = self._last_delta_pan * coast_factor
            delta_tilt = self._last_delta_tilt * coast_factor

            max_slew_deg = self.MAX_SLEW_RATE_DEG_S * dt
            delta_pan = max(-max_slew_deg, min(max_slew_deg, delta_pan))
            delta_tilt = max(-max_slew_deg, min(max_slew_deg, delta_tilt))

            new_pan = max(self.PAN_MIN, min(self.PAN_MAX, self.current_pan + delta_pan))
            new_tilt = max(self.TILT_MIN, min(self.TILT_MAX, self.current_tilt - delta_tilt))
            self.current_pan = new_pan
            self.current_tilt = new_tilt

            should_dispatch = self._evaluate_rate_limit(now) if (abs(delta_pan) > 0.05 or abs(delta_tilt) > 0.05) else False

            return TrackingControlOutput(
                pan_angle=self.current_pan,
                tilt_angle=self.current_tilt,
                delta_pan=delta_pan,
                delta_tilt=delta_tilt,
                raw_error_x=0.0,
                raw_error_y=0.0,
                filtered_error_x=0.0,
                filtered_error_y=0.0,
                in_deadband_x=False,
                in_deadband_y=False,
                is_settled=False,
                should_dispatch_command=should_dispatch,
            )

        # Case 3: No target present (holding or idle)
        # CRITICAL: Do NOT spam commands at 20 Hz when system is idle!
        if target_centroid is None or coast_factor <= 0.0:
            self._last_delta_pan = 0.0
            self._last_delta_tilt = 0.0
            return TrackingControlOutput(
                pan_angle=self.current_pan,
                tilt_angle=self.current_tilt,
                delta_pan=0.0,
                delta_tilt=0.0,
                raw_error_x=0.0,
                raw_error_y=0.0,
                filtered_error_x=0.0,
                filtered_error_y=0.0,
                in_deadband_x=self.db_x.in_deadband,
                in_deadband_y=self.db_y.in_deadband,
                is_settled=True,
                should_dispatch_command=False,
            )

        cx, cy = target_centroid

        # 1. Raw error vectors relative to frame center (320, 240)
        raw_err_x = cx - self.optical_center_x
        raw_err_y = cy - self.optical_center_y

        # 2. Hysteresis deadband filtering
        db_err_x, in_db_x = self.db_x.filter(raw_err_x)
        db_err_y, in_db_y = self.db_y.filter(raw_err_y)

        # 3. EMA low-pass filtering (alpha = 0.35)
        filt_err_x = self.ema_x.filter(db_err_x)
        filt_err_y = self.ema_y.filter(db_err_y)

        is_settled = in_db_x and in_db_y

        # 4. PID calculation
        delta_pan = self.pid_pan.update(filt_err_x, dt, is_settled=in_db_x)
        delta_tilt = self.pid_tilt.update(filt_err_y, dt, is_settled=in_db_y)

        # Axis Inversion Toggles
        if self.invert_pan:
            delta_pan = -delta_pan
        if self.invert_tilt:
            delta_tilt = -delta_tilt

        # 5. Slew rate limiting: max 80 deg/s
        max_slew_deg = self.MAX_SLEW_RATE_DEG_S * dt
        delta_pan = max(-max_slew_deg, min(max_slew_deg, delta_pan))
        delta_tilt = max(-max_slew_deg, min(max_slew_deg, delta_tilt))

        self._last_delta_pan = delta_pan
        self._last_delta_tilt = delta_tilt

        # 6. Apply delta to current servo angles
        new_pan = self.current_pan + delta_pan
        new_tilt = self.current_tilt - delta_tilt

        # Physical boundary clamping
        clamped_pan = max(self.PAN_MIN, min(self.PAN_MAX, new_pan))
        clamped_tilt = max(self.TILT_MIN, min(self.TILT_MAX, new_tilt))

        self.current_pan = clamped_pan
        self.current_tilt = clamped_tilt

        # 7. 20 Hz output command rate limiting and deadband suppression
        if is_settled:
            if not self._was_settled:
                # Entering deadband: dispatch one final stop command to park servos
                self._was_settled = True
                should_dispatch = self._evaluate_rate_limit(now)
            else:
                # Already settled in deadband: suppress commands to avoid bus traffic & buzzing
                should_dispatch = False
        else:
            self._was_settled = False
            should_dispatch = self._evaluate_rate_limit(now)

        return TrackingControlOutput(
            pan_angle=self.current_pan,
            tilt_angle=self.current_tilt,
            delta_pan=delta_pan,
            delta_tilt=delta_tilt,
            raw_error_x=raw_err_x,
            raw_error_y=raw_err_y,
            filtered_error_x=filt_err_x,
            filtered_error_y=filt_err_y,
            in_deadband_x=in_db_x,
            in_deadband_y=in_db_y,
            is_settled=is_settled,
            should_dispatch_command=should_dispatch,
        )

    def _evaluate_rate_limit(self, now: float) -> bool:
        """Determines if enough time has passed to dispatch a 20 Hz movement command."""
        if now - self._last_command_time >= self.MIN_COMMAND_INTERVAL_S:
            self._last_command_time = now
            return True
        return False
