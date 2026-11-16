# SmartVision Phase 3: ESP32-S3 Firmware Guide

**Document Version:** 1.0.0 (Phase 3 Baseline)  
**Target Platform:** ESP32-S3 N16R8 (Dual-Core Xtensa LX7 @ 240 MHz, 16MB SPI Flash, 8MB Octal PSRAM)  
**Peripheral Drivers:** PCA9685 I2C 16-Ch PWM, MG996R Pan Servo, MG90S Tilt Servo, HC-SR04 Ultrasonic Sensor, HC-SR501 PIR Sensor, 5V Active Buzzer, System Status LED  
**Communication Protocol:** Full-Duplex WebSocket (`/ws/device`), JSON Envelope (`docs/protocol.md`)  
**Operating System:** FreeRTOS / Arduino-ESP32 Core 3.3+  

---

## 1. Modular Firmware Architecture

The Phase 3 firmware in `smartvision/firmware/` is partitioned into decoupled, single-responsibility modules following Ponytail principles (clean, minimal, standard Arduino/FreeRTOS primitives, zero unnecessary dependencies):

```
smartvision/firmware/
├── include/
│   ├── hardware_config.h     # Calibrated pin assignments, servo clamps & register definitions
│   ├── firmware_config.h     # Wi-Fi credentials, backend WS endpoints, task priorities & timeouts
│   ├── config.h              # Forwarding alias to firmware_config.h
│   ├── firmware_types.h      # FreeRTOS inter-task command, snapshot & queue data structures
│   ├── wifi_manager.h        # Wi-Fi auto-reconnect engine with exponential backoff
│   ├── websocket_client.h    # RFC6455 full-duplex WebSocket client (/ws/device)
│   ├── protocol_handler.h    # Inbound JSON dispatcher & outbound telemetry serializer
│   ├── motion_engine.h       # 50 Hz discrete slew rate interpolation & boundary protection
│   ├── sensor_engine.h       # 10 Hz HC-SR04 ping, HC-SR501 debounce & non-blocking buzzer
│   ├── pca9685_driver.h      # Zero-dependency PCA9685 12-bit I2C driver
│   ├── hcsr04_driver.h       # Non-blocking HC-SR04 driver with 5-sample median filter
│   ├── hcsr501_driver.h      # HC-SR501 driver with 30s thermal stabilization guard
│   └── buzzer_driver.h       # Non-blocking active buzzer pattern state machine
├── src/
│   ├── firmware_main.cpp     # FreeRTOS dual-core task spawning & watchdog supervisor
│   ├── wifi_manager.cpp      # Wi-Fi station connection & RSSI tracking implementation
│   ├── websocket_client.cpp  # WebSocket lifecycle & frame transmission implementation
│   ├── protocol_handler.cpp  # ArduinoJson v7 parser & serializer implementation
│   ├── motion_engine.cpp     # PCA9685 servo control & slew interpolation implementation
│   └── sensor_engine.cpp     # Sensor sampling & buzzer dispatch implementation
└── platformio.ini            # Target build environments (smartvision_firmware, test suites)
```

---

## 2. FreeRTOS Dual-Core Concurrency & Task Partitioning

The ESP32-S3 features two independent 32-bit Xtensa LX7 cores. Network packet processing and Wi-Fi stack interrupts are isolated on **Core 0**, while hard real-time servo PWM actuation and microsecond sensor acquisition run deterministically on **Core 1**:

```
+-------------------------------------------------------------------------------------------------+
|                                    ESP32-S3 DUAL-CORE XTENSA LX7                                |
+-----------------------------------------------+-------------------------------------------------+
|                    CORE 0                     |                     CORE 1                      |
|       (Networking & Communications Hub)       |      (Deterministic Control & Real-Time Safety) |
+-----------------------------------------------+-------------------------------------------------+
|                                               |                                                 |
|  [Task_WatchdogSupervisor] (Priority 4)       |  [Task_Motion] (Priority 3, 50 Hz / 20ms)       |
|    - 800ms communication watchdog timer       |    - Consumes from g_servoCmdQueue              |
|    - Failsafe supervisor (FAILSAFE_ACTIVE)    |    - Discrete slew rate interpolation           |
|    - Freeze servos & warning buzzer cadence   |    - Certified limit clamping [15°-165°,60°-135°|
|                                               |    - Proximity obstacle motion halt (< 20 cm)   |
|                                               |    - Writes 12-bit counts to PCA9685 via I2C    |
|                                               |                                                 |
|  [Task_Network] (Priority 1)                  |  [Task_Sensors] (Priority 2, 10 Hz / 100ms)     |
|    - Wi-Fi station association                |    - 10 Hz HC-SR04 ping with 5-median filter    |
|    - Exponential backoff (1s -> 10s ceiling)  |    - HC-SR501 PIR motion edge detection         |
|    - WebSocket client (/ws/device)            |    - Non-blocking active buzzer state machine   |
|    - Inbound JSON dispatch to ProtocolHandler |    - Serializes 10 Hz telem.sensors JSON        |
|    - Transmits messages from g_outboxQueue    |    - Enqueues telemetry to g_outboxQueue        |
|                                               |    - Heartbeat status LED blink (GPIO 10)       |
+-----------------------------------------------+-------------------------------------------------+
                                     |                     ^
                                     | g_servoCmdQueue     |
                                     +---------------------+
                                     | g_buzzerCmdQueue    |
                                     +---------------------+
                                     ^ g_outboxQueue       |
                                     +---------------------+
```

### FreeRTOS Allocation Summary Table

| Task Name | Core | Priority | Stack Size | Period / Execution | Responsibility |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `Task_WatchdogSupervisor` | **0** | **4** (Highest) | 4096 bytes | 50 ms | 800ms communication freshness watchdog; triggers `FAILSAFE_ACTIVE` |
| `Task_Motion` | **1** | **3** | 4096 bytes | 20 ms (50 Hz) | Slew interpolation; angle clamping; PCA9685 PWM output |
| `Task_Sensors` | **1** | **2** | 4096 bytes | 10 ms / 100 ms | HC-SR04 sonar ping; PIR sampling; buzzer patterns; `telem.sensors` generation |
| `Task_Network` | **0** | **1** | 8192 bytes | Continuous (5ms yield) | Wi-Fi link maintenance; WebSocket `/ws/device` event pump; outbox drain |

---

## 3. Hardware Pinout & Silicon Constraints

All pin assignments strictly match `hardware_config.h`.

> [!CAUTION] **Octal PSRAM Silicon Protection**
> The ESP32-S3 N16R8 module bonds **GPIO 33, 34, 35, 36, and 37** directly to high-speed Octal SPI PSRAM. These pins are strictly protected with compile-time `ASSERT_VALID_PIN()` assertions.

| Peripheral | Signal | ESP32-S3 GPIO | Electrical Interface | Notes |
| :--- | :--- | :---: | :--- | :--- |
| **PCA9685 PWM Driver** | `SDA` | **GPIO 8** | Open-drain, 4.7 kΩ pull-up to 3.3V | I2C Bus controller 0 (Addr: `0x40`) |
| **PCA9685 PWM Driver** | `SCL` | **GPIO 9** | Open-drain, 4.7 kΩ pull-up to 3.3V | 100 kHz standard mode |
| **PCA9685 PWM Driver** | `OE` | **GPIO 12** | Active LOW push-pull | LOW = outputs enabled, HIGH = high-Z |
| **Status Indicator LED** | `LED` | **GPIO 10** | Active HIGH via 330 Ω resistor | 1 Hz normal heartbeat, 5 Hz alert strobe |
| **Active 5V Buzzer** | `SIG` | **GPIO 7** | 2N2222 NPN switch via 1.0 kΩ base | Flyback 1N4148 diode clamped |
| **HC-SR04 Ultrasonic** | `TRIG` | **GPIO 4** | Push-pull 3.3V output | 10 µs trigger pulse |
| **HC-SR04 Ultrasonic** | `ECHO` | **GPIO 5** | High-Z input via 1.0k / 2.0k divider | Scaled from 5.0V to 3.33V |
| **HC-SR501 PIR Motion** | `OUT` | **GPIO 6** | Digital input with internal pull-down | Native 3.3V logic output |
| **MG996R Pan Servo** | `PWM` | **Ch 0** on PCA9685 | 50 Hz PWM (500 µs - 2500 µs) | Clamped to **[15.0°, 165.0°]** |
| **MG90S Tilt Servo** | `PWM` | **Ch 1** on PCA9685 | 50 Hz PWM (500 µs - 2500 µs) | Clamped to **[60.0°, 135.0°]** |

---

## 4. Wi-Fi Configuration & Exponential Backoff

Network parameters are configured in `include/firmware_config.h` (or passed via PlatformIO build flags):

```c
// Wi-Fi Access Point Credentials
#define WIFI_SSID           "SmartVision-AP"
#define WIFI_PASSWORD       "smartvision123"

// FastAPI Backend WebSocket Target
#define BACKEND_HOST        "192.168.1.100"
#define BACKEND_PORT        8000
#define BACKEND_WS_PATH     "/ws/device"
```

### Auto-Reconnection & Backoff Progression
To prevent Wi-Fi router storming and network thrashing during temporary router restarts, `WiFiManager` implements progressive exponential backoff:
1. Attempt connection with a **12-second** timeout window (`WIFI_CONNECT_TIMEOUT_MS`).
2. If connection fails or drops, disconnect clean and wait for the backoff interval.
3. The backoff interval starts at **1000 ms** (`WIFI_BACKOFF_MIN_MS`) and doubles upon each successive failure:
   $$1.0\text{ s} \longrightarrow 2.0\text{ s} \longrightarrow 4.0\text{ s} \longrightarrow 8.0\text{ s} \longrightarrow 10.0\text{ s (Ceiling)}$$
4. When connection is established (`WL_CONNECTED`), the backoff interval automatically resets to **1000 ms**.

---

## 5. WebSocket Communication Protocol (`/ws/device`)

All communication conforms strictly to `docs/protocol.md` JSON 5-field outer envelopes:
`type`, `timestamp`, `sender`, `seq`, `corr_id`, `payload`.

### 5.1 Outbound Telemetry: `telem.sensors` (10 Hz)
Streamed every 100 ms from `Task_Sensors`:
```json
{
  "type": "telem.sensors",
  "timestamp": 1731657110120,
  "sender": "esp32",
  "seq": 4501,
  "corr_id": null,
  "payload": {
    "sonar": {
      "distance_cm": 84.6,
      "valid": true,
      "status": "in_range"
    },
    "pir": {
      "motion_detected": true,
      "trigger_count": 14,
      "last_trigger_ms": 348120
    },
    "servos": {
      "pan_angle": 92.4,
      "tilt_angle": 88.1,
      "pan_target": 90.0,
      "tilt_target": 90.0,
      "is_moving": false
    },
    "buzzer": {
      "active": false,
      "pattern": "off"
    },
    "system": {
      "uptime_ms": 348950,
      "rssi_dbm": -58,
      "free_heap_bytes": 268412,
      "psram_free_bytes": 7192840,
      "cpu_temp_c": 44.5
    }
  }
}
```

### 5.2 Outbound Telemetry: `telem.status` (1 Hz)
Streamed every 1000 ms providing health, IP, and failsafe status:
```json
{
  "type": "telem.status",
  "timestamp": 1731657111000,
  "sender": "esp32",
  "seq": 451,
  "corr_id": null,
  "payload": {
    "node": "esp32",
    "wifi_connected": true,
    "ws_connected": true,
    "ip": "192.168.1.150",
    "rssi_dbm": -55,
    "failsafe_active": false,
    "estop_active": false,
    "servos": {
      "pan_angle": 90.0,
      "tilt_angle": 90.0
    },
    "uptime_ms": 349000
  }
}
```

### 5.3 Inbound Command Summary

| Command Type | Aliases | Required Payload Fields | Behavior |
| :--- | :--- | :--- | :--- |
| **Servo Move** | `cmd.servo.move`, `cmd.move` | `mode` ("absolute"/"relative"), `pan`, `tilt`, `speed` [0.1..1.0], `smooth` | Clamps angles to [15°-165°, 60°-135°] and slews servos |
| **Jog Move** | `cmd.jog` | `delta_pan` / `pan`, `delta_tilt` / `tilt`, `speed` | Increments current position by relative delta |
| **Center** | `cmd.servo.center`, `cmd.center` | `speed` [0.1..1.0] | Smoothly returns pan & tilt to calibrated center (90.0°, 90.0°); clears E-stop |
| **Emergency Stop**| `cmd.estop`, `sys.safestop` | `action` ("freeze"/"center"/"release_pwm"/"resume"), `release_pwm` | Instantly freezes servos and disables PCA9685 outputs (OE) |
| **Buzzer Control**| `cmd.buzzer` | `action` ("beep"/"chirp"/"alarm"/"pulse"/"mute"), `duration_ms`, `count` | Controls non-blocking active buzzer patterns |
| **Ping / Pong** | `sys.ping`, `ping` | `{}` | Immediately returns `sys.pong` with `echo_timestamp` and RTT |

---

## 6. Safety Policies & Fail-Safe Watchdog

### 6.1 800ms Hardware Watchdog (`Task_WatchdogSupervisor`)
- Dedicated supervisor task on Core 0 monitors time elapsed since the last valid WebSocket text frame or heartbeat.
- If elapsed time exceeds **800 ms**:
  1. Sets internal flag `g_failsafe_active = true`.
  2. Dispatches `MOTION_CMD_FREEZE` to `g_servoCmdQueue` on Core 1 (queue-based, eliminating multi-core I2C bus contention).
  3. Commands the active buzzer to sound warning alert chirps (70ms ON / 50ms OFF / 70ms ON) every 5 seconds.
  4. Flags error in telemetry packets (`telem.sensors.system.failsafe_active = true` and `telem.status.failsafe_active = true`).
  5. Dispatches an emergency `alert.event` message (`event_type: "ws_disconnect"`, `severity: "critical"`).
  6. Switches status LED (GPIO 10) to rapid 5 Hz alert strobe.

### 6.2 Watchdog Recovery
- When network communication is restored and any valid command or `sys.ping` is ingested:
  1. Internal flag `g_failsafe_active` is cleared.
  2. `MOTION_CMD_RESUME` is enqueued to Core 1 motion engine to restore normal slew processing.
  3. Warning buzzer is silenced.
  4. Telemetry error flags are cleared (`failsafe_active: false`).
  5. Status LED returns to 1 Hz slow heartbeat.

### 6.3 Ultrasonic Collision Interlock (< 20 cm)
- If the HC-SR04 measures an obstacle distance $< 20.0\text{ cm}$ (`PROXIMITY_OBSTRUCTION_CM`):
  1. Motion engine halts forward/approaching travel immediately.
  2. Buzzer emits an obstruction warning chirp.
  3. `alert.event` (`event_type: "proximity_obstruction"`, `severity: "critical"`) is dispatched.
  4. The system safely accepts `cmd.center` or jog commands steering *away* from the obstacle.

---

## 7. Compilation & Flashing Guide

### 7.1 PlatformIO Command Line Interface (CLI)

From the project root:

```powershell
# Navigate to firmware directory
cd "smartvision/firmware"

# Compile the modular Phase 3 production firmware
pio run -e smartvision_firmware

# Flash to ESP32-S3 over USB CDC
pio run -e smartvision_firmware -t upload

# Launch serial monitor at 115200 baud
pio device monitor -b 115200
```

### 7.2 Overriding Wi-Fi & Backend Credentials at Build Time

You can customize network settings without modifying source files via PlatformIO build flags:

```powershell
pio run -e smartvision_firmware --build-flag "-DWIFI_SSID=\"MyHomeWiFi\"" --build-flag "-DWIFI_PASSWORD=\"SecretKey123\"" --build-flag "-DBACKEND_HOST=\"192.168.1.50\""
```

---

## 8. Verification & Serial Monitor Traces

### 8.1 Automated Test Suite Verification

Run the automated Python test suite to verify full protocol conformance against an active mock WebSocket server:

```powershell
cd "smartvision"
py tests/test_firmware_mock_server.py
```

Expected Output:
```
================================================================================
  SMARTVISION PHASE 3: ESP32 FIRMWARE PROTOCOL & MOCK SERVER TEST SUITE
================================================================================
  [MockServer] Started listening on ws://127.0.0.1:8765/ws/device
    [MockServer] Handshake complete: ESP32 client connected to /ws/device
  [1/7] Link Handshake & RFC6455 Framing: OK
  [2/7] Verifying 10 Hz Telemetry (telem.sensors) & Schema Validation...
    - Envelope schema strictly conforms to docs/protocol.md section 3.4
    - Sub-schemas (sonar, pir, servos, buzzer, system) 100% compliant
  [3/7] Verifying Inbound Command Dispatch (cmd.move, cmd.jog, cmd.center)...
    - cmd.servo.move (absolute): Slew to Pan 120.0°, Tilt 80.0° verified
    - cmd.jog (relative delta): Pan -15° (-> 105°), Tilt +10° (-> 90°) verified
    - cmd.servo.center: Slew back to Neutral Center (90.0°, 90.0°) verified
  [4/7] Verifying Ping / Pong Synchronization & Round-Trip Timing...
    - sys.pong returned with matching corr_id and RTT = 0 ms
  [5/7] Verifying Active Buzzer Command Patterns (beep, chirp, alarm, mute)...
    - Buzzer patterns and mute command state machine verified
  [6/7] Verifying 800ms Communication Watchdog & Safe-Stop Behavior...
    - 800ms communication loss watchdog engaged FAILSAFE_ACTIVE successfully
    - Servos frozen in place; warning buzzer cadence activated
    - telem.sensors flagged error in telemetry (failsafe_active: True)
    - Communication heartbeat restored -> FAILSAFE_ACTIVE cleared to NORMAL
  [7/7] Verifying Certified Physical Boundaries & Proximity Interlock...
    - Physical limit clamping verified (Pan clamped to 165.0°, Tilt clamped to 60.0°)
    - cmd.estop immediate hardware freeze and torque release verified
    [MockServer] ESP32 client disconnected
================================================================================
  [PASS] ALL PHASE 3 FIRMWARE & MOCK SERVER PROTOCOL TESTS COMPLETED WITH 100% SUCCESS!
================================================================================
```

### 8.2 Typical Hardware Boot & Protocol Trace

When the ESP32-S3 boots with the serial monitor attached:

```
=======================================================
  SmartVision Dual-Core ESP32-S3 Firmware (Phase 3)
=======================================================
Chip Model: ESP32-S3 | Rev: 1 | Cores: 2 | Freq: 240 MHz
Free SRAM: 278912 bytes | Free PSRAM: 7192840 bytes
=======================================================

[Task_Net] Running on Core 0, Priority 1
[Task_Watchdog] Running on Core 0, Priority 4 (Watchdog: 800 ms)
[Task_Motion] Running on Core 1, Priority 3 (50 Hz / 20ms)
[Motion] Initializing PCA9685 driver on I2C...
[Motion] Servos parked at center (Pan: 90.0°, Tilt: 90.0°)
[Task_Sensors] Running on Core 1, Priority 2 (10 Hz Sensor / Buzzer)
[Sensor] Initializing HC-SR04, HC-SR501, and Buzzer drivers...
[Setup] All 4 FreeRTOS tasks initialized and pinned to dual cores successfully.

[WiFi] Connecting to 'SmartVision-AP' (backoff: 1000 ms)...
[WiFi] Connected! IP: 192.168.1.150 | RSSI: -54 dBm
[WebSocket] Connecting to ws://192.168.1.100:8000/ws/device
[WebSocket] Connected to: /ws/device
[Task_Net] WebSocket link established with backend!
[Watchdog] Connected. Watchdog armed.
[Protocol] Ingested cmd.servo.move -> Pan: 120.0°, Tilt: 80.0°
[Protocol] Valid message received. Failsafe cleared -> NORMAL operation.
```
