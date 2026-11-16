# SmartVision: Communication Protocol Specification

**Document Version:** 1.0.0 (Phase 0 Baseline)  
**Author:** SmartVision Engineering Team  
**Scope:** WebSocket Framing, JSON Envelopes, Message Schemas, Safety Watchdogs, and Smoothing Algorithms  
**Status:** Approved Protocol Specification  

---

## 1. Network Topology & Endpoint Definitions

The SmartVision system employs a **Centralized Gateway Topology** mediated by the PC-hosted FastAPI backend. Direct client-to-firmware connections are avoided to eliminate embedded resource contention, multi-client synchronization bugs, and unsecured command arbitration.

```
                     +-------------------------------------------------+
                     |                 Next.js Frontend                |
                     |           (Operator Web Dashboard)              |
                     +-------------------------------------------------+
                                       |              ^
                     HTTP GET (MJPEG)  |              | WebSocket
                  /api/v1/stream/video |              | /ws/client
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
```

### 1.1 HTTP Endpoints
- `GET /api/v1/stream/video.mjpeg`: Primary HTTP chunked multipart stream (`multipart/x-mixed-replace; boundary=frame`). Consumable natively by browser `<img>` tags.
- `GET /api/v1/health`: Returns JSON health snapshot of camera frame rate, vision pipeline state, and connected nodes.

### 1.2 WebSocket Endpoints
- `ws://<host>:8000/ws/client`: Dedicated full-duplex JSON endpoint for Next.js operator dashboards. Ingests operator commands and broadcasts real-time telemetry, object detections, and system alert notifications.
- `ws://<host>:8000/ws/device`: Dedicated full-duplex JSON endpoint for the ESP32-S3 microcontroller. Ingests 10 Hz sensor snapshots and issues arbitrated PCA9685 servo actuation commands.

---

## 2. Standard Message Envelope

All WebSocket messages conform to a uniform typed JSON envelope. Timestamps are 64-bit integer Unix milliseconds (`uint64`) to eliminate heap-intensive ISO-8601 string parsing on the ESP32-S3.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "SmartVisionEnvelope",
  "type": "object",
  "required": ["type", "timestamp", "sender", "seq", "payload"],
  "properties": {
    "type": {
      "type": "string",
      "description": "Dot-delimited message type identifier.",
      "enum": [
        "sys.ping",
        "sys.pong",
        "sys.safestop",
        "sys.status",
        "cmd.servo.move",
        "cmd.servo.center",
        "cmd.servo.patrol",
        "cmd.buzzer",
        "telem.sensors",
        "track.frame_target",
        "track.mode_set",
        "track.select_id",
        "alert.event"
      ]
    },
    "timestamp": {
      "type": "integer",
      "minimum": 0,
      "description": "UTC Unix epoch timestamp in milliseconds."
    },
    "sender": {
      "type": "string",
      "enum": ["frontend", "backend", "esp32"],
      "description": "Originating node identifier."
    },
    "seq": {
      "type": "integer",
      "minimum": 0,
      "maximum": 4294967295,
      "description": "Monotonically increasing 32-bit sequence number per sender."
    },
    "corr_id": {
      "type": ["string", "null"],
      "description": "Optional correlation UUID to link responses/acknowledgments to commands."
    },
    "payload": {
      "type": "object",
      "description": "Type-specific message payload body."
    }
  }
}
```

---

## 3. Complete WebSocket Message Schemas

### 3.1 Servo Movement Command (`cmd.servo.move`)
Direction: `frontend` $\rightarrow$ `backend` $\rightarrow$ `esp32`

```json
{
  "type": "cmd.servo.move",
  "timestamp": 1731657100000,
  "sender": "frontend",
  "seq": 101,
  "corr_id": "c7a8b3d2-45e1-4b77-8c3e-908123456789",
  "payload": {
    "mode": "absolute",
    "pan": 90.0,
    "tilt": 90.0,
    "speed": 0.5,
    "step_deg": 5.0,
    "smooth": true
  }
}
```

#### Field Specifications & Constraints:
- `mode` (`string`, required): `"absolute"` or `"relative"`.
- `pan` (`number`, required):
  - In `"absolute"` mode: Target azimuth angle in degrees. Permitted range: `15.0` to `165.0` (Center: `90.0°`).
  - In `"relative"` mode: Relative jog increment in degrees. Permitted range: `-45.0` to `+45.0`.
- `tilt` (`number`, required):
  - In `"absolute"` mode: Target elevation angle in degrees. Permitted range: `60.0` to `135.0` (Center: `90.0°`).
  - In `"relative"` mode: Relative jog increment in degrees. Permitted range: `-30.0` to `+30.0`.
- `speed` (`number`, optional, default `0.5`): Normalized velocity factor in range `[0.1, 1.0]`, mapping to $10^\circ/\text{s}$ to $120^\circ/\text{s}$.
- `step_deg` (`number`, optional, default `5.0`): Step size used for D-pad jog increments.
- `smooth` (`boolean`, optional, default `true`): Enables FreeRTOS slew-rate interpolation on the ESP32.

---

### 3.2 Servo Center Command (`cmd.servo.center`)
Direction: `frontend` $\rightarrow$ `backend` $\rightarrow$ `esp32`

```json
{
  "type": "cmd.servo.center",
  "timestamp": 1731657102000,
  "sender": "frontend",
  "seq": 102,
  "corr_id": "e9b21f34-118b-4a52-b883-fa4192019284",
  "payload": {
    "speed": 0.4
  }
}
```
**Behavior:** Immediately slews Pan to `90.0°` and Tilt to `90.0°` at the specified speed.

---

### 3.3 Servo Patrol Sweep Command (`cmd.servo.patrol`)
Direction: `frontend` $\rightarrow$ `backend` $\rightarrow$ `esp32`

```json
{
  "type": "cmd.servo.patrol",
  "timestamp": 1731657105000,
  "sender": "frontend",
  "seq": 103,
  "corr_id": null,
  "payload": {
    "enabled": true,
    "pan_min": 30.0,
    "pan_max": 150.0,
    "tilt_angle": 90.0,
    "speed_deg_s": 20.0,
    "dwell_time_ms": 1000
  }
}
```

#### Field Specifications:
- `enabled` (`boolean`, required): `true` initiates back-and-forth oscillation; `false` halts patrol at current angle.
- `pan_min` (`number`, required): Lower azimuth sweep bound (`15.0` to `80.0°`).
- `pan_max` (`number`, required): Upper azimuth sweep bound (`100.0` to `165.0°`).
- `tilt_angle` (`number`, required): Static elevation during sweep (`60.0` to `135.0°`).
- `speed_deg_s` (`number`, required): Sweep velocity in deg/sec (`5.0` to `45.0`).
- `dwell_time_ms` (`integer`, optional, default `1000`): Dwell pause duration at sweep endpoints.

---

### 3.4 Sensor Telemetry Message (`telem.sensors`)
Direction: `esp32` $\rightarrow$ `backend` $\rightarrow$ `frontend`  
Frequency: 10 Hz (every 100 ms)

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

#### Field Specifications:
- `sonar.distance_cm`: Non-blocking HC-SR04 distance measurement. Range: `2.0` to `400.0` cm. Returns `-1.0` if echo timed out.
- `sonar.status`: `"in_range"`, `"out_of_range"`, or `"timeout"`.
- `pir.motion_detected`: Boolean indicating current digital pin level of HC-SR501.
- `servos.pan_angle` / `tilt_angle`: Estimated real-time servo shaft positions based on slew interpolation.
- `system.rssi_dbm`: Wi-Fi signal strength in dBm (`-100` to `0`).

---

### 3.5 Tracking Coordinates & Target Selection (`track.frame_target`)
Direction: `backend` $\rightarrow$ `frontend` & (`Internal Controller` $\rightarrow$ `esp32`)  
Frequency: 25 Hz to 30 Hz (Synchronous with YOLO inference output)

```json
{
  "type": "track.frame_target",
  "timestamp": 1731657115200,
  "sender": "backend",
  "seq": 1820,
  "corr_id": null,
  "payload": {
    "frame_id": 14205,
    "timestamp_captured": 1731657115160,
    "timestamp_processed": 1731657115198,
    "latency_ms": 38.0,
    "frame_dimensions": {
      "width": 640,
      "height": 480
    },
    "tracking_mode": "auto_track",
    "target_locked": true,
    "active_target": {
      "track_id": 4,
      "class_name": "person",
      "confidence": 0.89,
      "bbox": [180, 95, 340, 420],
      "bbox_normalized": [0.281, 0.198, 0.531, 0.875],
      "centroid": [260.0, 257.5],
      "centroid_normalized": [0.406, 0.536],
      "error_px": [-60.0, 17.5],
      "in_deadband": false,
      "commanded_delta_deg": {
        "pan": -2.4,
        "tilt": 0.5
      }
    },
    "all_detections": [
      {
        "track_id": 4,
        "class_name": "person",
        "confidence": 0.89,
        "bbox": [180, 95, 340, 420],
        "is_primary": true
      },
      {
        "track_id": 7,
        "class_name": "person",
        "confidence": 0.67,
        "bbox": [480, 140, 590, 390],
        "is_primary": false
      }
    ]
  }
}
```

---

### 3.6 Tracking Mode Configuration (`track.mode_set`)
Direction: `frontend` $\rightarrow$ `backend`

```json
{
  "type": "track.mode_set",
  "timestamp": 1731657120000,
  "sender": "frontend",
  "seq": 105,
  "corr_id": "f12c8401-6b4d-4933-911e-0129a09efb44",
  "payload": {
    "mode": "auto_track",
    "target_selection": "primary",
    "deadband_px": 20,
    "smoothing_factor": 0.35,
    "reacquisition_timeout_ms": 3000
  }
}
```

#### Field Specifications:
- `mode` (`string`, required): `"manual"`, `"auto_track"`, `"patrol"`, or `"idle"`.
- `target_selection`: `"primary"` (largest/highest confidence person), `"center_closest"`, or a specific integer `track_id`.

---

### 3.7 Target Selection by Track ID (`track.select_id`)
Direction: `frontend` $\rightarrow$ `backend`

```json
{
  "type": "track.select_id",
  "timestamp": 1731657125000,
  "sender": "frontend",
  "seq": 106,
  "corr_id": null,
  "payload": {
    "track_id": 7
  }
}
```

---

### 3.8 Alert Event Notification (`alert.event`)
Direction: `backend` / `esp32` $\rightarrow$ `frontend`

```json
{
  "type": "alert.event",
  "timestamp": 1731657130000,
  "sender": "backend",
  "seq": 78,
  "corr_id": null,
  "payload": {
    "event_id": "evt_98124_prox",
    "event_type": "proximity_obstruction",
    "severity": "critical",
    "source": "esp32",
    "message": "Obstacle detected 12.5 cm from camera (Threshold: 20.0 cm). Servo motion inhibited.",
    "telemetry_snapshot": {
      "distance_cm": 12.5,
      "threshold_cm": 20.0,
      "pan_angle": 90.0,
      "tilt_angle": 90.0
    },
    "action_taken": "motion_inhibited",
    "buzzer_activated": true
  }
}
```

#### Allowed `event_type` Values:
- `"motion_alarm"`: PIR sensor detected body movement in armed zone.
- `"proximity_warning"`: Sonar reading between 20.0 cm and 40.0 cm.
- `"proximity_obstruction"`: Sonar reading $< 20.0\text{ cm}$ (Critical).
- `"stale_tracking"`: Target lost or frame latency $> 300\text{ ms}$.
- `"camera_offline"`: UVC webcam stream disconnected.
- `"ws_disconnect"`: WebSocket connection timeout.
- `"boundary_violation"`: Out-of-bounds servo angle rejected.

---

### 3.9 Buzzer Control Command (`cmd.buzzer`)
Direction: `frontend` / `backend` $\rightarrow$ `esp32`

```json
{
  "type": "cmd.buzzer",
  "timestamp": 1731657135000,
  "sender": "backend",
  "seq": 107,
  "corr_id": "b3e810a9-1982-45e0-91cd-32810a442e91",
  "payload": {
    "action": "beep",
    "duration_ms": 150,
    "count": 3,
    "interval_ms": 100
  }
}
```

---

### 3.10 Heartbeat Ping / Pong (`sys.ping` / `sys.pong`)
Direction: Bidirectional between `frontend` $\leftrightarrow$ `backend` and `backend` $\leftrightarrow$ `esp32`  
Interval: Every 500 ms

**Ping:**
```json
{
  "type": "sys.ping",
  "timestamp": 1731657140000,
  "sender": "backend",
  "seq": 890,
  "corr_id": "ping_890",
  "payload": {}
}
```

**Pong:**
```json
{
  "type": "sys.pong",
  "timestamp": 1731657140018,
  "sender": "esp32",
  "seq": 4560,
  "corr_id": "ping_890",
  "payload": {
    "echo_timestamp": 1731657140000,
    "rtt_ms": 18
  }
}
```

---

### 3.11 Safe-Stop Emergency Halt (`sys.safestop`)
Direction: `frontend` / `backend` $\rightarrow$ `esp32`

```json
{
  "type": "sys.safestop",
  "timestamp": 1731657145000,
  "sender": "backend",
  "seq": 9999,
  "corr_id": "e_stop_critical_01",
  "payload": {
    "reason": "ws_disconnect",
    "action": "freeze",
    "release_pwm": false,
    "details": "Communication watchdog timeout elapsed without heartbeat."
  }
}
```

#### Action Options:
- `"freeze"`: Instantly holds current servo positions with active torque.
- `"center"`: Smoothly slews pan/tilt back to calibrated center ($90.0^\circ, 90.0^\circ$).
- `"release_pwm"`: Sets PCA9685 PWM pulse output to 0, depowering servo coils to prevent motor burnout.

---

## 4. Safety Policies & Fail-Safe Specifications

### 4.1 800ms Hardware Watchdog (ESP32-S3)
- An isolated FreeRTOS timer task (`Watchdog_Failsafe_Task`, priority 4) checks time since last valid command or `sys.ping`.
- If elapsed time exceeds **800 ms**:
  1. Sets internal flag `FAILSAFE_ACTIVE_BIT`.
  2. Freezes servo position instantly.
  3. Commands the active buzzer to emit two short warning chirps ($100\text{ ms}$).
  4. Enters connection retry state with exponential backoff (1s, 2s, 4s, up to 10s).

### 4.2 300ms Stale Tracking Data Safeguard (Backend)
- In `auto_track` mode, every vision frame carries `timestamp_captured`.
- If `now() - timestamp_captured > 300 ms`:
  - Vision engine flags target coordinates as stale.
  - Commanded PID angular velocity is clamped to $0.0^\circ/\text{s}$.
  - System enters coasting/hold phase to prevent runaway velocity jumps during inference frame drops.

### 4.3 Camera Disconnect Fail-Safe
- If `cv2.VideoCapture.read()` returns `False` or hangs for $> 1000\text{ ms}$:
  - Backend broadcasts `alert.event` (`camera_offline`, severity `critical`).
  - Dispatches `sys.safestop` to the ESP32.
  - Spawns background auto-recovery thread polling device index every 3000 ms.

### 4.4 Two-Tier Angle Clamping
- **Tier 1 (Backend Pydantic Schema):** Any API or WebSocket command requesting $\theta_{\text{pan}} \notin [15^\circ, 165^\circ]$ or $\theta_{\text{tilt}} \notin [60^\circ, 135^\circ]$ is immediately rejected with HTTP 400 / `ERR_OUT_OF_BOUNDS`.
- **Tier 2 (ESP32 Firmware Clamp):** Even if a command bypasses backend validation, the ESP32 `Servo_Control_Task` strictly clamps input values before calculating PCA9685 register ticks:
  $$\text{ticks}_{\text{pan}} = \text{clamp}(\text{ticks}_{\text{pan}},\ 137,\ 478)$$
  $$\text{ticks}_{\text{tilt}} = \text{clamp}(\text{ticks}_{\text{tilt}},\ 239,\ 410)$$

---

## 5. Anti-Jitter and Motion Smoothing Algorithms

Directly converting raw pixel centroids into servo positions causes audible acoustic buzzing, high stall currents, and camera vibration. A three-stage filtering pipeline eliminates jitter:

```
[Raw YOLO BBox (x1, y1, x2, y2)]
               |
               v
    [Centroid Extraction: cx, cy]
               |
               v
    [Dual-Threshold Hysteresis Dead-Band]
    |--> If error < 15px: error = 0
    |--> If error > 25px: error active
               |
               v
    [Exponential Moving Average (EMA) Low-Pass Filter]
    C_filtered = alpha * C_raw + (1 - alpha) * C_filtered_prev  (alpha = 0.35)
               |
               v
    [Proportional Velocity & Step Limiter]
    delta_angle = clamp(Kp * error, -MAX_STEP, +MAX_STEP)
               |
               v
    [PCA9685 Angle Slew Interpolator (ESP32-S3)]
```

1. **Dual-Threshold Hysteresis Deadband:**
   - Inner threshold: $\pm 15\text{ px}$. If centroid error is within inner threshold, output error is $0$.
   - Outer threshold: $\pm 25\text{ px}$. Movement is only triggered if error exceeds outer threshold. Once active, tracking continues until error drops below inner threshold.
2. **Exponential Moving Average (EMA) Filter:**
   $$e_{\text{filtered}}[k] = \alpha \cdot e_{\text{deadband}}[k] + (1 - \alpha) \cdot e_{\text{filtered}}[k-1] \quad (\alpha = 0.35)$$
3. **Proportional Velocity Limiting:**
   $$\Delta \theta = \text{clamp}\left(K_p \cdot e_{\text{filtered}},\ -\Delta \theta_{\text{max}},\ +\Delta \theta_{\text{max}}\right)$$
   Where $K_p = 0.04^\circ/\text{px}$ and $\Delta \theta_{\text{max}} = 3.0^\circ/\text{frame}$ ($75^\circ/\text{s}$ at 25 FPS).
