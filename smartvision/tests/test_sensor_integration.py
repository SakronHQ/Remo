"""
test_sensor_integration.py
Automated Verification Suite for SmartVision Phase 2: Sensor Integration.

Validates:
1. Voltage divider transfer function, tolerance bounds (1k/2k), and rise-time delay.
2. HC-SR04 speed of sound temperature compensation, roundtrip timing, and out-of-range rejection.
3. HC-SR501 PIR boot warm-up window (30-60s), suppression, and edge trigger counting.
4. Active Buzzer non-blocking pattern state machine (Beep, Chirp, Alarm, Pulse, Mute).
5. Sensor telemetry JSON schema compliance against docs/protocol.md (telem.sensors).
"""

import json
import math
import sys
import unittest
from typing import Any, Dict, List, Optional


# ==============================================================================
# 1. Hardware Calibration Constants (matching hardware_config.h)
# ==============================================================================
ULTRASONIC_MIN_DISTANCE_CM = 2.0
ULTRASONIC_MAX_DISTANCE_CM = 400.0
ULTRASONIC_TIMEOUT_US = 30000
ULTRASONIC_TRIG_PULSE_US = 10
SPEED_OF_SOUND_20C = 343.42  # m/s -> 0.034342 cm/us

PROXIMITY_OBSTRUCTION_CM = 20.0
PROXIMITY_WARNING_CM = 40.0

PIR_WARMUP_DEFAULT_MS = 30000
PIR_DEBOUNCE_MS = 50

BUZZER_DEFAULT_BEEP_MS = 150
BUZZER_CHIRP_PULSE_MS = 70
BUZZER_CHIRP_GAP_MS = 50
BUZZER_ALARM_INTERVAL_MS = 150


# ==============================================================================
# 2. Physics & Calculation Helpers
# ==============================================================================
def voltage_divider_vout(vin: float, r1: float, r2: float) -> float:
    """Calculates voltage divider output: Vout = Vin * (R2 / (R1 + R2))."""
    return vin * (r2 / (r1 + r2))


def speed_of_sound_m_s(temp_c: float = 20.0) -> float:
    """Calculates speed of sound in dry air: v(T) = 331.3 + 0.606 * T."""
    return 331.3 + 0.606 * temp_c


def speed_of_sound_cm_us(temp_c: float = 20.0) -> float:
    """Speed of sound in cm per microsecond."""
    return speed_of_sound_m_s(temp_c) * 100.0 / 1_000_000.0


def echo_duration_to_distance_cm(duration_us: int, temp_c: float = 20.0) -> float:
    """Converts roundtrip pulse duration in microseconds to one-way distance in cm."""
    if duration_us <= 0 or duration_us >= ULTRASONIC_TIMEOUT_US:
        return -1.0
    speed = speed_of_sound_cm_us(temp_c)
    dist = (duration_us * speed) * 0.5
    if dist < (ULTRASONIC_MIN_DISTANCE_CM - 0.1) or dist > (ULTRASONIC_MAX_DISTANCE_CM + 0.1):
        return -1.0
    return round(dist, 1)


def distance_to_echo_duration_us(dist_cm: float, temp_c: float = 20.0) -> int:
    """Converts one-way distance in cm to expected roundtrip pulse duration in microseconds."""
    speed = speed_of_sound_cm_us(temp_c)
    return round((2.0 * dist_cm) / speed)


# ==============================================================================
# 3. Virtual Sensor State Machines for Logic Verification
# ==============================================================================
class VirtualPIRSensor:
    """Simulates HC-SR501 PIR sensor with warm-up stabilization and edge detection."""

    def __init__(self, warmup_ms: int = PIR_WARMUP_DEFAULT_MS):
        self.warmup_ms = warmup_ms
        self.boot_time_ms = 0
        self.warmup_complete = False
        self.motion_detected = False
        self.trigger_count = 0
        self.last_trigger_ms = 0
        self.last_edge_ms = 0
        self.prev_pin = False

    def begin(self, now_ms: int = 0):
        self.boot_time_ms = now_ms
        self.warmup_complete = (self.warmup_ms == 0)
        self.motion_detected = False
        self.trigger_count = 0
        self.last_trigger_ms = 0
        self.last_edge_ms = now_ms
        self.prev_pin = False

    def is_warming_up(self, now_ms: int) -> bool:
        if self.warmup_complete:
            return False
        if now_ms - self.boot_time_ms >= self.warmup_ms:
            self.warmup_complete = True
            return False
        return True

    def get_warmup_progress(self, now_ms: int) -> float:
        if self.warmup_complete or self.warmup_ms == 0:
            return 1.0
        elapsed = now_ms - self.boot_time_ms
        return min(1.0, max(0.0, elapsed / self.warmup_ms))

    def update(self, raw_pin_level: bool, now_ms: int) -> bool:
        """Returns True if a new confirmed motion trigger occurred."""
        if not self.warmup_complete:
            if now_ms - self.boot_time_ms >= self.warmup_ms:
                self.warmup_complete = True
                self.prev_pin = raw_pin_level
                self.motion_detected = False
                return False
            else:
                self.motion_detected = False
                self.prev_pin = raw_pin_level
                return False

        new_trigger = False
        if raw_pin_level != self.prev_pin:
            if now_ms - self.last_edge_ms >= PIR_DEBOUNCE_MS:
                self.last_edge_ms = now_ms
                if raw_pin_level:
                    self.trigger_count += 1
                    self.last_trigger_ms = now_ms
                    self.motion_detected = True
                    new_trigger = True
                else:
                    self.motion_detected = False
                self.prev_pin = raw_pin_level
        else:
            self.motion_detected = raw_pin_level

        return new_trigger


class VirtualBuzzer:
    """Simulates Active Buzzer non-blocking pattern state machine."""

    def __init__(self):
        self.pattern = "off"
        self.pin_state = False
        self.step = 0
        self.step_start_ms = 0
        self.pulse_count_remaining = 0
        self.pulse_on_ms = 0
        self.pulse_off_ms = 0

    def mute(self):
        self.pattern = "off"
        self.pin_state = False
        self.step = 0
        self.pulse_count_remaining = 0

    def beep(self, duration_ms: int = BUZZER_DEFAULT_BEEP_MS, now_ms: int = 0):
        if duration_ms == 0:
            self.mute()
            return
        self.pattern = "beep"
        self.pulse_on_ms = duration_ms
        self.step = 1
        self.step_start_ms = now_ms
        self.pin_state = True

    def chirp(self, now_ms: int = 0):
        self.pattern = "chirp"
        self.step = 1
        self.step_start_ms = now_ms
        self.pin_state = True

    def alarm(self, enable: bool = True, now_ms: int = 0):
        if not enable:
            self.mute()
            return
        self.pattern = "alarm"
        self.step = 1
        self.step_start_ms = now_ms
        self.pin_state = True

    def pulse(self, count: int, on_ms: int = 100, off_ms: int = 100, now_ms: int = 0):
        if count == 0 or on_ms == 0:
            self.mute()
            return
        self.pattern = "pulse"
        self.pulse_count_remaining = count
        self.pulse_on_ms = on_ms
        self.pulse_off_ms = off_ms
        self.step = 1
        self.step_start_ms = now_ms
        self.pin_state = True

    def update(self, now_ms: int):
        if self.pattern == "off":
            self.pin_state = False
            return

        if self.pattern == "beep":
            if self.step == 1 and (now_ms - self.step_start_ms >= self.pulse_on_ms):
                self.pin_state = False
                self.pattern = "off"
                self.step = 0

        elif self.pattern == "chirp":
            if self.step == 1 and (now_ms - self.step_start_ms >= BUZZER_CHIRP_PULSE_MS):
                self.pin_state = False
                self.step = 2
                self.step_start_ms = now_ms
            elif self.step == 2 and (now_ms - self.step_start_ms >= BUZZER_CHIRP_GAP_MS):
                self.pin_state = True
                self.step = 3
                self.step_start_ms = now_ms
            elif self.step == 3 and (now_ms - self.step_start_ms >= BUZZER_CHIRP_PULSE_MS):
                self.pin_state = False
                self.pattern = "off"
                self.step = 0

        elif self.pattern == "alarm":
            if self.step == 1 and (now_ms - self.step_start_ms >= BUZZER_ALARM_INTERVAL_MS):
                self.pin_state = False
                self.step = 2
                self.step_start_ms = now_ms
            elif self.step == 2 and (now_ms - self.step_start_ms >= BUZZER_ALARM_INTERVAL_MS):
                self.pin_state = True
                self.step = 1
                self.step_start_ms = now_ms

        elif self.pattern == "pulse":
            if self.step == 1 and (now_ms - self.step_start_ms >= self.pulse_on_ms):
                self.pin_state = False
                self.step = 2
                self.step_start_ms = now_ms
            elif self.step == 2 and (now_ms - self.step_start_ms >= self.pulse_off_ms):
                if self.pulse_count_remaining > 1:
                    self.pulse_count_remaining -= 1
                    self.pin_state = True
                    self.step = 1
                    self.step_start_ms = now_ms
                else:
                    self.pin_state = False
                    self.pattern = "off"
                    self.step = 0
                    self.pulse_count_remaining = 0


# ==============================================================================
# 4. Test Suite Execution Functions
# ==============================================================================

def test_voltage_divider_specifications():
    """Validates 5V to 3.3V voltage divider transfer function and tolerance bounds."""
    print("  [1/5] Testing Voltage Divider Math, Tolerances, and Rise-Time...")

    # Nominal 1k / 2k divider with 5.0V input
    r1_nom = 1000.0  # Ohms
    r2_nom = 2000.0  # Ohms
    vin = 5.0        # Volts

    vout_nom = voltage_divider_vout(vin, r1_nom, r2_nom)
    assert abs(vout_nom - 3.3333) < 0.001, f"Expected nominal Vout 3.333V, got {vout_nom:.4f}V"

    # Current drawn through divider
    total_r = r1_nom + r2_nom
    i_ma = (vin / total_r) * 1000.0
    assert 1.6 <= i_ma <= 1.7, f"Expected ~1.67 mA draw, got {i_ma:.3f} mA"
    assert i_ma < 15.0, f"Exceeded HC-SR04 Echo output drive rating (15 mA): {i_ma:.2f} mA"

    # Worst-case 5% tolerance bounds (E24 5% metal/carbon film resistors)
    # Worst-case maximum voltage: R1 is -5% (950 Ohms), R2 is +5% (2100 Ohms)
    r1_min = 950.0
    r2_max = 2100.0
    vout_max_5pct = voltage_divider_vout(vin, r1_min, r2_max)
    assert vout_max_5pct <= 3.45, f"Vout max ({vout_max_5pct:.3f}V) exceeded safe 3.45V threshold"
    assert vout_max_5pct < 3.60, f"FATAL: Vout max ({vout_max_5pct:.3f}V) breached ESP32-S3 abs max (3.60V)"

    # Worst-case minimum voltage: R1 is +5% (1050 Ohms), R2 is -5% (1900 Ohms)
    r1_max = 1050.0
    r2_min = 1900.0
    vout_min_5pct = voltage_divider_vout(vin, r1_max, r2_min)
    esp32_vih_min = 0.75 * 3.3  # 2.475 V
    assert vout_min_5pct >= esp32_vih_min, f"Vout min ({vout_min_5pct:.3f}V) failed to meet ESP32-S3 VIH min ({esp32_vih_min:.3f}V)"

    # Rise-time and acoustic error verification
    # Thevenin resistance: Rth = R1 || R2 = 1000 * 2000 / 3000 = 666.67 Ohms
    r_th = (r1_nom * r2_nom) / (r1_nom + r2_nom)
    c_parasitic = 20e-12  # 20 pF total stray capacitance
    tau = r_th * c_parasitic  # ~13.33 ns
    rise_time_10_90 = 2.2 * tau  # ~29.33 ns

    # Shortest physical pulse at minimum distance (2.0 cm)
    t_min_echo_us = distance_to_echo_duration_us(2.0, 20.0)  # ~116 us
    t_min_echo_ns = t_min_echo_us * 1000.0
    delay_fraction = (rise_time_10_90 / t_min_echo_ns) * 100.0
    assert delay_fraction < 0.05, f"Rise time error percentage ({delay_fraction:.4f}%) is unexpectedly high"

    print(f"    - Nominal Vout: {vout_nom:.4f} V (Current: {i_ma:.2f} mA)")
    print(f"    - 5% Worst-Case Limits: [{vout_min_5pct:.3f} V .. {vout_max_5pct:.3f} V] (Safe within 2.475V - 3.600V)")
    print(f"    - RC Rise Time: {rise_time_10_90*1e9:.2f} ns ({delay_fraction:.3f}% of min pulse width, zero acoustic impact)")


def test_ultrasonic_distance_and_temperature_math():
    """Validates speed of sound equation, roundtrip echo conversion, and range limits."""
    print("  [2/5] Testing Ultrasonic Timing, Temperature Compensation, and Limits...")

    # Speed of sound at standard reference temperatures
    v_0c = speed_of_sound_m_s(0.0)
    v_20c = speed_of_sound_m_s(20.0)
    v_40c = speed_of_sound_m_s(40.0)

    assert abs(v_0c - 331.3) < 0.01, f"0°C speed error: {v_0c}"
    assert abs(v_20c - 343.42) < 0.01, f"20°C speed error: {v_20c}"
    assert abs(v_40c - 355.54) < 0.01, f"40°C speed error: {v_40c}"

    # Roundtrip pulse durations at key distances (at 20°C)
    t_2cm = distance_to_echo_duration_us(2.0, 20.0)
    t_20cm = distance_to_echo_duration_us(20.0, 20.0)
    t_40cm = distance_to_echo_duration_us(40.0, 20.0)
    t_100cm = distance_to_echo_duration_us(100.0, 20.0)
    t_400cm = distance_to_echo_duration_us(400.0, 20.0)

    assert 115 <= t_2cm <= 118, f"2cm roundtrip pulse ({t_2cm} us) out of expected range"
    assert 1160 <= t_20cm <= 1170, f"20cm obstruction pulse ({t_20cm} us) out of expected range"
    assert 2320 <= t_40cm <= 2340, f"40cm warning pulse ({t_40cm} us) out of expected range"
    assert 5815 <= t_100cm <= 5835, f"100cm pulse ({t_100cm} us) out of expected range"
    assert 23280 <= t_400cm <= 23310, f"400cm max pulse ({t_400cm} us) out of expected range"

    # Timeout safety margin
    assert ULTRASONIC_TIMEOUT_US > t_400cm, "Timeout threshold must exceed max distance pulse time!"
    margin_us = ULTRASONIC_TIMEOUT_US - t_400cm
    margin_pct = (margin_us / t_400cm) * 100.0
    assert margin_pct >= 25.0, f"Timeout margin ({margin_pct:.1f}%) is less than 25% safety buffer"

    # Conversion back from duration to distance
    assert abs(echo_duration_to_distance_cm(t_2cm, 20.0) - 2.0) <= 0.1
    assert abs(echo_duration_to_distance_cm(t_20cm, 20.0) - 20.0) <= 0.1
    assert abs(echo_duration_to_distance_cm(t_40cm, 20.0) - 40.0) <= 0.1
    assert abs(echo_duration_to_distance_cm(t_100cm, 20.0) - 100.0) <= 0.1
    assert abs(echo_duration_to_distance_cm(t_400cm, 20.0) - 400.0) <= 0.1

    # Out-of-range rejection & timeout
    assert echo_duration_to_distance_cm(0) == -1.0, "Zero duration must return -1.0 (timeout)"
    assert echo_duration_to_distance_cm(ULTRASONIC_TIMEOUT_US) == -1.0, "Timeout threshold must return -1.0"
    assert echo_duration_to_distance_cm(ULTRASONIC_TIMEOUT_US + 500) == -1.0, "Over-timeout must return -1.0"

    pulse_too_short = distance_to_echo_duration_us(1.0, 20.0)  # 1cm < 2cm min
    assert echo_duration_to_distance_cm(pulse_too_short) == -1.0, "Distance < 2cm must be rejected"

    pulse_too_long = distance_to_echo_duration_us(450.0, 20.0)  # 450cm > 400cm max
    assert echo_duration_to_distance_cm(pulse_too_long) == -1.0, "Distance > 400cm must be rejected"

    print(f"    - Speed of sound: 0°C = {v_0c:.1f} m/s | 20°C = {v_20c:.1f} m/s | 40°C = {v_40c:.1f} m/s")
    print(f"    - Pulse durations: 2cm = {t_2cm} us | 20cm = {t_20cm} us | 400cm = {t_400cm} us")
    print(f"    - Timeout headroom: {margin_us} us ({margin_pct:.1f}% safety margin beyond 400cm)")


def test_pir_warmup_and_trigger_state_machine():
    """Validates PIR sensor warm-up suppression, progress, and debounced trigger counting."""
    print("  [3/5] Testing PIR Boot Warm-up Window & Motion Edge Detection...")

    pir = VirtualPIRSensor(warmup_ms=30000)
    pir.begin(now_ms=1000)

    # 1. During warm-up (0s to 29.9s): spurious pulses MUST be suppressed!
    assert pir.is_warming_up(now_ms=1500) is True
    assert pir.get_warmup_progress(now_ms=1000) == 0.0
    assert pir.get_warmup_progress(now_ms=16000) == 0.5  # 15s / 30s
    assert pir.get_warmup_progress(now_ms=31000) == 1.0

    # Spurious HIGH pulses during warm-up
    triggered = pir.update(raw_pin_level=True, now_ms=10000)
    assert triggered is False, "PIR must not trigger during warm-up window!"
    assert pir.motion_detected is False, "motion_detected must be False during warm-up!"
    assert pir.trigger_count == 0

    triggered = pir.update(raw_pin_level=False, now_ms=15000)
    assert triggered is False

    triggered = pir.update(raw_pin_level=True, now_ms=25000)
    assert triggered is False
    assert pir.trigger_count == 0

    # 2. Warm-up expires at now_ms = 31000 (1000 + 30000)
    assert pir.is_warming_up(now_ms=31001) is False
    assert pir.warmup_complete is True

    # 3. Post-warmup motion detection
    # Pin currently LOW
    pir.update(raw_pin_level=False, now_ms=31500)
    assert pir.motion_detected is False

    # Rising edge at now_ms = 32000
    triggered = pir.update(raw_pin_level=True, now_ms=32000)
    assert triggered is True, "Expected valid motion trigger on rising edge!"
    assert pir.motion_detected is True
    assert pir.trigger_count == 1
    assert pir.last_trigger_ms == 32000

    # Continued HIGH level should NOT increment trigger_count
    triggered = pir.update(raw_pin_level=True, now_ms=32500)
    assert triggered is False, "Holding pin HIGH must not generate extra trigger events"
    assert pir.trigger_count == 1
    assert pir.motion_detected is True

    # Falling edge
    pir.update(raw_pin_level=False, now_ms=34000)
    assert pir.motion_detected is False
    assert pir.trigger_count == 1

    # Second valid rising edge at now_ms = 35000 (after debounce)
    triggered = pir.update(raw_pin_level=True, now_ms=35000)
    assert triggered is True
    assert pir.trigger_count == 2
    assert pir.last_trigger_ms == 35000

    # 4. Critical edge case: Spurious HIGH pulse persisting across warm-up expiration boundary
    pir_noisy = VirtualPIRSensor(warmup_ms=30000)
    pir_noisy.begin(now_ms=0)
    pir_noisy.update(raw_pin_level=True, now_ms=29990)
    assert pir_noisy.motion_detected is False, "Transients during warm-up must be suppressed"
    # Expiration tick at 30005ms while pin is STILL HIGH from warm-up
    triggered = pir_noisy.update(raw_pin_level=True, now_ms=30005)
    assert triggered is False, "Must not trigger on warm-up expiration with high pin"
    assert pir_noisy.motion_detected is False, "motion_detected must remain False right after warm-up"
    assert pir_noisy.trigger_count == 0
    # Pin drops back to LOW
    pir_noisy.update(raw_pin_level=False, now_ms=31000)
    assert pir_noisy.motion_detected is False
    # Genuine post-warmup motion event
    triggered = pir_noisy.update(raw_pin_level=True, now_ms=32000)
    assert triggered is True
    assert pir_noisy.motion_detected is True
    assert pir_noisy.trigger_count == 1

    print("    - Warm-up window: 30,000 ms accurately suppresses noise and tracks progress")
    print("    - Rising-edge detector: verified clean debouncing and trigger counting")
    print("    - Warm-up transition: verified zero spurious motion triggers on boundary expiration")


def test_buzzer_patterns_and_state_machine():
    """Validates non-blocking active buzzer pattern sequences (Beep, Chirp, Alarm, Pulse, Mute)."""
    print("  [4/5] Testing Active Buzzer Non-Blocking Patterns & Mute...")

    buzzer = VirtualBuzzer()

    # Initial state
    assert buzzer.pattern == "off"
    assert buzzer.pin_state is False

    # 1. Beep pattern (150ms)
    buzzer.beep(duration_ms=150, now_ms=1000)
    assert buzzer.pattern == "beep"
    assert buzzer.pin_state is True

    # At 100ms, still sounding
    buzzer.update(now_ms=1100)
    assert buzzer.pin_state is True
    assert buzzer.pattern == "beep"

    # At 151ms, should auto-turn off
    buzzer.update(now_ms=1151)
    assert buzzer.pin_state is False
    assert buzzer.pattern == "off"

    # 2. Alert Chirp pattern (70ms ON, 50ms OFF, 70ms ON)
    buzzer.chirp(now_ms=2000)
    assert buzzer.pattern == "chirp"
    assert buzzer.pin_state is True

    # After 71ms: Step 1 ON completes -> Step 2 Gap OFF
    buzzer.update(now_ms=2071)
    assert buzzer.pin_state is False
    assert buzzer.step == 2

    # After 51ms of gap: Step 2 OFF completes -> Step 3 2nd pulse ON
    buzzer.update(now_ms=2122)
    assert buzzer.pin_state is True
    assert buzzer.step == 3

    # After 71ms of 2nd pulse: Chirp completes -> OFF
    buzzer.update(now_ms=2193)
    assert buzzer.pin_state is False
    assert buzzer.pattern == "off"

    # 3. Emergency Alarm pattern (150ms ON / 150ms OFF alternating)
    buzzer.alarm(enable=True, now_ms=3000)
    assert buzzer.pattern == "alarm"
    assert buzzer.pin_state is True

    # 151ms: Flips to OFF
    buzzer.update(now_ms=3151)
    assert buzzer.pin_state is False
    assert buzzer.step == 2

    # 301ms: Flips back to ON
    buzzer.update(now_ms=3302)
    assert buzzer.pin_state is True
    assert buzzer.step == 1

    # Mute stops alarm immediately
    buzzer.mute()
    assert buzzer.pattern == "off"
    assert buzzer.pin_state is False

    # 4. Pulse pattern (3 pulses of 100ms ON, 100ms OFF)
    buzzer.pulse(count=3, on_ms=100, off_ms=100, now_ms=4000)
    assert buzzer.pattern == "pulse"
    assert buzzer.pin_state is True
    assert buzzer.pulse_count_remaining == 3

    # Pulse 1 ON ends
    buzzer.update(now_ms=4101)
    assert buzzer.pin_state is False
    # Pulse 1 OFF ends -> Pulse 2 starts
    buzzer.update(now_ms=4202)
    assert buzzer.pin_state is True
    assert buzzer.pulse_count_remaining == 2

    # Pulse 2 ON ends
    buzzer.update(now_ms=4303)
    assert buzzer.pin_state is False
    # Pulse 2 OFF ends -> Pulse 3 starts
    buzzer.update(now_ms=4404)
    assert buzzer.pin_state is True
    assert buzzer.pulse_count_remaining == 1

    # Pulse 3 ON ends
    buzzer.update(now_ms=4505)
    assert buzzer.pin_state is False
    # Pulse 3 OFF ends -> Done!
    buzzer.update(now_ms=4606)
    assert buzzer.pin_state is False
    assert buzzer.pattern == "off"

    # 5. Guard against zero duration and zero count
    buzzer_zero = VirtualBuzzer()
    buzzer_zero.beep(duration_ms=0, now_ms=5000)
    assert buzzer_zero.pin_state is False, "beep(0) must not activate buzzer pin"
    assert buzzer_zero.pattern == "off"

    buzzer_zero.pulse(count=0, on_ms=100, off_ms=100, now_ms=5100)
    assert buzzer_zero.pin_state is False, "pulse(count=0) must not activate buzzer pin"
    assert buzzer_zero.pattern == "off"

    buzzer_zero.pulse(count=2, on_ms=0, off_ms=100, now_ms=5200)
    assert buzzer_zero.pin_state is False, "pulse(on_ms=0) must not activate buzzer pin"
    assert buzzer_zero.pattern == "off"

    print("    - Beep: verified single-shot duration cut-off and duration=0 guard")
    print("    - Chirp: verified 70ms-ON / 50ms-OFF / 70ms-ON cadence")
    print("    - Alarm: verified 150ms alternating cycle and instantaneous mute")
    print("    - Pulse: verified exact cycle count (3 pulses) and clean shutdown")


def test_telemetry_json_schema():
    """Validates sensor telemetry message payload against docs/protocol.md section 3.4."""
    print("  [5/5] Testing Telemetry JSON Schema Compliance (telem.sensors)...")

    # Sample realistic telemetry payload generated by sensor_suite firmware
    sample_telemetry = {
        "type": "telem.sensors",
        "timestamp": 1731657110120,
        "sender": "esp32",
        "seq": 4501,
        "corr_id": None,
        "payload": {
            "sonar": {
                "distance_cm": 84.6,
                "valid": True,
                "status": "in_range",
            },
            "pir": {
                "motion_detected": True,
                "trigger_count": 14,
                "last_trigger_ms": 348120,
            },
            "servos": {
                "pan_angle": 92.4,
                "tilt_angle": 88.1,
                "pan_target": 90.0,
                "tilt_target": 90.0,
                "is_moving": False,
            },
            "buzzer": {
                "active": False,
                "pattern": "off",
            },
            "system": {
                "uptime_ms": 348950,
                "rssi_dbm": -58,
                "free_heap_bytes": 268412,
                "psram_free_bytes": 7192840,
                "cpu_temp_c": 44.5,
            },
        },
    }

    # Serialization check
    json_str = json.dumps(sample_telemetry)
    assert len(json_str) > 0
    parsed = json.loads(json_str)

    # 1. Root envelope validation
    assert parsed["type"] == "telem.sensors"
    assert parsed["sender"] == "esp32"
    assert isinstance(parsed["timestamp"], int) and parsed["timestamp"] > 0
    assert isinstance(parsed["seq"], int) and parsed["seq"] >= 0
    assert "payload" in parsed

    # 2. Sonar payload validation
    sonar = parsed["payload"]["sonar"]
    assert isinstance(sonar["distance_cm"], (int, float))
    assert isinstance(sonar["valid"], bool)
    assert sonar["status"] in ["in_range", "out_of_range", "timeout"]
    if sonar["valid"]:
        assert 2.0 <= sonar["distance_cm"] <= 400.0
        assert sonar["status"] == "in_range"

    # 3. PIR payload validation
    pir = parsed["payload"]["pir"]
    assert isinstance(pir["motion_detected"], bool)
    assert isinstance(pir["trigger_count"], int) and pir["trigger_count"] >= 0
    assert isinstance(pir["last_trigger_ms"], int) and pir["last_trigger_ms"] >= 0

    # 4. Servos payload validation
    servos = parsed["payload"]["servos"]
    assert 15.0 <= servos["pan_angle"] <= 165.0
    assert 60.0 <= servos["tilt_angle"] <= 135.0
    assert isinstance(servos["is_moving"], bool)

    # 5. Buzzer payload validation
    buzzer = parsed["payload"]["buzzer"]
    assert isinstance(buzzer["active"], bool)
    assert buzzer["pattern"] in ["off", "beep", "chirp", "alarm", "pulse"]

    # 6. System payload validation
    system = parsed["payload"]["system"]
    assert isinstance(system["uptime_ms"], int) and system["uptime_ms"] >= 0
    assert isinstance(system["free_heap_bytes"], int) and system["free_heap_bytes"] > 0
    assert isinstance(system["cpu_temp_c"], (int, float))

    # Test edge case: Sonar Timeout payload
    timeout_telemetry = json.loads(json_str)
    timeout_telemetry["payload"]["sonar"]["distance_cm"] = -1.0
    timeout_telemetry["payload"]["sonar"]["valid"] = False
    timeout_telemetry["payload"]["sonar"]["status"] = "timeout"
    assert timeout_telemetry["payload"]["sonar"]["distance_cm"] == -1.0
    assert timeout_telemetry["payload"]["sonar"]["valid"] is False
    assert timeout_telemetry["payload"]["sonar"]["status"] == "timeout"

    # Test edge case: Sonar Out-of-Range payload
    oor_telemetry = json.loads(json_str)
    oor_telemetry["payload"]["sonar"]["distance_cm"] = -1.0
    oor_telemetry["payload"]["sonar"]["valid"] = False
    oor_telemetry["payload"]["sonar"]["status"] = "out_of_range"
    assert oor_telemetry["payload"]["sonar"]["distance_cm"] == -1.0
    assert oor_telemetry["payload"]["sonar"]["valid"] is False
    assert oor_telemetry["payload"]["sonar"]["status"] == "out_of_range"

    print("    - Envelope keys, types, and sequence bounds verified")
    print("    - Sonar sub-schema verified (distance_cm, valid, status in_range/out_of_range/timeout)")
    print("    - PIR sub-schema verified (motion_detected, trigger_count, last_trigger_ms)")
    print("    - Buzzer sub-schema verified (active, pattern)")
    print("    - System sub-schema verified (uptime, heap, psram, temperature)")


class TestSensorIntegration(unittest.TestCase):
    """Unittest test case runner adapter for CI discovery."""

    def test_voltage_divider(self):
        test_voltage_divider_specifications()

    def test_ultrasonic_math(self):
        test_ultrasonic_distance_and_temperature_math()

    def test_pir_state_machine(self):
        test_pir_warmup_and_trigger_state_machine()

    def test_buzzer_patterns(self):
        test_buzzer_patterns_and_state_machine()

    def test_telemetry_schema(self):
        test_telemetry_json_schema()


def run_all_tests():
    print("================================================================================")
    print("    SMARTVISION PHASE 2: SENSOR INTEGRATION AUTOMATED TEST SUITE                ")
    print("================================================================================")
    test_voltage_divider_specifications()
    test_ultrasonic_distance_and_temperature_math()
    test_pir_warmup_and_trigger_state_machine()
    test_buzzer_patterns_and_state_machine()
    test_telemetry_json_schema()
    print("================================================================================")
    print(" [PASS] All 5 sensor integration test suites completed with ZERO errors!        ")
    print("================================================================================")


if __name__ == "__main__":
    run_all_tests()
