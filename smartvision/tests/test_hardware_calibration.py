"""
test_hardware_calibration.py
Validates hardware calibration math, tick conversions, clamping bounds,
and power budget margins for SmartVision Phase 1.
"""

import math
import unittest

# Constants matching hardware_config.h
PCA9685_OSC_CLOCK = 25_000_000
PCA9685_PWM_FREQ = 50
PCA9685_TOTAL_TICKS = 4096
PCA9685_PERIOD_US = 1_000_000 / PCA9685_PWM_FREQ  # 20,000 us
PCA9685_US_PER_TICK = PCA9685_PERIOD_US / PCA9685_TOTAL_TICKS  # 4.8828125 us/tick

SERVO_PULSE_MIN_US = 500.0   # 0°
SERVO_PULSE_MAX_US = 2500.0  # 180°

SERVO_PAN_MIN_DEG = 15.0
SERVO_PAN_MAX_DEG = 165.0
SERVO_PAN_CENTER_DEG = 90.0

SERVO_TILT_MIN_DEG = 60.0
SERVO_TILT_MAX_DEG = 135.0
SERVO_TILT_CENTER_DEG = 90.0


def calculate_prescale(osc_clock_hz=PCA9685_OSC_CLOCK, update_rate_hz=PCA9685_PWM_FREQ):
    return round(osc_clock_hz / (PCA9685_TOTAL_TICKS * update_rate_hz)) - 1


def clamp_pan_angle(deg: float) -> float:
    if math.isnan(deg):
        return SERVO_PAN_CENTER_DEG
    return max(SERVO_PAN_MIN_DEG, min(SERVO_PAN_MAX_DEG, deg))


def clamp_tilt_angle(deg: float) -> float:
    if math.isnan(deg):
        return SERVO_TILT_CENTER_DEG
    return max(SERVO_TILT_MIN_DEG, min(SERVO_TILT_MAX_DEG, deg))


def angle_to_ticks(deg: float) -> int:
    if math.isnan(deg):
        deg = 90.0
    pulse_us = SERVO_PULSE_MIN_US + (deg / 180.0) * (SERVO_PULSE_MAX_US - SERVO_PULSE_MIN_US)
    return round(pulse_us / PCA9685_US_PER_TICK)


def pan_angle_to_ticks(deg: float) -> int:
    return angle_to_ticks(clamp_pan_angle(deg))


def tilt_angle_to_ticks(deg: float) -> int:
    return angle_to_ticks(clamp_tilt_angle(deg))


def test_prescale_calculation():
    prescale = calculate_prescale(25_000_000, 50)
    assert prescale == 121, f"Expected prescale 121, got {prescale}"


def test_pan_clamping_and_ticks():
    # Boundary clamps
    assert clamp_pan_angle(-10.0) == 15.0
    assert clamp_pan_angle(0.0) == 15.0
    assert clamp_pan_angle(15.0) == 15.0
    assert clamp_pan_angle(90.0) == 90.0
    assert clamp_pan_angle(165.0) == 165.0
    assert clamp_pan_angle(180.0) == 165.0
    assert clamp_pan_angle(250.0) == 165.0
    assert clamp_pan_angle(float("nan")) == 90.0

    # Strict tick mappings - 90° MUST map to exactly 307 ticks (no ambiguity)
    assert pan_angle_to_ticks(15.0) == 137, f"Expected 137, got {pan_angle_to_ticks(15.0)}"
    assert pan_angle_to_ticks(90.0) == 307, f"Expected 307, got {pan_angle_to_ticks(90.0)}"
    assert pan_angle_to_ticks(165.0) == 478, f"Expected 478, got {pan_angle_to_ticks(165.0)}"

    # Pulse width calculation check (50Hz = 20,000 us, 4096 ticks -> 4.8828125 us/tick)
    center_pulse_us = pan_angle_to_ticks(90.0) * PCA9685_US_PER_TICK
    assert 1495 <= center_pulse_us <= 1505, f"Neutral pulse {center_pulse_us} us not near 1500 us"


def test_tilt_clamping_and_ticks():
    # Boundary clamps
    assert clamp_tilt_angle(0.0) == 60.0
    assert clamp_tilt_angle(45.0) == 60.0
    assert clamp_tilt_angle(60.0) == 60.0
    assert clamp_tilt_angle(90.0) == 90.0
    assert clamp_tilt_angle(135.0) == 135.0
    assert clamp_tilt_angle(170.0) == 135.0
    assert clamp_tilt_angle(float("nan")) == 90.0

    # Strict tick mappings
    assert tilt_angle_to_ticks(60.0) == 239, f"Expected 239, got {tilt_angle_to_ticks(60.0)}"
    assert tilt_angle_to_ticks(90.0) == 307, f"Expected 307, got {tilt_angle_to_ticks(90.0)}"
    assert tilt_angle_to_ticks(135.0) == 410, f"Expected 410, got {tilt_angle_to_ticks(135.0)}"

    # Pulse width calculation check
    min_pulse_us = tilt_angle_to_ticks(60.0) * PCA9685_US_PER_TICK
    max_pulse_us = tilt_angle_to_ticks(135.0) * PCA9685_US_PER_TICK
    assert 1160 <= min_pulse_us <= 1175, f"Min tilt pulse {min_pulse_us} us outside expected bounds"
    assert 1995 <= max_pulse_us <= 2010, f"Max tilt pulse {max_pulse_us} us outside expected bounds"


def test_power_budget():
    # Component breakdown (stall / peak)
    mg996r_stall = 2.50
    mg90s_stall = 0.80
    esp32_peak = 0.45
    sensors_peak = 0.02 + 0.001 + 0.04 + 0.01 + 0.005  # HC-SR04, PIR, Buzzer, PCA9685 logic, LED
    total_peak = mg996r_stall + mg90s_stall + esp32_peak + sensors_peak
    supply_rating = 5.00
    margin = supply_rating - total_peak
    margin_pct = (margin / supply_rating) * 100.0

    assert round(total_peak, 3) == 3.826
    assert round(margin, 3) == 1.174
    assert round(margin_pct, 2) == 23.48

    # Individual test phase peak currents
    test1_peak = esp32_peak + 0.01  # ESP32 + PCA9685 logic only
    assert test1_peak < 0.50, "Test 1 exceeds logic power threshold"

    test2_peak = esp32_peak + mg996r_stall + 0.01
    assert round(test2_peak, 2) == 2.96, f"Test 2 peak {test2_peak} != 2.96 A"
    assert test2_peak < supply_rating, "Test 2 exceeds supply capacity"

    test3_peak = esp32_peak + mg90s_stall + 0.01
    assert round(test3_peak, 2) == 1.26, f"Test 3 peak {test3_peak} != 1.26 A"
    assert test3_peak < supply_rating, "Test 3 exceeds supply capacity"


def test_slew_timing():
    # Slew step: 1.0 deg, 15 ms delay -> ~66.67 deg/s
    step_deg = 1.0
    delay_s = 0.015
    vel_deg_s = step_deg / delay_s
    assert round(vel_deg_s, 2) == 66.67

    # Pan travel time (15° to 165° = 150°)
    pan_travel_deg = 165.0 - 15.0
    pan_time_s = (pan_travel_deg / step_deg) * delay_s
    assert round(pan_time_s, 3) == 2.250

    # Tilt travel time (60° to 135° = 75°)
    tilt_travel_deg = 135.0 - 60.0
    tilt_time_s = (tilt_travel_deg / step_deg) * delay_s
    assert round(tilt_time_s, 3) == 1.125


class TestHardwareCalibration(unittest.TestCase):
    def test_prescale(self):
        test_prescale_calculation()

    def test_pan_clamping(self):
        test_pan_clamping_and_ticks()

    def test_tilt_clamping(self):
        test_tilt_clamping_and_ticks()

    def test_power(self):
        test_power_budget()

    def test_slew(self):
        test_slew_timing()


if __name__ == "__main__":
    test_prescale_calculation()
    test_pan_clamping_and_ticks()
    test_tilt_clamping_and_ticks()
    test_power_budget()
    test_slew_timing()
    print("[PASS] All hardware calibration, clamping math, power budget, and slew assertions passed strictly!")
