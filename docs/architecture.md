# SmartVision: End-to-End System Architecture

**Document Version:** 1.0.0 (Phase 0 Baseline)  
**Author:** SmartVision Engineering Team  
**Target Platform:** ESP32-S3 N16R8, PCA9685, Dual-Axis Pan-Tilt Gimbal, PC Vision Host (FastAPI + YOLOv8n), Next.js Dashboard  
**Status:** Approved Architectural Specification  

---

## 1. System Overview & Topological Architecture

SmartVision is an autonomous, vision-guided 2-DOF (Degree-of-Freedom) pan-tilt tracking and surveillance system. The architecture separates hard real-time actuator control and low-level sensor acquisition from high-throughput deep learning inference and web orchestration.

### 1.1 Architectural Topology

The overall system is structured across three primary tiers:
1. **Edge Actuation & Telemetry Tier (ESP32-S3 Embedded Subsystem):** Direct hardware interfacing, PCA9685 PWM driving, HC-SR04 distance measurement, HC-SR501 PIR motion sensing, buzzer alert generation, and a hardware watchdog fail-safe.
2. **PC Vision & Central Hub Tier (FastAPI Backend & Python CV Engine):** Local high-throughput video capture (DirectShow/UVC), YOLOv8n person detection, ByteTrack multi-object tracking, dual-axis PID tracking control with deadband and EMA filtering, MJPEG streaming broadcast, and WebSocket message arbitration.
3. **Operator Presentation Tier (Next.js 14+ Web Dashboard):** Real-time live video display, synchronized HTML5 Canvas bounding box and reticle overlay, click-to-lock target selection, manual pan/tilt jogging, telemetry gauges, and an emergency stop interface.

```
                      +-------------------------------------------------+
                      |                 Next.js Frontend                |
                      |             (Operator Web Dashboard)            |
                      +-------------------------------------------------+
                                       |              ^
                     HTTP GET (MJPEG)  |              | WebSocket
                 /api/v1/stream/video  |              | /ws/client
                                       v              v
+---------------------------------------------------------------------------------------+
|                                    FastAPI Backend                                    |
|                                (PC Central Vision & Hub)                              |
|                                                                                       |
|  [USB Webcam Ingestion] ---> [YOLOv8 Person Tracker] ---> [Tracking State Machine]   |
|                                                                    |                  |
|  [MJPEG Streamer Engine] <-----------------------------------------+                  |
|                                                                    |                  |
|  [REST Status & Config]      [Safety & Command Arbiter] <----------+                  |
+---------------------------------------------------------------------------------------+
                                       ^
                                       | WebSocket
                                       | /ws/device
                                       v
                      +-------------------------------------------------+
                      |                ESP32-S3 Firmware                |
                      |          (FreeRTOS / Arduino / ESP-IDF)         |
                      |                                                 |
                      |   - PCA9685 I2C (Pan MG996R, Tilt MG90S)        |
                      |   - HC-SR04 Ultrasonic Trigger / Echo           |
                      |   - HC-SR501 PIR Digital Input                  |
                      |   - Active 5V Buzzer Transistor Driver          |
                      |   - 800ms Hardware Safety Watchdog Task         |
                      +-------------------------------------------------+
                                       |
                                       | I2C Bus (SDA GPIO 8, SCL GPIO 9, Addr 0x40)
                                       v
                              +------------------+
                              | PCA9685 Driver   | <--- External 5V 5A Supply
                              +--------+---------+
                                       |
                     +-----------------+-----------------+
                     |                                   |
                     v                                   v
             [ MG996R Pan Servo ]               [ MG90S Tilt Servo ]
              (Ch 0: 15° - 165°)                 (Ch 1: 60° - 135°)
```

---

## 2. Edge Actuation & Telemetry Tier (ESP32-S3 Subsystem)

### 2.1 Microcontroller Configuration & Dual-Core Affinity
The ESP32-S3 N16R8 features dual Xtensa 32-bit LX7 cores operating at 240 MHz, with 16 MB SPI Flash and 8 MB Octal PSRAM (OPI). To guarantee hard real-time actuator control without timing jitter induced by Wi-Fi packet processing and TCP retransmissions, tasks are partitioned across cores using FreeRTOS:

- **Core 0 (Networking & Communication Hub)**:
  - `WiFi_WS_Task` (Priority 1, Stack: 8192 bytes): Manages Wi-Fi association, DHCP maintenance, WebSocket client connection (`/ws/device`), incoming JSON deserialization, and outgoing telemetry dispatch.
- **Core 1 (Deterministic Control & Real-Time Safety)**:
  - `Watchdog_Failsafe_Task` (Priority 4 [Highest], Stack: 2048 bytes): Monitors communication freshness, executes the 800ms hardware watchdog, and coordinates safe-stop routines.
  - `Servo_Control_Task` (Priority 3, Stack: 4096 bytes): Consumes commanded target angles from the queue, performs 50 Hz discrete slew rate interpolation, clamps angles to mechanical limits, and writes 12-bit register values to the PCA9685 via I2C.
  - `Sensor_Polling_Task` (Priority 2, Stack: 4096 bytes): Executes 10 Hz non-blocking HC-SR04 ultrasonic distance acquisition, samples HC-SR501 PIR digital input, drives active buzzer alert patterns, and pushes sensor snapshots to `TelemetryQueue`.

### 2.2 FreeRTOS Inter-Task Communication Primitives
- `xServoCommandQueue` (Depth = 5, item type `ServoCommand_t`): Overwrite-enabled command buffer ensuring stale movement commands are dropped.
- `xTelemetryQueue` (Depth = 5, item type `TelemetryData_t`): Thread-safe FIFO staging aggregated sensor data for WebSocket dispatch.
- `xI2CMutex`: Mutex protecting Hardware I2C Controller 0 (`I2C_NUM_0`).
- `xSystemEventGroup`: Event flags for `WIFI_CONNECTED_BIT`, `WS_CONNECTED_BIT`, `FAILSAFE_ACTIVE_BIT`, and `PROXIMITY_ALARM_BIT`.

### 2.3 PCA9685 12-Bit PWM Controller Interfacing
The PCA9685 is addressed over I2C at `0x40`. At a 50 Hz PWM frequency ($T = 20\text{ ms} = 20,000\ \mu\text{s}$), the 12-bit counter ($4096$ ticks) yields:
$$t_{\text{tick}} = \frac{20,000\ \mu\text{s}}{4096} \approx 4.8828125\ \mu\text{s/tick}$$

Standard RC servo pulses ($500\ \mu\text{s} - 2500\ \mu\text{s}$) translate to counts via:
$$\text{Count}(t_{\mu\text{s}}) = \text{round}\left(\frac{t_{\mu\text{s}}}{4.8828125}\right)$$

- $0^\circ \rightarrow 500\ \mu\text{s} \rightarrow 102\text{ ticks}$
- $90^\circ \rightarrow 1500\ \mu\text{s} \rightarrow 307\text{ ticks}$ (Neutral center)
- $180^\circ \rightarrow 2500\ \mu\text{s} \rightarrow 512\text{ ticks}$

---

## 3. PC Computer Vision & Central Hub Tier

### 3.1 Multi-Threaded Vision Pipeline Architecture
To maintain a consistent 30 FPS inference and tracking loop without I/O stalls, the vision engine uses a decoupled multi-threaded pipeline:

1. **Capture Thread (`VideoCaptureThread`)**: Uses OpenCV DirectShow (`cv2.CAP_DSHOW`) on Windows with a single-frame buffer (`CAP_PROP_BUFFERSIZE = 1`). Overwrite policy guarantees zero frame lag.
2. **Inference Thread (`VisionInferenceThread`)**: Runs YOLOv8n person detection (`classes=[0]`) at $640 \times 480$ resolution, applies ByteTrack for persistent ID tracking, computes target centroid, evaluates dead-band thresholds, and executes dual-axis PID controllers.
3. **Stream Encoding Thread (`StreamEncoderThread`)**: Overlays bounding boxes, crosshairs, and tracking HUD, encodes frames to JPEG (quality 80%), and pushes them to the shared MJPEG broadcast queue.

### 3.2 Dual-Axis PID Control Formulation
For each tracking axis (Pan and Tilt):
$$\text{Centroid:}\quad x_c = \frac{x_1 + x_2}{2},\quad y_c = \frac{y_1 + y_2}{2}$$
$$\text{Frame Center:}\quad x_0 = \frac{W}{2} = 320,\quad y_0 = \frac{H}{2} = 240$$
$$\text{Raw Error:}\quad \epsilon_x = x_c - x_0,\quad \epsilon_y = y_c - y_0$$

#### Dual-Threshold Hysteresis Deadband:
$$\text{deadband\_x} = 
\begin{cases} 
0 & \text{if } |\epsilon_x| \le 15\text{ px} \\
\epsilon_x & \text{if } |\epsilon_x| \ge 25\text{ px} \\
\text{previous\_state} & \text{otherwise}
\end{cases}$$

#### Exponential Moving Average (EMA) Low-Pass Filter:
$$e_{x,\text{filtered}}[k] = \alpha \cdot \text{deadband\_x}[k] + (1 - \alpha) \cdot e_{x,\text{filtered}}[k-1] \quad (\alpha = 0.35)$$

#### PID Controller with Anti-Windup:
$$P(k) = K_p \times e(k)$$
$$I(k) = \text{clamp}\left(I(k-1) + K_i \times e(k) \times \Delta t,\ -I_{\text{max}},\ +I_{\text{max}}\right)$$
$$D(k) = K_d \times \frac{e(k) - e(k-1)}{\Delta t}$$
$$\Delta \theta(k) = \text{clamp}\left(P(k) + I(k) + D(k),\ -\Delta \theta_{\text{max}},\ +\Delta \theta_{\text{max}}\right)$$

**Tuned Baseline Parameters:**
- **Pan Axis:** $K_p = 0.04^\circ/\text{px}$, $K_i = 0.005^\circ/(\text{px}\cdot\text{s})$, $K_d = 0.008^\circ\cdot\text{s}/\text{px}$, $I_{\text{max}} = 5.0^\circ$, $\Delta \theta_{\text{max}} = 3.0^\circ/\text{frame}$.
- **Tilt Axis:** $K_p = 0.03^\circ/\text{px}$, $K_i = 0.003^\circ/(\text{px}\cdot\text{s})$, $K_d = 0.006^\circ\cdot\text{s}/\text{px}$, $I_{\text{max}} = 3.0^\circ$, $\Delta \theta_{\text{max}} = 2.0^\circ/\text{frame}$.

### 3.3 Target Reacquisition & Coasting Logic
- **Coasting Phase ($0 < t_{\text{lost}} \le 400\text{ ms}$)**: Decays last commanded angular velocity by $\gamma = 0.7$ per frame to smoothly follow momentary occlusions.
- **Hold Phase ($400\text{ ms} < t_{\text{lost}} \le 2000\text{ ms}$)**: Velocity set to 0. Servos hold position while searching for re-emergence.
- **Timeout Return ($t_{\text{lost}} > 5000\text{ ms}$)**: Resets tracking state and smoothly slews pan/tilt back to calibrated center ($90^\circ, 90^\circ$).

---

## 4. Backend & Web Gateway Tier (FastAPI)

FastAPI serves as the centralized asynchronous gateway and arbitration switchboard:
- `/ws/device`: WebSocket connection dedicated to ESP32-S3 firmware. Ingests high-rate telemetry (10 Hz) and transmits validated servo actuation commands.
- `/ws/client`: WebSocket connection for operator Next.js dashboards. Broadcasts telemetry, detections, alerts, and accepts operator manual jog/click-to-lock commands.
- `/api/v1/stream/video.mjpeg`: HTTP multipart MJPEG stream endpoint consumable by HTML5 `<img>` tags.
- `SystemStateManager`: Thread-safe, asyncio-locked state repository arbitrating manual operator overrides vs. autonomous CV tracking commands.

---

## 5. Hardware Component Compatibility & Technical Limitations

### 5.1 ESP32-S3 N16R8 Silicon Constraints
- **Octal PSRAM Pin Reservation:** GPIO 33, 34, 35, 36, and 37 are internally dedicated to the high-speed Octal PSRAM bus. Accessing these pins causes instantaneous cache crashes and kernel panics. They are strictly excluded from external wiring.
- **Flash Bus Reservation:** GPIO 26 through 32 are internally wired to SPI Flash and reserved.
- **Strapping Pins:** GPIO 0, 3, 45, and 46 dictate boot modes. They are kept free of external pull-up/pull-down loads that could interfere with power-up.
- **Voltage Tolerance:** Inputs are rated for 3.3V logic (absolute maximum 3.6V). **Pins are NOT 5V tolerant.**

### 5.2 MG996R & MG90S Servos
- **MG996R (Pan):** Metal gears, stall current up to 2.5 A at 5V, 9.4 kg·cm torque. Mechanical limit clamped to $15^\circ - 165^\circ$ to prevent camera USB cable twisting and chassis collision.
- **MG90S (Tilt):** Metal gears, stall current up to 0.85 A at 5V, 1.8 kg·cm torque. Mechanical limit clamped to $60^\circ - 135^\circ$ to prevent gimbal camera strike against pan bracket.

### 5.3 HC-SR04 Ultrasonic Sensor
- Requires 5V $V_{CC}$ for 40 kHz piezo transducers.
- Trigger pin accepts 3.3V logic ($V_{IH} \ge 2.0\text{ V}$).
- **Echo pin outputs a 5.0V pulse.** Direct connection to ESP32-S3 GPIO destroys the input pin. A passive resistor voltage divider ($1\text{ k}\Omega / 2\text{ k}\Omega$ or $2\text{ k}\Omega / 3.3\text{ k}\Omega$) steps down the echo voltage to a safe $3.11\text{ V} - 3.33\text{ V}$ with negligible rise-time delay (29 ns).

### 5.4 HC-SR501 PIR Motion Sensor
- Powered from 5V rail. Onboard 7133-1 LDO powers internal circuitry at 3.3V.
- Output signal is native **3.3V TTL logic**, directly compatible with ESP32-S3 input.
- High-power 2.4 GHz RF bursts from the ESP32-S3 Wi-Fi antenna can induce false PIR triggers. Minimum 15 cm physical separation or copper foil shielding on the sensor back is required.

### 5.5 Active 5V Buzzer
- Draws 35–45 mA at 5V. Sourcing directly from an ESP32 GPIO (max 20 mA recommended) causes voltage sag and port degradation.
- Switched via a low-side 2N2222 NPN transistor ($R_B = 1.0\text{ k}\Omega$).
- Inductive turn-off kickback is clamped via an antiparallel 1N4148 diode across buzzer terminals.

### 5.6 Power Distribution & Worst-Case Stall Budget
- External 5V 5A regulated DC power supply provides 25W continuous power.
- Combined worst-case peak stall load:
  $$\text{MG996R Stall: } 2.50\text{ A} + \text{MG90S Stall: } 0.80\text{ A} + \text{ESP32 Wi-Fi Peak: } 0.45\text{ A} + \text{Peripherals: } 0.07\text{ A} = 3.82\text{ A}$$
- **Headroom Margin:** $5.00\text{ A} - 3.82\text{ A} = 1.18\text{ A}$ ($23.6\%$ spare capacity).
- Typical dynamic operating current: $\approx 1.30\text{ A}$ (26% load).
- Power rail transient suppression: $1000\ \mu\text{F}$ low-ESR electrolytic capacitor across PCA9685 $V+$ and GND terminals.
- **Common Ground Bonding:** All GND lines (Power Supply, PCA9685, ESP32-S3) are solidly bonded to prevent floating reference offsets.

---

## 6. System Fail-Safe Policies & Operational Safeguards

| Trigger Condition | Detection Mechanism | Latency / Timeout | System Response & Action | Recovery Procedure |
|---|---|---|---|---|
| **ESP32 WebSocket Disconnection** | TCP disconnect callback or lack of heartbeat ping/pong on ESP32 | **800 ms** threshold | ESP32 enters `SAFETY_SAFE_STOP`. All servo motion halts instantly. Buzzer sounds 2 short warning chirps. | ESP32 enters reconnection backoff loop (1s, 2s, 4s, max 10s). Re-syncs center position upon reconnect. |
| **Operator Frontend Disconnect** | Backend WebSocket `/ws/client` closure | **Immediate (0 ms)** | Backend switches mode to `IDLE`. Any active manual motion is halted (`speed: 0`). Auto-tracking pauses. | When frontend reconnects, dashboard receives full system state synchronization. |
| **Stale Tracking Data** | Target timestamp check: `now() - timestamp_captured > 300ms` | **300 ms** threshold | Backend halts auto-tracking velocity calculation. Holds last commanded angle. Status set to `TRACKING_STALE`. | Automatically resumes when fresh frames ($<150\text{ms}$ old) arrive with valid bounding box. |
| **Complete Target Loss** | YOLO detector fails to find tracked person ID for consecutive frames | **> 2000 ms** threshold | Transitions to `TARGET_SEARCH`. After **5000 ms**, servos gently return to calibrated Center (`90°`, `90°`). | Reacquires lock when person enters frame and meets confidence $>0.60$. |
| **Camera Disconnect / UVC Drop** | `cv2.VideoCapture.read()` returns `False` or hangs $>1000\text{ms}$ | **1000 ms** threshold | Backend broadcasts `alert.event` (Critical: `camera_offline`). Dispatches `sys.safestop` to ESP32. UI shows camera error overlay. | Backend spawns camera auto-recovery thread attempting device reopen every 3000ms. |
| **Out-of-Bounds Command** | Pydantic schema validator (Backend) & angle clamp (ESP32) | **Immediate (<1 ms)** | Backend rejects request with `400 / ERR_OUT_OF_BOUNDS`. ESP32 hard-clamps PCA9685 PWM pulses. | Clamp ensures hardware never exceeds physical mechanical travel limits. |
| **Close Proximity Obstacle** | HC-SR04 sonar reading $< 20.0\text{ cm}$ | **50 ms** (1 sensor cycle) | Motion inhibited in forward tilt. Buzzer pulses rapid warning alarm. UI displays obstruction alert. | Clears automatically when obstacle distance exceeds 25.0 cm (5 cm hysteresis). |

---

## 7. Next.js Operator Dashboard Architecture

### 7.1 Component Architecture
```
DashboardLayout (src/app/layout.tsx)
└── SmartVisionDashboard (src/app/page.tsx)
    ├── StatusHeader
    │   ├── ConnectionBadges (Firmware, Vision, Backend, WebSocket Ping)
    │   └── EmergencyStopButton (E-Stop Trigger)
    ├── MainDisplayGrid
    │   ├── VideoViewportContainer
    │   │   ├── VideoPlayer (`<img src="/api/v1/stream/video.mjpeg" />`)
    │   │   └── CanvasOverlay (HTML5 Canvas overlay for BBoxes & Click-to-Lock)
    │   └── ControlTelemetrySidebar
    │       ├── ModeSelectorTab (Manual / Auto-Track / Patrol / Standby)
    │       ├── PanTiltControls (Virtual Joystick, 4-Way D-Pad, Angle Sliders, Center Home)
    │       ├── TelemetryCards (Sonar distance bar, PIR motion indicator, Servo angles)
    │       └── EventLogTable (Real-time chronological audit trail)
```

### 7.2 HTML5 Canvas Overlay & Click-to-Lock
The `<canvas>` overlay maps bounding boxes $[x_1, y_1, x_2, y_2]$ from camera space ($640 \times 480$) to browser viewport coordinates. When the operator clicks on a detected bounding box:
1. Canvas hit-test identifies the clicked bounding box.
2. Dashboard dispatches `track.select_id` with target `track_id` over `/ws/client`.
3. Backend anchors ByteTrack exclusively to that ID.
4. Active target is rendered with a neon cyan reticle, while passive detections remain neutral slate.
