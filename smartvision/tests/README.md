# SmartVision Standalone Test & Mock Suite

## Overview
This directory contains standalone Python mock utilities and verification scripts designed to independently test the SmartVision software, control loops, and communication protocols without physical hardware.

## Files
- `requirements.txt`: Python package requirements for the mock and test scripts.
- `mock_camera_stream.py`: Emulates a USB UVC webcam by generating synthetic 640x480 RGB frames at 30 FPS. Supports sinusoidal, diagonal bounce, and intermittent occlusion trajectories.
- `mock_esp32_firmware.py`: Emulates the ESP32-S3 microcontroller, PCA9685 virtual servo angles with slew rate inertia, mechanical limit clamping, HC-SR04/PIR telemetry, and the 800ms communication watchdog.
- `mock_backend_client.py`: Simulates operator/frontend dashboard interactions, verifies message envelope construction, command rate limiting (20 Hz), and protocol boundary validation.
- `run_system_sim.py`: Automated closed-loop simulation script verifying software tracking convergence, deadband jitter suppression, and fail-safe triggers.
- `test_hardware_calibration.py`: Unit test validating PCA9685 prescaler math (121), servo tick conversions (15°->137, 90°->307, 165°->478, 60°->239, 135°->410), conservative boundary clamping, and power budget headroom margins.
- `test_sensor_integration.py`: Unit test validating Phase 2 sensor integration (voltage divider math & 5% tolerance margins, ultrasonic speed of sound temperature formulas, roundtrip pulse timing, PIR 30s warm-up window & debounced edge counting, active buzzer state machine patterns, and telemetry JSON schema compliance).
- `test_camera_system.py`: Comprehensive test suite for Phase 4 PC Camera System (device probing, capability negotiation, synthetic fallback test card, double-buffered buffer draining, zero-lag delivery, rolling FPS metrics, auto-reconnect, and MJPEG multipart boundary formatting).

## Quick Execution

### 1. Run PC Camera System Verification (Phase 4)
```bash
python tests/test_camera_system.py
```

### 2. Run Sensor Integration Verification (Phase 2)
```bash
python tests/test_sensor_integration.py
```

### 3. Run Hardware Calibration & Power Budget Verification (Phase 1)
```bash
python tests/test_hardware_calibration.py
```

### 2. Run Complete Closed-Loop System Simulation
```bash
python tests/run_system_sim.py
```

### 2. Run Mock Camera Stream Test
```bash
python tests/mock_camera_stream.py --pattern sinusoidal --fps 30 --duration 3
```

### 3. Run Mock ESP32 Firmware Standalone Verification
```bash
python tests/mock_esp32_firmware.py --mode standalone
```

### 4. Run Mock Operator Client Standalone Verification
```bash
python tests/mock_backend_client.py --mode test
```
