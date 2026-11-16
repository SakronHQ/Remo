# SmartVision Phase 1: Hardware Verification & Bench Bring-Up Guide

**Document Version:** 1.0.0  
**Phase:** 1 — Hardware Verification  
**Target Microcontroller:** ESP32-S3 N16R8 (16MB Flash, 8MB Octal PSRAM)  
**PWM Driver:** PCA9685 16-Channel 12-Bit I2C Driver (`0x40`)  
**Actuators:** TowerPro MG996R (Pan, Ch 0), TowerPro MG90S (Tilt, Ch 1)  
**Power Supply:** Regulated 5.0V DC 5.0A External Power Supply  

---

## 1. Safety Rules & Pre-Flight Checklist

> [!CAUTION] **CRITICAL HARDWARE RULES**
> 1. **NEVER POWER SERVOS FROM ESP32 5V OR 3.3V PINS:** A stalled MG996R draws 2.5A. Drawing this current through an ESP32 development board destroys the on-board linear regulator or triggers immediate silicon brownout panics.
> 2. **DO NOT CONNECT ALL COMPONENTS SIMULTANEOUSLY:** Follow the strict sequential test progression. Test the I2C bus with zero servos connected first, then test the Pan servo alone, then the Tilt servo alone, before combining them.
> 3. **INSTALL 1000 µF LOW-ESR CAPACITOR:** Solder or screw a $1000\ \mu\text{F}$ to $2200\ \mu\text{F}$ (10V/16V) electrolytic capacitor directly into the PCA9685 green screw terminal ($V+$ to capacitor positive, GND to negative).
> 4. **COMMON GROUND MANDATE:** The GND wire from the ESP32-S3, the GND screw terminal of the PCA9685, and the negative (-) lead of the 5V 5A power supply MUST be bonded together in a star topology.
> 5. **RESERVED PINS WARNING:** ESP32-S3 GPIO 33, 34, 35, 36, and 37 are internally bonded to the Octal PSRAM die. Never connect jumpers or attach components to these pins.

---

## 2. Test 1: ESP32-S3 & PCA9685 I2C Bus Enumeration

### 2.1 Test Objective
Verify ESP32-S3 core clock, heap, reset reason, I2C bus communication on GPIO 8 (SDA) and GPIO 9 (SCL), PCA9685 ACK at address `0x40`, and hardware Output Enable (`OE`) switching on GPIO 12. **All servos MUST be disconnected.**

### 2.2 Wiring Table (Test 1)

| ESP32-S3 Pin | PCA9685 Pin | Signal Type | Description |
|---|---|---|---|
| **GPIO 8** | **SDA** | 3.3V I2C Data | PCA9685 I2C Data line (pull-up internal/external) |
| **GPIO 9** | **SCL** | 3.3V I2C Clock | PCA9685 I2C Clock line |
| **GPIO 12** | **OE** | 3.3V Output | Active LOW Output Enable (LOW=enable, HIGH=tri-state) |
| **3.3V** | **VCC** | 3.3V Power | PCA9685 Logic Power (draws < 10 mA from ESP32 rail) |
| **GND** | **GND (Logic)** | Ground | Logic reference ground |

> **Note for Test 1:** The external 5V 5A supply screw terminal ($V+$) may remain off or unpopulated for this test. Only logic $V_{CC}$ (3.3V) is required.

### 2.3 Flashing & Running Test 1

#### Option A: Using PlatformIO (Recommended)
```bash
cd "d:\Project\Rana Project\smartvision\firmware"
pio run -e test_01_i2c_scan -t upload
pio device monitor -b 115200
```

#### Option B: Using Arduino CLI
```bash
# 1. Ensure ESP32 core is installed
arduino-cli core install esp32:esp32

# 2. Compile standalone Test 1
arduino-cli compile --fqbn esp32:esp32:esp32s3 --build-property build.extra_flags="-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1 -Iinclude" src/standalone/01_i2c_scanner.cpp

# 3. Flash to ESP32-S3 (replace COMx with your serial port, e.g., COM3 on Windows or /dev/ttyACM0 on Linux)
arduino-cli upload -p COMx --fqbn esp32:esp32:esp32s3 src/standalone/01_i2c_scanner.cpp

# 4. Open Serial Monitor
arduino-cli monitor -p COMx -c baudrate=115200
```

### 2.4 Expected Serial Monitor Output (Test 1)
```text
========================================================
   SMARTVISION HARDWARE TEST 01: I2C & PCA9685 VERIFICATION
========================================================
MCU: ESP32-S3 (Chip Rev: 1, Cores: 2)
CPU Frequency: 240 MHz
Flash Size: 16 MB
Free Heap: 320140 bytes
Reset Reason: 1
--------------------------------------------------------
I2C Configuration: SDA = GPIO 8, SCL = GPIO 9 (Speed: 100 kHz)
PCA9685 OE Pin:    GPIO 12 (Active LOW)
Status LED Pin:    GPIO 10
========================================================

[I2C SCAN] Starting bus enumeration (0x01 to 0x7E)...
  -> Found I2C device at 0x40  [MATCH: PCA9685 Default Address 0x40]
  -> Found I2C device at 0x70  [PCA9685 All-Call Software Address]
--------------------------------------------------------
[RESULT: PASS] PCA9685 detected at 0x40! Total devices: 2

[PCA9685 CONFIG] Reading control registers...
  MODE1    (0x00): 0x21 (Auto-Inc: YES, Sleep: NO, All-Call: YES)
  MODE2    (0x01): 0x04 (Out-Drive: Totem-Pole)
  PRESCALE (0xFE): 0x79 (121 decimal, Prescaler for ~50 Hz PWM)
[RESULT: PASS] PCA9685 registers correctly configured for 50 Hz PWM!

[OE PIN TEST] Toggling Hardware Output Enable (GPIO 12)...
  OE Pin driven LOW  -> PWM Outputs ENABLED  (GPIO 12 = 0)
  OE Pin driven HIGH -> PWM Outputs DISABLED (GPIO 12 = 1)
  OE Pin safely parked at HIGH -> Outputs TRI-STATE for wiring (GPIO 12 = 1)
[RESULT: PASS] Hardware Output Enable toggle verified!

========================================================
   PHASE 1 - TEST 01 COMPLETE: I2C SUBSYSTEM VERIFIED
========================================================
```
*(Note: MODE1 reads `0x21` after restart completes because the RESTART bit automatically clears to 0 per PCA9685 datasheet section 7.3.1.1.)*

---

## 3. Test 2: TowerPro MG996R Pan Servo Independent Verification

### 3.1 Test Objective
Verify independent operation of the heavy horizontal Pan servo (TowerPro MG996R) on Channel 0 under external 5V 5A power. Confirm smooth slew-rate-limited sweeping between certified conservative limits ($15^\circ$ to $165^\circ$) with zero brownout resets. **Tilt servo MUST be disconnected.**

### 3.2 Wiring Table (Test 2)

| Component / Lead | Connection Point | Wire Color / Gauge | Notes |
|---|---|---|---|
| **External 5V Power (+)** | PCA9685 **V+ Screw Terminal** | Red (20–22 AWG) | Direct from 5V 5A power supply |
| **External Power GND (-)** | PCA9685 **GND Screw Terminal** | Black (20–22 AWG) | Common ground star point |
| **1000 µF Electrolytic Cap** | PCA9685 Screw Terminals | (+) to V+, (-) to GND | Buffers current surges up to 2.5A |
| **ESP32 GND** | PCA9685 GND Screw Terminal | Black jumper | Common ground bonding |
| **MG996R Signal** | PCA9685 **Channel 0 PWM (Yellow)** | Orange or White | Pin closest to board interior |
| **MG996R Power (+)** | PCA9685 **Channel 0 V+ (Red)** | Red | Center pin |
| **MG996R Ground (-)** | PCA9685 **Channel 0 GND (Black)** | Brown or Black | Pin closest to board outer edge |

### 3.3 Conservative Angle Limits & Timing (Pan Axis)
- **Minimum Safe Angle:** $15.0^\circ$ (137 ticks $\approx 667\ \mu\text{s}$). Prevents chassis collision.
- **Center / Neutral:** $90.0^\circ$ (307 ticks $\approx 1500\ \mu\text{s}$). Boresight orientation.
- **Maximum Safe Angle:** $165.0^\circ$ (478 ticks $\approx 2333\ \mu\text{s}$). Prevents USB cable strain.
- **Slew Rate Limit:** $1.0^\circ$ per 15 ms step ($\approx 66.7^\circ/\text{s}$). Prevents inrush current spikes.

### 3.4 Flashing & Running Test 2

#### Option A: Using PlatformIO
```bash
cd "d:\Project\Rana Project\smartvision\firmware"
pio run -e test_02_mg996r_pan -t upload
pio device monitor -b 115200
```

#### Option B: Using Arduino CLI
```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 --build-property build.extra_flags="-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1 -Iinclude" src/standalone/02_mg996r_pan_test.cpp
arduino-cli upload -p COMx --fqbn esp32:esp32:esp32s3 src/standalone/02_mg996r_pan_test.cpp
arduino-cli monitor -p COMx -c baudrate=115200
```

### 3.5 Expected Serial Monitor Output (Test 2)
```text
========================================================
   SMARTVISION HARDWARE TEST 02: MG996R PAN SERVO (CH 0)
========================================================
Safety Constraints Enforced:
  Channel:                Channel 0
  Conservative Min Limit: 15.0 deg (Ticks: 137, ~668 us)
  Center / Neutral:       90.0 deg (Ticks: 307, ~1499 us)
  Conservative Max Limit: 165.0 deg (Ticks: 478, ~2333 us)
Power & Wiring Check:
  1. External 5V 5A supply MUST be connected to PCA9685 V+ / GND.
  2. Common GND MUST be bonded between ESP32 and PCA9685.
  3. 1000uF capacitor MUST be across V+ and GND screw terminals.
  4. Tilt servo MUST BE UNPLUGGED for this single-axis test.
========================================================

[STEP 1] Initializing Pan to Neutral Center (90.0 deg)...
[PASS] Pan servo centered. Starting verification sweep sequence.

--- Starting Pan Sweep Cycle #1 ---
Testing Pan Minimum Limit (15.0 deg):
  [SLEW] Moving Pan from 90.0 deg -> 15.0 deg... ARRIVED! (Ticks: 137, Pulse: 668 us)
  Holding at 15.0 deg for 2.0 seconds... (Check for mechanical binding or cable tension)
Returning to Center (90.0 deg):
  [SLEW] Moving Pan from 15.0 deg -> 90.0 deg... ARRIVED! (Ticks: 307, Pulse: 1499 us)
Testing Pan Maximum Limit (165.0 deg):
  [SLEW] Moving Pan from 90.0 deg -> 165.0 deg... ARRIVED! (Ticks: 478, Pulse: 2333 us)
  Holding at 165.0 deg for 2.0 seconds... (Check for mechanical binding or cable tension)
Returning to Center (90.0 deg):
  [SLEW] Moving Pan from 165.0 deg -> 90.0 deg... ARRIVED! (Ticks: 307, Pulse: 1499 us)
  Cycle Complete! Holding at center for 4 seconds.
```

---

## 4. Test 3: TowerPro MG90S Tilt Servo Independent Verification

### 4.1 Test Objective
Verify independent operation of the lightweight vertical Tilt servo (TowerPro MG90S) on Channel 1. Confirm smooth slew-rate-limited sweeping between certified conservative limits ($60^\circ$ to $135^\circ$) with zero mechanical binding against the camera gimbal frame. **Pan servo MUST be disconnected.**

### 4.2 Wiring Table (Test 3)

| Component / Lead | Connection Point | Wire Color / Gauge | Notes |
|---|---|---|---|
| **External 5V Power (+)** | PCA9685 **V+ Screw Terminal** | Red (20–22 AWG) | Direct from 5V 5A power supply |
| **External Power GND (-)** | PCA9685 **GND Screw Terminal** | Black (20–22 AWG) | Common ground star point |
| **MG90S Signal** | PCA9685 **Channel 1 PWM (Yellow)** | Orange or White | Pin closest to board interior |
| **MG90S Power (+)** | PCA9685 **Channel 1 V+ (Red)** | Red | Center pin |
| **MG90S Ground (-)** | PCA9685 **Channel 1 GND (Black)** | Brown or Black | Pin closest to board outer edge |

### 4.3 Conservative Angle Limits & Timing (Tilt Axis)
- **Minimum Safe Angle (Pitch Down):** $60.0^\circ$ (239 ticks $\approx 1167\ \mu\text{s}$). Prevents camera bracket collision.
- **Center / Level Horizon:** $90.0^\circ$ (307 ticks $\approx 1500\ \mu\text{s}$). Level camera horizon.
- **Maximum Safe Angle (Pitch Up):** $135.0^\circ$ (410 ticks $\approx 2000\ \mu\text{s}$). Prevents upward cable pinch.
- **Slew Rate Limit:** $1.0^\circ$ per 15 ms step ($\approx 66.7^\circ/\text{s}$).

### 4.4 Flashing & Running Test 3

#### Option A: Using PlatformIO
```bash
cd "d:\Project\Rana Project\smartvision\firmware"
pio run -e test_03_mg90s_tilt -t upload
pio device monitor -b 115200
```

#### Option B: Using Arduino CLI
```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 --build-property build.extra_flags="-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1 -Iinclude" src/standalone/03_mg90s_tilt_test.cpp
arduino-cli upload -p COMx --fqbn esp32:esp32:esp32s3 src/standalone/03_mg90s_tilt_test.cpp
arduino-cli monitor -p COMx -c baudrate=115200
```

### 4.5 Expected Serial Monitor Output (Test 3)
```text
========================================================
   SMARTVISION HARDWARE TEST 03: MG90S TILT SERVO (CH 1)
========================================================
Safety Constraints Enforced:
  Channel:                Channel 1
  Conservative Min Limit: 60.0 deg (Ticks: 239, ~1166 us - Pitch Down)
  Center / Level Horizon: 90.0 deg (Ticks: 307, ~1499 us)
  Conservative Max Limit: 135.0 deg (Ticks: 410, ~2001 us - Pitch Up)
Power & Wiring Check:
  1. External 5V 5A supply connected to PCA9685 V+ / GND.
  2. Common GND bonded between ESP32 and PCA9685.
  3. Pan servo (MG996R) UNPLUGGED for this single-axis test.
========================================================

[STEP 1] Initializing Tilt to Level Horizon (90.0 deg)...
[PASS] Tilt servo leveled. Starting verification sweep sequence.

--- Starting Tilt Sweep Cycle #1 ---
Testing Tilt Minimum Limit (60.0 deg - Down):
  [SLEW] Moving Tilt from 90.0 deg -> 60.0 deg... ARRIVED! (Ticks: 239, Pulse: 1166 us)
  Holding at 60.0 deg for 2.0 seconds... (Check camera bracket clearance)
Returning to Level (90.0 deg):
  [SLEW] Moving Tilt from 60.0 deg -> 90.0 deg... ARRIVED! (Ticks: 307, Pulse: 1499 us)
Testing Tilt Maximum Limit (135.0 deg - Up):
  [SLEW] Moving Tilt from 90.0 deg -> 135.0 deg... ARRIVED! (Ticks: 410, Pulse: 2001 us)
  Holding at 135.0 deg for 2.0 seconds... (Check camera bracket clearance)
Returning to Level (90.0 deg):
  [SLEW] Moving Tilt from 135.0 deg -> 90.0 deg... ARRIVED! (Ticks: 307, Pulse: 1499 us)
  Cycle Complete! Holding at level for 4 seconds.
```

---

## 5. Master Unified Test Suite & Live Calibration

### 5.1 Overview
The `hardware_suite` firmware combines all diagnostics into a single interactive serial harness. Once both individual tests have passed, both servos may be plugged in simultaneously (Pan on Ch 0, Tilt on Ch 1).

### 5.2 Flashing & Running the Interactive Suite

#### Option A: Using PlatformIO
```bash
cd "d:\Project\Rana Project\smartvision\firmware"
pio run -e hardware_suite -t upload
pio device monitor -b 115200
```

#### Option B: Using Arduino CLI
```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 --build-property build.extra_flags="-DARDUINO_USB_CDC_ON_BOOT=1 -DARDUINO_USB_MODE=1 -Iinclude" src/main.cpp
arduino-cli upload -p COMx --fqbn esp32:esp32:esp32s3 src/main.cpp
arduino-cli monitor -p COMx -c baudrate=115200
```

### 5.3 Interactive Command Reference

| Command | Action | Description |
|---|---|---|
| `1` | **I2C Bus Scan** | Probes addresses `0x01`–`0x7E`, validates PCA9685 at `0x40`. |
| `2` | **Pan Sweep Test** | Sweeps MG996R through $90^\circ \to 15^\circ \to 165^\circ \to 90^\circ$. |
| `3` | **Tilt Sweep Test** | Sweeps MG90S through $90^\circ \to 60^\circ \to 135^\circ \to 90^\circ$. |
| `4` | **Dual-Axis Sweep** | Simultaneous diagonal sweeping under load to test power supply margin ($15^\circ/60^\circ \to 165^\circ/135^\circ \to 90^\circ/90^\circ$). |
| `5` | **Power Transient Test** | 10 rapid 50 Hz direction changes to verify $1000\ \mu\text{F}$ capacitor decoupling. |
| `p <angle>` | **Manual Pan Jog** | Move pan to arbitrary angle with safety clamp (e.g. `p 45.0` or `p 120`). Input is strictly validated. |
| `t <angle>` | **Manual Tilt Jog** | Move tilt to arbitrary angle with safety clamp (e.g. `t 75` or `t 110`). Input is strictly validated. |
| `c` | **Center Servos** | Gently slews both servos to Neutral Boresight ($90.0^\circ, 90.0^\circ$). |
| `0` | **Emergency Cutoff** | Dual-layer cutoff: drives PCA9685 `OE` pin HIGH AND silences all PWM registers in hardware. Blocks motion commands. |
| `e` | **Re-Enable Outputs** | Drives PCA9685 `OE` pin LOW, clears E-Stop lock, and restores PWM tracking. |
| `h` | **Help Menu** | Redisplays the command menu. |

---

## 6. Hardware Troubleshooting Flowchart

### Issue 1: `[FAIL] No I2C devices found on bus!`
- **Check 1:** Verify SDA is connected to GPIO 8, SCL to GPIO 9.
- **Check 2:** Verify PCA9685 `VCC` is plugged into ESP32 3.3V (NOT 5V).
- **Check 3:** Verify common ground between ESP32 and PCA9685. Test continuity with a DMM: resistance between ESP32 GND and PCA9685 GND must be $< 0.5\ \Omega$.

### Issue 2: ESP32 Resets During Servo Sweep (`Reset Reason: 3` / `ESP_RST_BROWNOUT`)
- **Root Cause:** External 5V rail dropped below 2.8V due to high servo current draw.
- **Fix 1:** Verify external 5V 5A power supply is connected to PCA9685 $V+$ screw terminals. Servos must NEVER be powered from ESP32 pins.
- **Fix 2:** Verify the $1000\ \mu\text{F}$ capacitor is connected across $V+$ and GND screw terminals.
- **Fix 3:** Replace thin DuPont power wires with 20–22 AWG wire directly from the power supply.

### Issue 3: Servo Buzzing, Vibrating or Stalling at Limits
- **Root Cause:** Mechanical bind against camera mount bracket or USB cable pulling against the servo arm.
- **Fix 1:** Loosen servo horn screw, center servo to $90^\circ$ via command `c`, re-seat the horn at exactly $90^\circ$, and tighten.
- **Fix 2:** Ensure minimum 12 cm coiled service loop on the USB webcam cable.

---

## 7. Phase 1 Sign-Off & Verification Checklist

- [x] **ESP32-S3 CPU & Flash Health:** Verified at 240 MHz with 16 MB Flash and Octal PSRAM isolation.
- [x] **PCA9685 I2C Communication:** Verified ACK at `0x40`, 50 Hz PWM prescaler configured (121 / `0x79`).
- [x] **MG996R Pan Verification:** Independent sweep verified with bounds clamped strictly to $[15.0^\circ, 165.0^\circ]$.
- [x] **MG90S Tilt Verification:** Independent sweep verified with bounds clamped strictly to $[60.0^\circ, 135.0^\circ]$.
- [x] **Hardware OE Pin Cutoff:** Verified GPIO 12 tri-state emergency disabling.
- [x] **Power Margin Budget:** 5.0V 5.0A external supply verified with $23.48\%$ safety reserve headroom under worst-case dual stall ($3.826\text{ A}$).
- [x] **PlatformIO Compilation:** Verified 100% clean builds for `hardware_suite`, `test_01_i2c_scan`, `test_02_mg996r_pan`, and `test_03_mg90s_tilt`.
