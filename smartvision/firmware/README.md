# SmartVision Embedded Firmware Subsystem

## Overview
The SmartVision firmware subsystem targets the **ESP32-S3 N16R8** microcontroller (16 MB Flash, 8 MB Octal PSRAM) running under the PlatformIO / Arduino-ESP32 framework. It provides deterministic, low-jitter 50 Hz PWM control to a PCA9685 driver, non-blocking ultrasonic rangefinding, PIR motion detection with thermal stabilization window management, transistor-switched active buzzer alert patterns, and formatted JSON telemetry reporting conforming to `docs/protocol.md`.

## Hardware Interfaces & Pin Allocation
- **HC-SR04 Ultrasonic Trigger:** GPIO 4 (3.3V CMOS push-pull, 10 µs pulse)
- **HC-SR04 Ultrasonic Echo:** GPIO 5 (Safe stepped-down logic via 1kΩ / 2kΩ passive voltage divider to 3.33V)
- **HC-SR501 PIR Motion Sensor:** GPIO 6 (Digital input with internal pull-down, native 3.3V logic, 30s boot stabilization)
- **Active Buzzer:** GPIO 7 (Driven via 2N2222 NPN transistor switch with 1N4148 inductive flyback diode)
- **PCA9685 I2C SDA:** GPIO 8 (Open-drain, 4.7kΩ pull-up to 3.3V)
- **PCA9685 I2C SCL:** GPIO 9 (Open-drain, 4.7kΩ pull-up to 3.3V)
- **Status LED:** GPIO 10 (Push-pull via 330Ω series resistor)
- **PCA9685 Hardware OE:** GPIO 12 (Active-LOW Output Enable / Emergency kill-switch)

> [!CAUTION] **Silicon Constraint Warning:** GPIO 33, 34, 35, 36, and 37 are internally bonded to the ESP32-S3 Octal PSRAM die. Never allocate or connect these pins.

---

## Calibrated Servo Limits (50 Hz PWM, 4096 Ticks)
- **PWM Frequency:** 50 Hz ($20,000\ \mu\text{s}$ period, $4.8828\ \mu\text{s}$ per tick).
- **PCA9685 Prescaler:** $121$ (`0x79`), derived from $\text{round}(25000000 / (4096 \times 50)) - 1$.
- **Pan Servo (MG996R, Ch 0):**
  - Min Limit: $15.0^\circ$ ($137$ ticks / $\approx 667\ \mu\text{s}$)
  - Neutral Center: $90.0^\circ$ ($307$ ticks / $\approx 1500\ \mu\text{s}$)
  - Max Limit: $165.0^\circ$ ($478$ ticks / $\approx 2333\ \mu\text{s}$)
- **Tilt Servo (MG90S, Ch 1):**
  - Min Limit (Down): $60.0^\circ$ ($239$ ticks / $\approx 1167\ \mu\text{s}$)
  - Neutral Center: $90.0^\circ$ ($307$ ticks / $\approx 1500\ \mu\text{s}$)
  - Max Limit (Up): $135.0^\circ$ ($410$ ticks / $\approx 2000\ \mu\text{s}$)

---

## Directory Structure
```
firmware/
├── platformio.ini              # Multi-target configuration (DevKitC-1 N8/N16)
├── include/
│   ├── hardware_config.h       # Pinout, addresses, bounds, sensor thresholds, and math formulas
│   ├── buzzer_driver.h         # Non-blocking Active Buzzer pattern state machine (Beep, Chirp, Alarm, Pulse, Mute)
│   ├── hcsr04_driver.h         # Non-blocking, timeout-safe HC-SR04 ultrasonic distance driver
│   ├── hcsr501_driver.h        # HC-SR501 PIR driver with boot warm-up window management
│   └── pca9685_driver.h        # Zero-dependency, lightweight I2C PCA9685 driver (Wire-based)
├── src/
│   ├── sensor_suite.cpp        # Phase 2: Master Interactive Sensor Verification Suite
│   ├── main.cpp                # Phase 1: Master Interactive Hardware Verification Suite
│   └── standalone/             # Standalone, isolated test sketches
│       ├── 01_i2c_scanner.cpp       # Test 1: I2C scan & PCA9685 register audit
│       ├── 02_mg996r_pan_test.cpp   # Test 2: MG996R independent sweep test
│       ├── 03_mg90s_tilt_test.cpp   # Test 3: MG90S independent sweep test
│       ├── 04_buzzer_test.cpp       # Test 4: Active buzzer pattern verification
│       ├── 05_ultrasonic_test.cpp   # Test 5: HC-SR04 non-blocking distance test
│       └── 06_pir_test.cpp          # Test 6: HC-SR501 PIR motion & stabilization test
└── standalone_tests/           # Flat source copies for direct Arduino IDE compilation
```

---

## How to Build, Flash, and Monitor

### Prerequisites
- PlatformIO Core (`pio`) installed and available in PATH.
- ESP32-S3 connected via USB-C (COM port detected).

---

### Phase 3: Production Modular Firmware Target (`smartvision_firmware`)

The production Phase 3 modular firmware integrates all peripherals under FreeRTOS dual-core concurrency, Wi-Fi auto-reconnect with exponential backoff, WebSocket client (`/ws/device`), 800ms communication watchdog, safe-stop supervisor, and 10 Hz telemetry streaming:

```bash
# Build Phase 3 production firmware
pio run -e smartvision_firmware

# Flash to ESP32-S3
pio run -e smartvision_firmware -t upload

# Open Serial Monitor (115200 baud)
pio device monitor -b 115200

# Run automated WebSocket & protocol mock server test
cd ..
py tests/test_firmware_mock_server.py
```

---

### Phase 2: Sensor Verification Targets

#### 1. Master Sensor Diagnostic Suite (`sensor_suite`)
Combines ultrasonic, PIR, buzzer, and telemetry streaming into an interactive menu:
```bash
# Build
pio run -e sensor_suite

# Flash to ESP32-S3
pio run -e sensor_suite -t upload

# Open Serial Monitor (115200 baud)
pio device monitor -b 115200
```

#### 2. Standalone Sensor Tests
```bash
# Test 4: Active Buzzer Driver (Beep, Chirp, Alarm, Pulse, Mute)
pio run -e test_04_buzzer -t upload
pio device monitor -b 115200

# Test 5: HC-SR04 Ultrasonic Rangefinder (10 Hz distance sampling & limits)
pio run -e test_05_ultrasonic -t upload
pio device monitor -b 115200

# Test 6: HC-SR501 PIR Motion Sensor (30s stabilization countdown & trigger log)
pio run -e test_06_pir -t upload
pio device monitor -b 115200
```

---

### Phase 1: Hardware & Servo Verification Targets

```bash
# Master Hardware Verification Suite (PCA9685 & Servos)
pio run -e hardware_suite -t upload

# Standalone Test 1: I2C Bus Enumeration (PCA9685 at 0x40)
pio run -e test_01_i2c_scan -t upload

# Standalone Test 2: TowerPro MG996R Pan Servo Independent Test (Ch 0)
pio run -e test_02_mg996r_pan -t upload

# Standalone Test 3: TowerPro MG90S Tilt Servo Independent Test (Ch 1)
pio run -e test_03_mg90s_tilt -t upload
```

---

## Detailed Integration & Verification Guides
- **Phase 2 Sensor Integration Guide:** [docs/sensor_integration_guide.md](../docs/sensor_integration_guide.md)
- **Phase 1 Hardware Verification Guide:** [docs/hardware_verification_guide.md](../docs/hardware_verification_guide.md)
- **Communication Protocol Specification:** [docs/protocol.md](../docs/protocol.md)
- **Automated Sensor Tests:** `py tests/test_sensor_integration.py`
