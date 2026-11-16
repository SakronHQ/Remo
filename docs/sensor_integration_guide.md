# SmartVision Phase 2: Sensor Integration & Verification Guide

**Document Version:** 1.0.0 (Phase 2 Baseline)  
**Author:** SmartVision Engineering Team  
**Scope:** HC-SR501 PIR Motion Sensor, HC-SR04 Ultrasonic Distance Sensor, Active Buzzer Driver, Safe Voltage Shifting, Non-Blocking Drivers, and Telemetry Reporting  
**Status:** Approved Engineering Guide  

---

## 1. Executive Summary & Objectives

Phase 2 transitions SmartVision from motor verification into active environmental perception and acoustic feedback. The system integrates three essential hardware peripherals directly with the **ESP32-S3 N16R8**:
1. **HC-SR501 PIR Motion Sensor:** Wide-angle passive infrared human body detection for armed perimeter surveillance, featuring boot-up thermal stabilization window handling (30–60 seconds).
2. **HC-SR04 Ultrasonic Distance Sensor:** High-frequency 40 kHz acoustic rangefinding for collision avoidance, obstacle proximity warnings, and non-blocking distance sampling.
3. **Active 5V Buzzer Driver:** Transistor-switched acoustic alert transducer delivering distinct audible signals (Beep, Alert Chirp, Emergency Alarm, Pulsed Warnings, and Instant Mute).

All firmware is built according to **Ponytail principles**: minimal code, zero external third-party library dependencies, non-blocking asynchronous state machines, defensive bounded timeouts, and strict silicon protection against over-voltage and PSRAM pin corruption.

---

## 2. GPIO Pin Allocation & Silicon Protection Matrix

| Peripheral Function | ESP32-S3 GPIO | Direction | Logic Level | Circuit / Interface Scheme | Hardware Destination | Boot State |
|---|---|---|---|---|---|---|
| **HC-SR04 Trigger** | **GPIO 4** | Output | 3.3V CMOS | Direct push-pull ($10\ \mu\text{s}$ pulse) | HC-SR04 Trig Pin | LOW |
| **HC-SR04 Echo** | **GPIO 5** | Input | 3.3V Logic | **$1\text{ k}\Omega / 2\text{ k}\Omega$ Voltage Divider** (from 5V) | Divider Junction | Hi-Z |
| **HC-SR501 PIR** | **GPIO 6** | Input | 3.3V Logic | Native 3.3V output (`INPUT_PULLDOWN`) | HC-SR501 OUT Pin | LOW |
| **Active Buzzer** | **GPIO 7** | Output | 3.3V CMOS | **2N2222 NPN Switch** via $1\text{ k}\Omega$ base resistor | Transistor Base | LOW (Silent) |
| **PCA9685 SDA** | **GPIO 8** | Bidirectional | 3.3V Open-Drain | $4.7\text{ k}\Omega$ pull-up to 3.3V | PCA9685 SDA | High (Idle) |
| **PCA9685 SCL** | **GPIO 9** | Output | 3.3V Open-Drain | $4.7\text{ k}\Omega$ pull-up to 3.3V | PCA9685 SCL | High (Idle) |
| **Status LED** | **GPIO 10** | Output | 3.3V CMOS | $330\ \Omega$ series resistor to LED anode | LED Anode | LOW |
| **PCA9685 OE** | **GPIO 12** | Output | 3.3V Push-Pull | Hardware Output Enable (Active LOW) | PCA9685 OE Pin | LOW (Enabled) |

> [!CAUTION] **CRITICAL SILICON CONSTRAINT: GPIO 33–37 ARE BONDED TO OCTAL PSRAM**  
> The ESP32-S3 N16R8 module integrates 8 MB high-speed Octal PSRAM. **GPIO 33, 34, 35, 36, and 37 are internally bonded directly to the PSRAM die.** Never connect wires, resistors, or pull-ups to these pins, and never configure them in firmware. Any assertion on these pins causes instant CPU kernel panics (`Cache disabled but cached memory region accessed`). All sensor assignments strictly utilize low-numbered GPIOs (4, 5, 6, 7, 8, 9, 10, 12).

---

## 3. Circuit Schematics & Electrical Interfacing

### 3.1 HC-SR04 Safe 5V-to-3.3V Echo Level-Shifting Circuit

#### Problem Statement
The HC-SR04 ultrasonic sensor requires a 5.0V DC power rail to generate its 40 kHz acoustic burst and emits a **5.0V active-high pulse** on its `Echo` pin. Connecting this 5.0V signal directly to the ESP32-S3 GPIO pin breaches the absolute maximum rating ($V_{DD} + 0.3\text{ V} \approx 3.6\text{ V}$), destroying the MCU input buffer.

#### Voltage Divider Topology & Transfer Function
A passive two-resistor divider safely steps down the 5.0V signal to 3.33V:

```
[HC-SR04 Echo (5.0V)] ----[ R1: 1.0 kΩ ]----+---- [ ESP32-S3 GPIO 5 (3.33V) ]
                                            |
                                      [ R2: 2.0 kΩ ]
                                            |
                                          [ GND ]
```

$$V_{\text{out}} = V_{\text{in}} \cdot \frac{R_2}{R_1 + R_2} = 5.0\text{ V} \cdot \frac{2000\ \Omega}{1000\ \Omega + 2000\ \Omega} = 5.0 \cdot \frac{2}{3} \approx 3.333\text{ V}$$

#### Electrical Margin & Tolerance Validation
- **Nominal Output:** $3.333\text{ V}$ (perfect match for 3.3V CMOS logic).
- **Current Drawn from Echo Pin:** $I = \frac{5.0\text{ V}}{3000\ \Omega} \approx 1.67\text{ mA}$ (well within the HC-SR04 15 mA drive capability).
- **Worst-Case 5% Resistor Tolerance Analysis:**
  - $R_1 \in [950\ \Omega, 1050\ \Omega]$, $R_2 \in [1900\ \Omega, 2100\ \Omega]$.
  - $V_{\text{out,max}} = 5.0 \cdot \frac{2100}{950 + 2100} = 3.443\text{ V} \le 3.600\text{ V}$ (Safe: $157\text{ mV}$ below absolute maximum rating).
  - $V_{\text{out,min}} = 5.0 \cdot \frac{1900}{1050 + 1900} = 3.220\text{ V} \ge 2.475\text{ V}$ (Safe: $745\text{ mV}$ above ESP32 $V_{IH,\text{min}}$ threshold).
- **Acoustic Rise-Time Analysis:**
  - Thevenin equivalent resistance: $R_{\text{th}} = \frac{1000 \cdot 2000}{3000} \approx 666.7\ \Omega$.
  - Parasitic capacitance: $C_p = C_{\text{pin}} + C_{\text{stray}} \approx 8\text{ pF} + 12\text{ pF} = 20\text{ pF}$.
  - Time constant: $\tau = R_{\text{th}} \cdot C_p = 666.7\ \Omega \cdot 20\text{ pF} \approx 13.33\text{ ns}$.
  - Rise time ($10\% - 90\%$): $t_r = 2.2 \cdot \tau \approx 29.33\text{ ns}$.
  - Round-trip echo duration for minimum distance ($2.0\text{ cm}$): $t_{\text{echo}} \approx 116.5\ \mu\text{s} = 116,500\text{ ns}$.
  - Rise time error: $\frac{29.33\text{ ns}}{116,500\text{ ns}} \approx 0.025\%$ ($\Delta d \approx 0.0005\text{ mm}$).
  **Conclusion:** The passive divider introduces **zero measurable acoustic distortion**.

---

### 3.2 HC-SR501 PIR Motion Sensor Interfacing

#### Operating Characteristics & 3.3V Logic Compatibility
- **Power Supply (VCC):** Powered from the regulated external 5V rail.
- **On-board LDO Regulator:** The HC-SR501 integrates a 7133-1 low-dropout 3.3V linear regulator. **Its `OUT` pin outputs native 3.3V logic (HIGH = 3.3V, LOW = 0V)**. It connects directly to **GPIO 6** with no level shifter required.
- **Firmware Pull-Down:** Configured as `pinMode(PIN_PIR_INPUT, INPUT_PULLDOWN)` to prevent floating inputs when the sensor is detached.

```
       +5V Rail -----------------> [ VCC ] HC-SR501
     Common GND -----------------> [ GND ] HC-SR501
ESP32-S3 GPIO 6 <----------------- [ OUT ] HC-SR501 (Native 3.3V Output)
```

#### Boot-Up Thermal Stabilization Window (30–60 Seconds)
When powered on, the pyroelectric infrared sensing crystal absorbs ambient thermal radiation and establishes thermodynamic equilibrium. During this **30 to 60-second warm-up window**, the internal comparator fluctuates erratically, generating false HIGH pulses:
- The `HCSR501Driver` class implements a non-blocking `isWarmingUp()` timer tracking `millis() - boot_time_ms < PIR_WARMUP_DEFAULT_MS (30000 ms)`.
- During warm-up, all incoming pulses are strictly suppressed: `isMotionDetected()` returns `false`, preventing false alarms on system power-up.
- Diagnostic functions provide real-time warm-up progress (`getWarmupProgress()`, `getWarmupRemainingMs()`).
- Developers can press `'f'` in the Serial Monitor to force-bypass warm-up during rapid bench testing.

#### Physical Hardware Configuration (Jumpers & Trimpots)
1. **Retriggering Jumper Mode:**
   - **Position 'H' (Repeatable Trigger - RECOMMENDED):** While human motion continues within the detection cone, the output pin stays continuous HIGH. Once motion ceases, the pin goes LOW after the delay time.
   - **Position 'L' (Single Trigger):** The sensor pulses HIGH once for the delay duration, then goes LOW for a fixed 2.5s inhibit period regardless of continued motion.
2. **Time Delay Potentiometer ($T_x$):**
   - Turn **fully counter-clockwise** to set the minimum hold time ($\approx 2.5 - 3.0$ seconds). This provides maximum responsiveness for real-time tracking.
3. **Sensitivity Potentiometer ($S_x$):**
   - Turn to approximately **50% (middle position)** to establish a sensing cone radius of $3 - 5$ meters. Turning fully clockwise increases sensitivity up to 7 meters (which may catch peripheral movements).

---

### 3.3 Active 5V Buzzer Transistor Driver Circuit

#### Problem Statement & Component Sizing
An active 5V electromagnetic buzzer consumes **35 mA to 45 mA** when sounding. The ESP32-S3 GPIO pins have a recommended continuous current limit of **20 mA**. Driving the buzzer directly from GPIO causes excessive voltage drop, brownout resets, and junction degradation. Furthermore, an active buzzer contains an internal inductive coil; de-energizing the coil generates an inductive back-EMF voltage spike ($V = -L \frac{di}{dt}$) that destroys unprotected GPIO transistors.

#### Low-Side NPN Transistor Switch Schematic

```
               +5V Rail
                  |
             +----+----+
             |         |
             |     [ 1N4148 Diode ]
             |     (Cathode to +5V, Anode to Collector)
             |         |
      [ Active Buzzer ]|
             |         |
             +----+----+
                  |
              Collector
                  |
GPIO 7 ---[ 1kΩ RB ]--- Base (2N2222)
                  |
             [ 10kΩ RPD ]
                  |
               Emitter
                  |
              Common GND
```

#### Component Parameter Derivations
1. **Collector Current ($I_C$):** $I_C \approx 40\text{ mA}$ at 5.0V.
2. **Forced Beta for Deep Saturation:** $\beta_{\text{forced}} = 15$ ($V_{CE(\text{sat})} \le 0.15\text{ V}$).
3. **Required Base Current ($I_B$):**
   $$I_B = \frac{I_C}{\beta_{\text{forced}}} = \frac{40\text{ mA}}{15} \approx 2.67\text{ mA}$$
4. **Base Resistor Value ($R_B$):**
   $$R_B = \frac{V_{OH} - V_{BE(\text{sat})}}{I_B} = \frac{3.3\text{ V} - 0.7\text{ V}}{0.00267\text{ A}} = \frac{2.6\text{ V}}{0.00267\text{ A}} \approx 973.8\ \Omega \implies \mathbf{1.0\text{ k}\Omega\ (\text{Standard E24})}$$
   - GPIO 7 current draw: $I_B = \frac{3.3 - 0.7}{1000} = 2.60\text{ mA}$ (only $13\%$ of GPIO capacity).
5. **Inductive Flyback Clamping Diode (1N4148):**
   - Placed in anti-parallel across the buzzer terminals (Cathode to +5V, Anode to Collector). Clamps reverse inductive kickback spikes safely to $V_{CC} + V_F \approx 5.0\text{ V} + 0.7\text{ V} = 5.7\text{ V}$.
6. **Base Pull-Down Resistor ($R_{PD} = 10\text{ k}\Omega$):**
   - Keeps the 2N2222 firmly in cutoff during MCU bootloader execution, holding the buzzer silent.

---

## 4. Software Architecture & Modular Drivers

The firmware is located in `firmware/` and organized into self-contained header-only drivers:

```
firmware/
├── include/
│   ├── hardware_config.h     # Complete pin assignments, safety clamps, and sensor limits
│   ├── buzzer_driver.h       # Non-blocking Active Buzzer pattern state machine
│   ├── hcsr04_driver.h       # Non-blocking, timeout-safe HC-SR04 ultrasonic driver
│   ├── hcsr501_driver.h      # HC-SR501 PIR driver with boot warm-up window management
│   └── pca9685_driver.h      # Zero-dependency 12-bit PWM servo driver (Phase 1)
├── src/
│   ├── sensor_suite.cpp      # Unified Interactive Diagnostic Suite (Phase 2)
│   ├── main.cpp              # Unified Hardware Verification Suite (Phase 1)
│   └── standalone/
│       ├── 01_i2c_scanner.cpp
│       ├── 02_mg996r_pan_test.cpp
│       ├── 03_mg90s_tilt_test.cpp
│       ├── 04_buzzer_test.cpp
│       ├── 05_ultrasonic_test.cpp
│       └── 06_pir_test.cpp
└── platformio.ini             # Multi-target build configurations
```

### 4.1 Non-Blocking Buzzer Patterns (`buzzer_driver.h`)
The buzzer driver runs a millisecond-precision state machine called via `buzzer.update(now_ms)`:
- `beep(duration_ms)`: Emits a single clean notification tone (default 150 ms).
- `chirp()`: Emits a distinct double chirp (70 ms ON, 50 ms OFF, 70 ms ON) for acknowledgments and motion alerts.
- `alarm(true)`: Continuously alternates 150 ms ON and 150 ms OFF until `mute()` is called.
- `pulse(count, on_ms, off_ms)`: Emits $N$ warning pulses.
- `mute()`: Instantly cuts off output and resets the sequence.

### 4.2 Timeout-Safe Ultrasonic Timing (`hcsr04_driver.h`)
- Issues a clean $10\ \mu\text{s}$ trigger pulse.
- Samples echo duration using `pulseIn` with a hardcoded **$30,000\ \mu\text{s}$ timeout** ($\approx 515\text{ cm}$ maximum flight time).
- Speed of sound temperature compensation:
  $$v(T) = (331.3 + 0.606 \times T)\text{ m/s}$$
  Acoustic propagation uses ambient room air temperature ($20.0^\circ\text{C}$ nominal via `DEFAULT_AMBIENT_TEMP_C`), while the ESP32-S3 internal temperature sensor (`temperatureRead()`) monitors MCU die health in telemetry.
- Out-of-Range Rejection: Readings $< 2.0\text{ cm}$ or $> 400.0\text{ cm}$ are marked `valid = false`, classified as `"out_of_range"`, and report `-1.0f` conforming to `docs/protocol.md`. Reflections $< 20.0\text{ cm}$ (including $< 2.0\text{ cm}$) are defensively flagged by `isObstruction()` for collision avoidance. If no echo is detected, the status is `"timeout"` with distance `-1.0f`.
- 5-Sample Median Filter: Rejects single-frame acoustic reflections and specular bounce noise.

### 4.3 PIR Thermal Stabilization (`hcsr501_driver.h`)
- Maintains a 30-second countdown upon boot.
- Suppresses false triggers until thermal equilibrium is established.
- Debounces rising-edge transitions with a 50 ms window, logging incremental trigger counts and millisecond timestamps.

---

## 5. PlatformIO Build Targets & Execution

All targets compile with zero warnings using the native Espressif32 toolchain.

### 5.1 Build Commands

```bash
# Navigate to firmware directory
cd "d:\Project\Rana Project\smartvision\firmware"

# Compile Unified Sensor Verification Suite (Phase 2 Default)
pio run -e sensor_suite

# Compile Standalone Buzzer Test
pio run -e test_04_buzzer

# Compile Standalone Ultrasonic Test
pio run -e test_05_ultrasonic

# Compile Standalone PIR Motion Test
pio run -e test_06_pir

# Flash sensor suite to ESP32-S3 over USB-C
pio run -e sensor_suite -t upload

# Open Serial Monitor at 115200 baud
pio device monitor -b 115200
```

---

## 6. Interactive Diagnostic Suite Walkthrough (`sensor_suite`)

Upon opening the Serial Monitor at 115200 baud, the ESP32-S3 emits an initial 100 ms confirmation beep and renders the interactive menu:

```
================================================================================
         SMARTVISION PHASE 2: UNIFIED SENSOR VERIFICATION SUITE                 
================================================================================
MCU:            ESP32-S3 (Chip Rev: 2, Cores: 2)
CPU Freq:       240 MHz | Flash: 8 MB | Free Heap: 301248 bytes
Internal Temp:  42.5 °C
--------------------------------------------------------------------------------
HC-SR04 Sonar:  Trig = GPIO 4 | Echo = GPIO 5 (1k/2k Divider -> 3.33V)
HC-SR501 PIR:   Out = GPIO 6 (Native 3.3V, 30000 ms warm-up window)
Active Buzzer:  GPIO 7 (Low-side 2N2222 NPN driver + 1N4148 flyback clamp)
Status LED:     GPIO 10 (Active HIGH via 330R)
I2C Bus:        SDA = GPIO 8 | SCL = GPIO 9 (PCA9685 at 0x40)
================================================================================

------------------------- SENSOR DIAGNOSTIC MENU ---------------------------
  [1] Stream Real-time Tabular Sensor Data (10 Hz live monitor)
  [2] Stream Formatted JSON Telemetry (10 Hz matching docs/protocol.md)
  [3] Run HC-SR04 Ultrasonic Accuracy & Noise Benchmark
  [4] Run HC-SR501 PIR Motion & Warm-up Verification
  [5] Run Active Buzzer Pattern Demo (Beep, Chirp, Alarm, Pulse, Mute)
  [6] Start Proximity Collision Avoidance Demo (Auto-alarm < 20cm)
  [7] Start Armed Security Alarm Demo (Auto-chirp on PIR trigger)
  --- Quick Action Keys ---
  [b] Single Beep (150ms)        | [c] Alert Chirp
  [a] Toggle Continuous Alarm     | [m] Mute Buzzer
  [u] Single Ultrasonic Ping     | [p] Query PIR State
  [f] Force Bypass PIR Warm-up   | [j] Single JSON Telemetry Snapshot
  [s] Stop Streaming / Return to Menu
  [h] Redisplay This Menu
----------------------------------------------------------------------------
Select command > 
```

### 6.1 Mode 1: Live Tabular Stream (10 Hz)
Pressing `'1'` streams human-readable sensor telemetry:

```
+------------+---------------+--------------+------------------+------------------+-----------------+
| Time (ms)  | Distance (cm) | Sonar Status | PIR Motion State | Buzzer Pattern   | Status LED      |
+------------+---------------+--------------+------------------+------------------+-----------------+
| 14200      | 85.3          | in_range     | WARMING UP (16s) | off              | OFF (LOW)       |
| 14300      | 85.1          | in_range     | WARMING UP (16s) | off              | OFF (LOW)       |
| 31200      | 42.6          | in_range     | CLEAR (Cnt:0)    | off              | OFF (LOW)       |
| 31300      | 18.4          | in_range     | DETECTED (Cnt:1) | alarm            | ON (HIGH)       |
| 31400      | -1.0          | timeout      | CLEAR (Cnt:1)    | off              | OFF (LOW)       |
```

### 6.2 Mode 2: Formatted JSON Telemetry Stream (10 Hz)
Pressing `'2'` streams production JSON telemetry conforming strictly to `docs/protocol.md` section 3.4 (`telem.sensors`):

```json
{"type":"telem.sensors","timestamp":35420,"sender":"esp32","seq":104,"corr_id":null,"payload":{"sonar":{"distance_cm":48.2,"valid":true,"status":"in_range"},"pir":{"motion_detected":false,"trigger_count":2,"last_trigger_ms":31200},"servos":{"pan_angle":90.0,"tilt_angle":90.0,"pan_target":90.0,"tilt_target":90.0,"is_moving":false},"buzzer":{"active":false,"pattern":"off"},"system":{"uptime_ms":35420,"rssi_dbm":-55,"free_heap_bytes":298412,"psram_free_bytes":0,"cpu_temp_c":43.1}}}
```

### 6.3 Mode 6: Proximity Collision Avoidance Routine
Demonstrates autonomous multi-tier safety reaction:
- **Object $< 20.0\text{ cm}$ (Critical Obstruction):** Immediately triggers continuous emergency buzzer alarm and rapidly flashes Status LED at 10 Hz.
- **Object between $20.0\text{ cm}$ and $40.0\text{ cm}$ (Warning Zone):** Emits warning chirps once per second and illuminates Status LED solid.
- **Object $> 40.0\text{ cm}$ (Safe Zone):** Mutes buzzer and extinguishes Status LED.

---

## 7. Automated Python Verification Suite

The repository includes a comprehensive standalone test script at `tests/test_sensor_integration.py` that validates all mathematical, physical, and protocol specifications without requiring connected hardware.

```bash
# Execute Phase 2 automated test suite
py tests/test_sensor_integration.py
```

### Test Coverage Summary

```
================================================================================
    SMARTVISION PHASE 2: SENSOR INTEGRATION AUTOMATED TEST SUITE                
================================================================================
  [1/5] Testing Voltage Divider Math, Tolerances, and Rise-Time...
    - Nominal Vout: 3.3333 V (Current: 1.67 mA)
    - 5% Worst-Case Limits: [3.220 V .. 3.443 V] (Safe within 2.475V - 3.600V)
    - RC Rise Time: 29.33 ns (0.000% of min pulse width, zero acoustic impact)
  [2/5] Testing Ultrasonic Timing, Temperature Compensation, and Limits...
    - Speed of sound: 0°C = 331.3 m/s | 20°C = 343.4 m/s | 40°C = 355.5 m/s
    - Pulse durations: 2cm = 116 us | 20cm = 1165 us | 400cm = 23295 us
    - Timeout headroom: 6705 us (28.8% safety margin beyond 400cm)
  [3/5] Testing PIR Boot Warm-up Window & Motion Edge Detection...
    - Warm-up window: 30,000 ms accurately suppresses noise and tracks progress
    - Rising-edge detector: verified clean debouncing and trigger counting
  [4/5] Testing Active Buzzer Non-Blocking Patterns & Mute...
    - Beep: verified single-shot duration cut-off
    - Chirp: verified 70ms-ON / 50ms-OFF / 70ms-ON cadence
    - Alarm: verified 150ms alternating cycle and instantaneous mute
    - Pulse: verified exact cycle count (3 pulses) and clean shutdown
  [5/5] Testing Telemetry JSON Schema Compliance (telem.sensors)...
    - Envelope keys, types, and sequence bounds verified
    - Sonar sub-schema verified (distance_cm, valid, status in_range/out_of_range/timeout)
    - PIR sub-schema verified (motion_detected, trigger_count, last_trigger_ms)
    - Buzzer sub-schema verified (active, pattern)
    - System sub-schema verified (uptime, heap, psram, temperature)
================================================================================
 [PASS] All 5 sensor integration test suites completed with ZERO errors!        
================================================================================
```

---

## 8. Physical Bench Verification & Calibration Checklist

Before powering up the complete rig, execute this sequential electrical verification:

| # | Inspection Item | Verification Procedure | Expected Measurement | Pass/Fail |
|---|---|---|---|---|
| **1** | **Echo Divider Output** | Disconnect GPIO 5. Place target at 100 cm. Measure voltage at divider junction with DMM or oscilloscope. | $3.25\text{ V} \le V_{\text{peak}} \le 3.40\text{ V}$ | [ ] PASS |
| **2** | **PIR Logic Level** | Measure HC-SR501 OUT pin voltage with DMM during active motion. | $3.20\text{ V} \le V_{\text{high}} \le 3.35\text{ V}$ | [ ] PASS |
| **3** | **Buzzer Saturation** | Command buzzer ON (`'b'`). Measure $V_{CE}$ across 2N2222 Collector and Emitter. | $V_{CE(\text{sat})} \le 0.20\text{ V}$ | [ ] PASS |
| **4** | **Flyback Clamping** | Verify 1N4148 cathode is connected to +5V and anode to transistor collector. | Diode reverse-biased | [ ] PASS |
| **5** | **Common Ground** | Verify continuity between ESP32 GND, 5V supply GND, and sensor GND rails. | Resistance $< 0.2\ \Omega$ | [ ] PASS |
| **6** | **PIR Stabilization** | Observe boot sequence. Confirm zero false trigger events during initial 30s warm-up. | Status LED remains OFF | [ ] PASS |
| **7** | **Ultrasonic Linearity** | Place flat cardboard at 10cm, 50cm, 100cm, and 200cm. Verify reading accuracy. | Error $\le \pm 1.0\text{ cm}$ | [ ] PASS |
| **8** | **Obstruction Inhibit** | Move hand closer than 20 cm. Confirm emergency buzzer alarm fires immediately. | Alarm sounds, LED flashes | [ ] PASS |

---

## 9. Troubleshooting & Bench Diagnostics

### 9.1 Ultrasonic Sensor Always Returns `-1.0` or `"timeout"`
- **Cause 1:** 5V rail is disconnected or sagging. The HC-SR04 transmitter cannot oscillate at 3.3V.
- **Cause 2:** Resistor divider values swapped ($2\text{ k}\Omega$ in series, $1\text{ k}\Omega$ to ground), yielding only $1.67\text{ V}$, which falls below ESP32 $V_{IH}$ minimum ($2.475\text{ V}$).
- **Cause 3:** Soft acoustic target (e.g. clothing, foam) or target angled $> 15^\circ$, causing acoustic reflection away from receiver. Test with a solid, flat notebook or cardboard.

### 9.2 PIR Triggers Constantly / Random False Alarms
- **Cause 1:** Sensor is still in the 30-second thermal stabilization window. Wait for countdown to reach 0.
- **Cause 2:** Jumper is set to single-trigger mode ('L') instead of repeatable trigger ('H'). Move jumper to 'H'.
- **Cause 3:** Sensitivity trimpot ($S_x$) is turned to maximum ($7\text{ m}$), picking up ambient air currents or heat convection. Dial back to 50%.
- **Cause 4:** Common ground between ESP32 and PIR has high resistance, causing ground bounce. Verify star-topology ground.

### 9.3 Buzzer Clicks But Does Not Sound Tone
- **Cause 1:** Passive buzzer installed instead of an active buzzer. Active buzzers have an internal oscillator and produce sound with continuous DC voltage. Passive buzzers require a PWM frequency (LEDC/tone).
- **Cause 2:** 2N2222 transistor polarity reversed (Emitter and Collector swapped). Emitter must connect to GND; Collector connects to buzzer negative.

### 9.4 ESP32 Brownout Reset When Buzzer Sounds
- **Cause 1:** Buzzer is connected to the ESP32 3.3V pin instead of the external 5V power supply rail.
- **Cause 2:** Missing $1000\ \mu\text{F}$ buffer capacitor across the 5V power rail. Add electrolytic capacitor across power entry terminals.
