# SmartVision: API & WebSocket Protocol Reference Manual

**Document Version:** 1.0.0 (Production Release)  
**Phase:** 9 — Production Documentation, Packaging & Final Handover  
**Scope:** REST Endpoints, OpenAPI 3.1 Specification, Full-Duplex WebSockets, Message Schemas & Error Protocols  
**Status:** Certified Final Specification  

---

## 1. Overview & Architecture

The SmartVision Central Gateway (FastAPI) provides high-performance, asynchronous orchestration between the PC Computer Vision engine, the Next.js Operator Dashboard, and the physical ESP32-S3 embedded microcontroller.

```
                         ┌────────────────────────────────────────────────────────┐
                         │              OPERATOR DASHBOARD (Next.js)             │
                         └───────────────────────▲──┬─────────────────────────────┘
                                                 │  │ WebSocket (/ws/client)
                                HTTP MJPEG Stream │  │ REST API (/api/v1/*)
                           /api/v1/stream/video  │  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │             SMARTVISION CENTRAL GATEWAY                │
                         │               (FastAPI / Uvicorn Hub)                  │
                         └───────────────────────▲──┬─────────────────────────────┘
                                                 │  │ WebSocket (/ws/device)
                                 Sensor Telemetry │  │ PWM Servo Move Commands
                                  (10 Hz JSON)   │  ▼
                         ┌────────────────────────────────────────────────────────┐
                         │             ESP32-S3 EMBEDDED HARDWARE                 │
                         │      (PCA9685, Servos, Sonar, PIR, Buzzer)             │
                         └────────────────────────────────────────────────────────┘
```

### Communication Channels
1. **REST API (`/api/v1/*`):** Health probes, comprehensive system diagnostics, manual actuation overrides, and failsafe commands.
2. **Video Streaming (`/api/v1/stream/video.mjpeg`):** High-speed multipart boundary HTTP stream consumed natively by browser `<img>` elements.
3. **Operator WebSocket (`/ws/client`):** Bidirectional low-latency JSON channel streaming 30 FPS tracking HUD targets, 10 Hz sensor telemetry, system alerts, and ingesting user commands.
4. **Device WebSocket (`/ws/device`):** Dedicated low-overhead JSON channel interfacing the ESP32-S3 microcontroller with 800 ms hardware watchdog monitoring.

Interactive Swagger documentation is available at `http://<host>:8000/docs` and ReDoc at `http://<host>:8000/redoc`. The complete OpenAPI 3.1.0 schema is exported at [`smartvision/docs/openapi.json`](file:///smartvision/docs/openapi.json).

---

## 2. Authentication & Security

All REST management endpoints and WebSocket connections support optional API key verification when `SMARTVISION_API_KEY` is configured in the environment.

- **HTTP Header:** `X-API-Key: <secret_key>` or `Authorization: Bearer <secret_key>`
- **WebSocket Query Parameter:** `ws://<host>:8000/ws/client?token=<secret_key>`

If no API key is set in `SMARTVISION_API_KEY`, the gateway runs in development trust mode for rapid deployment.

---

## 3. REST API Endpoint Reference

### 3.1 Root Discovery Index
- **Endpoint:** `GET /`
- **Description:** Returns service discovery links and gateway version metadata.
- **Response `200 OK`:**
```json
{
  "name": "SmartVision Central Gateway",
  "version": "1.0.0",
  "docs": "/docs",
  "health": "/api/v1/health",
  "status": "/api/v1/system/status",
  "stream": "/api/v1/stream/video.mjpeg",
  "ws_device": "/ws/device",
  "ws_client": "/ws/client"
}
```

---

### 3.2 System Health Probe
- **Endpoint:** `GET /api/v1/health`
- **Description:** Rapid liveness and health probe for container supervisors, load balancers, and launch health-check scripts.
- **Response `200 OK`:**
```json
{
  "status": "healthy",
  "uptime_sec": 142.5,
  "camera_active": true,
  "camera_fps": 29.8,
  "esp32_connected": true,
  "failsafe_active": false,
  "clients_connected": 1
}
```

---

### 3.3 Comprehensive System Status Snapshot
- **Endpoint:** `GET /api/v1/system/status`
- **Description:** Complete runtime state dump including servo coordinates, sensor telemetry, active tracking targets, and queue metrics.
- **Response `200 OK`:**
```json
{
  "system": {
    "name": "SmartVision",
    "version": "1.0.0",
    "mode": "auto_track",
    "failsafe_active": false,
    "uptime_seconds": 142.5
  },
  "connections": {
    "esp32_online": true,
    "client_count": 1
  },
  "hardware": {
    "servos": {
      "pan_angle": 92.4,
      "tilt_angle": 88.1,
      "is_moving": false
    },
    "sensors": {
      "distance_cm": 84.5,
      "pir_motion": false,
      "obstacle_detected": false
    }
  },
  "tracking": {
    "mode": "auto_track",
    "has_target": true,
    "target_id": 1,
    "confidence": 0.92,
    "error_px": {"x": 4.2, "y": -2.1},
    "is_settled": true
  }
}
```

---

### 3.4 Camera Actuation & Manual Jog Control
- **Endpoint:** `POST /api/v1/camera/control`
- **Description:** Dispatches calibrated pan/tilt movements to the hardware servos. Movement is clamped within certified safety limits ($15.0^\circ \le \text{pan} \le 165.0^\circ$, $60.0^\circ \le \text{tilt} \le 135.0^\circ$).
- **Request Body:**
```json
{
  "pan": 110.0,
  "tilt": 85.0,
  "speed": 0.8
}
```
- **Response `200 OK`:**
```json
{
  "success": true,
  "message": "Movement command dispatched",
  "dispatched_target": {"pan": 110.0, "tilt": 85.0, "speed": 0.8}
}
```
- **Error Responses:**
  - `400 Bad Request`: When `failsafe_active` is asserted, ESP32 is offline, or angles exceed mechanical constraints.

---

### 3.5 Emergency Stop & Failsafe Management
- **Endpoint:** `POST /api/v1/camera/failsafe`
- **Description:** Immediately triggers global safe-stop (freezing servos, engaging alarm) or clears active safe-stop state.
- **Request Body:**
```json
{
  "action": "stop",
  "reason": "Operator manual emergency stop"
}
```
- **Response `200 OK`:**
```json
{
  "success": true,
  "action_executed": "stop",
  "failsafe_active": true
}
```

---

### 3.6 MJPEG Video Stream
- **Endpoint:** `GET /api/v1/stream/video.mjpeg`
- **Headers:** `Content-Type: multipart/x-mixed-replace; boundary=frame`
- **Description:** Real-time HTTP multipart stream delivering JPEG frames at 30 FPS. Drains OpenCV driver queues with zero-latency double buffering and auto-failover to synthetic test pattern.

---

## 4. Full-Duplex WebSocket Protocol

### 4.1 Authoritative 5-Field Message Envelope
Every message exchanged across `/ws/client` and `/ws/device` strictly complies with the following envelope schema:

```json
{
  "type": "string",
  "timestamp": 1731754800000,
  "sender": "frontend | backend | esp32",
  "seq": 42,
  "payload": {}
}
```

| Field | Type | Description |
|---|---|---|
| `type` | `string` | Dot-delimited message type identifier (e.g. `cmd.servo.move`, `telem.sensors`). |
| `timestamp` | `integer` | 64-bit UTC millisecond epoch timestamp. |
| `sender` | `string` | Node source: `"frontend"`, `"backend"`, or `"esp32"`. |
| `seq` | `integer` | Monotonically increasing 32-bit sequence counter. |
| `payload` | `object` | Type-specific structured message payload. |

---

### 4.2 Complete Message Catalog

#### 1. System Liveness (`sys.ping` / `sys.pong`)
Exchanged to monitor round-trip latency (RTT) and maintain connection keepalive.
```json
// Inbound Ping
{
  "type": "sys.ping",
  "timestamp": 1731754800100,
  "sender": "frontend",
  "seq": 101,
  "payload": {"client_time": 1731754800100}
}

// Outbound Pong
{
  "type": "sys.pong",
  "timestamp": 1731754800102,
  "sender": "backend",
  "seq": 204,
  "payload": {"client_time": 1731754800100, "server_time": 1731754800102}
}
```

#### 2. Emergency Safe-Stop (`sys.safestop`)
Issued during safety violations, watchdog timeouts, or operator E-Stop.
```json
{
  "type": "sys.safestop",
  "timestamp": 1731754800200,
  "sender": "backend",
  "seq": 105,
  "payload": {
    "action": "engage",
    "reason": "Watchdog timeout / communication link lost"
  }
}
```

#### 3. Servo Actuation Command (`cmd.servo.move`)
Dispatched by operator D-pad/sliders or the autonomous tracking PID controller.
```json
{
  "type": "cmd.servo.move",
  "timestamp": 1731754800300,
  "sender": "backend",
  "seq": 112,
  "payload": {
    "pan": 95.0,
    "tilt": 88.5,
    "speed": 0.8
  }
}
```

#### 4. Calibrated Neutral Re-Center (`cmd.servo.center`)
Immediately centers both pan and tilt axes to $(90.0^\circ, 90.0^\circ)$.
```json
{
  "type": "cmd.servo.center",
  "timestamp": 1731754800400,
  "sender": "frontend",
  "seq": 115,
  "payload": {}
}
```

#### 5. Acoustic Buzzer Actuation (`cmd.buzzer`)
Controls the 2N2222-driven 5V active buzzer sound pattern.
```json
{
  "type": "cmd.buzzer",
  "timestamp": 1731754800500,
  "sender": "backend",
  "seq": 118,
  "payload": {
    "pattern": "chirp | alarm | beep | mute",
    "duration_ms": 300
  }
}
```

#### 6. Microcontroller Sensor Telemetry (`telem.sensors`)
Streamed at 10 Hz from the ESP32-S3 over `/ws/device`.
```json
{
  "type": "telem.sensors",
  "timestamp": 1731754800600,
  "sender": "esp32",
  "seq": 890,
  "payload": {
    "distance_cm": 45.2,
    "pir_state": 1,
    "pan_angle": 90.0,
    "tilt_angle": 90.0,
    "is_moving": false,
    "failsafe_active": false
  }
}
```

#### 7. Tracking Frame Target Stream (`track.frame_target`)
Streamed at 30 FPS over `/ws/client` with detected bounding boxes, ByteTrack IDs, active target reticle coordinates, and PID pixel errors.
```json
{
  "type": "track.frame_target",
  "timestamp": 1731754800700,
  "sender": "backend",
  "seq": 1400,
  "payload": {
    "frame_width": 640,
    "frame_height": 480,
    "detections": [
      {
        "track_id": 1,
        "bbox": [180.0, 120.0, 310.0, 420.0],
        "confidence": 0.94,
        "is_target": true
      }
    ],
    "target": {
      "track_id": 1,
      "centroid": [245.0, 270.0],
      "error_px": [-75.0, 30.0],
      "is_settled": false
    },
    "tracking_mode": "auto_track"
  }
}
```

#### 8. Target Lock Selection (`track.select_id`)
Dispatched when an operator clicks a detection bounding box in the web UI.
```json
{
  "type": "track.select_id",
  "timestamp": 1731754800800,
  "sender": "frontend",
  "seq": 132,
  "payload": {
    "track_id": 1,
    "mode": "auto_track"
  }
}
```

#### 9. System Notification & Alert Events (`alert.event`)
Dispatched on proximity warnings, connection state changes, or tracking loss.
```json
{
  "type": "alert.event",
  "timestamp": 1731754800900,
  "sender": "backend",
  "seq": 150,
  "payload": {
    "event_type": "proximity_obstruction | ws_disconnect | target_lost",
    "severity": "info | warning | critical",
    "message": "Obstacle detected closer than 20cm threshold (14.5 cm)",
    "action_taken": "motion_inhibited"
  }
}
```

---

## 5. Rate Limiting & Safety Enforcement

1. **Client Rate Limiting:** The Gateway enforces a 20 Hz transmission rate limit (minimum 50 ms interval between manual jog commands). Bursts exceeding 20 Hz are dropped gracefully with a warning alert to protect the servo hardware and WebSocket queue from buffer bloat.
2. **Watchdog Supervision:** If the ESP32 loses WebSocket connectivity for $> 800\text{ ms}$, the hardware watchdog trips: servos freeze immediately, the buzzer alarm engages, and all motion is inhibited until connection recovery and manual centering.
3. **Hardware Boundary Clamping:** Commands attempting to drive servos beyond certified angles ($[15^\circ, 165^\circ]$ Pan, $[60^\circ, 135^\circ]$ Tilt) are clamped automatically by both backend validation and firmware registers.
