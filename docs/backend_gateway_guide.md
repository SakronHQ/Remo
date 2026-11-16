# SmartVision Backend Gateway & Central Hub: Technical Architecture & Operations Guide

**Document Version:** 1.0.0 (Phase 6 Implementation)  
**Author:** SmartVision Engineering Team  
**Scope:** FastAPI Application, Dual WebSocket Hub, MJPEG Streaming, REST API, Safety Watchdogs, and Local Execution  
**Status:** Certified Specification & Implementation  

---

## 1. Architectural Overview & Topology

The SmartVision backend acts as the centralized gateway and arbitration hub connecting the embedded ESP32-S3 microcontroller, the PC-hosted computer vision engine, and web operator dashboards. It mediates all sensor ingestion, optical person tracking, mechanical actuation, and video distribution.

```
                   +-----------------------------------------------+
                   |            Next.js Operator Dashboard         |
                   |               (Web Browser Client)            |
                   +-----------------------------------------------+
                                  |                 ^
             HTTP GET (MJPEG)     |                 | Full-Duplex WebSocket
           /api/v1/stream/video   |                 | /ws/client (20 Hz)
                                  v                 v
+-----------------------------------------------------------------------------------+
|                        FastAPI Central Gateway (PC Host)                          |
|                                                                                   |
|  [CameraService] ──────> [TrackingPipeline] ──────> [SystemStateManager]          |
|  (UVC / DirectShow)      (YOLO + ByteTrack)         (Thread-Safe Repository)      |
|                                  │                            ▲                   |
|                                  v                            │                   |
|                        [TrackingWorker Loop]                  │                   |
|                        (20 Hz PID Dispatch)                   │                   |
|                                  │                            │                   |
|                                  v                            │                   |
|                         [ConnectionHub] ──────────────────────┘                   |
|                         (Dual WebSocket Arbiter)                                  |
|                                  │                                                |
|                                  v Full-Duplex WebSocket                          |
|                             /ws/device                                            |
+-----------------------------------------------------------------------------------+
                                   │
                                   v
                   +-----------------------------------------------+
                   |               ESP32-S3 Firmware               |
                   |                 (FreeRTOS)                    |
                   |                                               |
                   | - PCA9685 Servos (15°-165° Pan, 60°-135° Tilt)|
                   | - HC-SR04 Sonar & HC-SR501 PIR (10 Hz)        |
                   | - Active 5V Buzzer Transistor Driver          |
                   | - 800ms Hardware Safety Watchdog              |
                   +-----------------------------------------------+
```

---

## 2. Lifespan Architecture & Asynchronous Services

The application entrypoint (`backend/app/main.py`) utilizes modern FastAPI `lifespan` context management to guarantee ordered initialization, thread safety, and clean hardware teardown without orphan processes.

### 2.1 Initialization Sequence
1. **CameraService:** Starts decoupled buffer-draining capture thread (DirectShow/V4L2) or synthetic test card fallback (`vision.camera.service.CameraService`).
2. **TrackingPipeline:** Initializes YOLOv8 person detector (or zero-dependency `MockPersonDetector`), pure NumPy ByteTracker, target selector state machine, dual-axis PID controller, and tactical HUD overlay (`vision.tracking.pipeline.TrackingPipeline`).
3. **SystemStateManager:** Instantiates thread-safe state container tracking ESP32 connection state, sensor telemetry, active targets, alert ring buffers, and latest encoded JPEG frames (`backend.app.services.state_manager.SystemStateManager`).
4. **ConnectionHub:** Manages WebSocket sessions for `/ws/device` and `/ws/client`, enforcing 20 Hz client rate limiting and atomic broadcasting (`backend.app.services.connection_hub.ConnectionHub`).
5. **FailsafeService:** Launches background task querying ESP32 with 500 ms `sys.ping` heartbeats and detecting communications dropouts exceeding 1200 ms (`backend.app.services.failsafe.FailsafeService`).
6. **TrackingWorker:** Launches background asyncio task continuously consuming frames from `CameraService`, executing inference via `asyncio.to_thread`, updating state, and broadcasting `track.frame_target` telemetry (`backend.app.services.tracking_worker.TrackingWorker`).

### 2.2 Graceful Teardown Sequence
1. Cancels and awaits `TrackingWorker` task.
2. Cancels and awaits `FailsafeService` watchdog task.
3. Stops `CameraService` background capture and reconnection threads, releasing OpenCV video hardware.
4. Closes active WebSocket connections with clean status codes.

---

## 3. Dual WebSocket Hub Specification

### 3.1 `/ws/device` (ESP32-S3 Embedded Bridge)
- **Direction:** Full-Duplex between PC Backend and ESP32-S3.
- **Inbound Ingestion:**
  - `telem.sensors`: 10 Hz environmental snapshot (sonar distance, PIR motion state, current/target servo angles, buzzer state, uptime, heap). Updates state manager and broadcasts to all web operators.
  - `telem.status` / `sys.status`: Diagnostics and heartbeat telemetry.
  - `alert.event`: Hardware alerts (e.g. proximity obstruction $< 20\text{ cm}$).
  - `sys.pong`: Latency acknowledgment (calculates round-trip time).
  - `sys.ping`: Responds immediately with `sys.pong`.
- **Outbound Dispatching:**
  - `cmd.servo.move` & `cmd.jog`: Target pan/tilt positions.
  - `cmd.servo.center`: Re-centering to neutral $90^\circ, 90^\circ$.
  - `cmd.estop` & `sys.safestop`: Hardware freeze and torque release.
  - `cmd.buzzer`: Acoustic chirp and alarm patterns.
  - `sys.ping`: Periodic 500 ms heartbeat query.
- **Watchdog & Safe-Stop:** If communication lapses for $> 1200\text{ ms}$, the backend marks the device disconnected, enters failsafe mode, and broadcasts a `ws_disconnect` critical alert to all connected dashboards.

### 3.2 `/ws/client` (Frontend Operator Bridge)
- **Direction:** Full-Duplex between PC Backend and Operator Web Dashboards.
- **Connection Handshake:** Immediately transmits full system state snapshot (`sys.status`) upon connection.
- **Operator Inbound Commands:**
  - `cmd.servo.move` & `cmd.jog`: Manual D-pad or slider adjustments.
  - `cmd.servo.center`: Returns pan/tilt servos to $90^\circ, 90^\circ$.
  - `cmd.estop`: Global hardware emergency stop.
  - `track.mode_set`: Changes mode (`auto_track`, `manual`, `idle`, `patrol`).
  - `track.select_id`: Direct ByteTrack ID locking.
  - `track.click_to_track`: Interactive image plane $(x, y)$ coordinate lock.
  - `cmd.buzzer`: Dispatches buzzer test pattern to firmware.
- **Rate-Limiting (20 Hz):**
  - Enforces minimum 50 ms period between inbound operator commands per client session.
  - Drops burst packets exceeding 20 Hz and returns `rate_limit_exceeded` alert to prevent hardware flooding.
- **Schema Validation:**
  - Strictly validates outer 5-field envelope and inner payload models.
  - Commands violating physical angle limits ($< 15^\circ$ or $> 165^\circ$ Pan; $< 60^\circ$ or $> 135^\circ$ Tilt) are rejected with a structured `command_rejected` alert envelope.

---

## 4. Low-Latency MJPEG Video Streaming

- **Endpoint:** `GET /api/v1/stream/video.mjpeg`
- **MIME Type:** `multipart/x-mixed-replace; boundary=frame`
- **Native Browser Playback:**
  ```html
  <img src="http://localhost:8000/api/v1/stream/video.mjpeg" alt="SmartVision Live Stream" />
  ```
- **HUD Annotation:** Every video frame is rendered with tactical HUD elements:
  - Bounding boxes with tracking ID, class name, and confidence score.
  - High-visibility corner reticle for active locked target.
  - Centroid deadband rectangles ($\pm 15\text{ px}$ inner, $\pm 25\text{ px}$ outer).
  - Telemetry banner displaying real-time FPS, inference latency, resolution, and tracking state.
- **Client Disconnect Cleanup:** Stream generator detects client HTTP disconnection via `request.is_disconnected()`, terminating frame yielding without leaking background memory or asyncio tasks.

---

## 5. REST API Reference (`/api/v1/`)

All REST endpoints support optional API Key or Bearer token authentication.

### 5.1 `GET /api/v1/health`
Returns gateway operational health, uptime, and version.
```json
{
  "status": "ok",
  "uptime_s": 42.15,
  "timestamp": 1731710500120,
  "version": "1.0.0"
}
```

### 5.2 `GET /api/v1/system/status`
Returns comprehensive aggregated diagnostic snapshot across ESP32, Camera, Tracking, and Sensors.
```json
{
  "timestamp": 1731710505120,
  "uptime_s": 47.15,
  "estop_active": false,
  "esp32": {
    "connected": true,
    "ip": "192.168.1.150",
    "connected_at_ms": 1731710460000,
    "last_heartbeat_ms": 1731710505100,
    "rtt_ms": 14,
    "failsafe_active": false,
    "estop_active": false
  },
  "camera": {
    "running": true,
    "fps": 30.0,
    "synthetic": false,
    "width": 640,
    "height": 480,
    "dropped_frames": 0
  },
  "tracking": {
    "mode": "auto_track",
    "locked": true,
    "active_track_id": 3,
    "tracks_count": 2,
    "inference_ms": 8.4,
    "fps": 29.8,
    "active_target": {
      "track_id": 3,
      "centroid": [310.0, 245.0],
      "bbox": [240, 110, 380, 390],
      "confidence": 0.91
    }
  },
  "sensors": {
    "sonar": {"distance_cm": 74.2, "valid": true, "status": "in_range"},
    "pir": {"motion_detected": true, "trigger_count": 8, "last_trigger_ms": 12400},
    "servos": {"pan_angle": 92.5, "tilt_angle": 88.0, "pan_target": 90.0, "tilt_target": 90.0, "is_moving": false},
    "buzzer": {"active": false, "pattern": "off"},
    "system": {"uptime_ms": 45100, "rssi_dbm": -56, "free_heap_bytes": 284100}
  }
}
```

### 5.3 `POST /api/v1/tracking/target`
Locks onto a target via image coordinate click, direct tracking ID, or prioritization strategy.
- **Request Body:**
  ```json
  {
    "click_to_track": [320.0, 240.0],
    "track_id": null,
    "strategy": null
  }
  ```
- **Response:**
  ```json
  {
    "status": "ok",
    "message": "Locked target ID 3 via click-to-track",
    "data": {"track_id": 3, "locked": true}
  }
  ```

### 5.4 `POST /api/v1/tracking/mode`
Configures tracking state machine mode.
- **Request Body:** `{"mode": "auto_track"}` (`auto_track`, `manual`, `idle`, `patrol`)
- **Response:** `{"status": "ok", "message": "Tracking mode changed to 'auto_track'", "data": {"mode": "auto_track"}}`

### 5.5 `POST /api/v1/camera/control`
Dispatches manual servo movement, incremental jogging, centering, or speed adjustments. Enforces physical boundary clamping.
- **Move Request:**
  ```json
  {
    "action": "move",
    "pan": 115.0,
    "tilt": 85.0,
    "speed": 0.5
  }
  ```
- **Jog Request:**
  ```json
  {
    "action": "jog",
    "delta_pan": 5.0,
    "delta_tilt": -3.0,
    "speed": 0.5
  }
  ```
- **Speed Adjustment Request:**
  ```json
  {
    "action": "speed",
    "speed": 0.8
  }
  ```
- **Center Request:** `{"action": "center"}`
- **Out-of-Bounds Rejection (HTTP 422 / 400):**
  If `pan < 15.0` or `pan > 165.0`, or `tilt < 60.0` or `tilt > 135.0`, the request is rejected with validation details.

### 5.6 `POST /api/v1/system/estop`
Engages or resets hardware Emergency Stop.
- **Engage:** `{"action": "freeze", "reason": "Operator Emergency Halt"}`
- **Resume:** `{"action": "resume"}`

### 5.7 `POST /api/v1/buzzer/test`
Dispatches acoustic alert patterns to ESP32 firmware.
- **Request Body:**
  ```json
  {
    "action": "chirp",
    "duration_ms": 150,
    "count": 2,
    "interval_ms": 100
  }
  ```

---

## 6. Authentication & Security Configuration

Security settings are managed centrally in `backend/app/config.py` and configurable via environment variables:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SMARTVISION_AUTH_ENABLED` | `false` | Enable/disable API key verification |
| `SMARTVISION_API_KEY` | `smartvision-secret-key` | Secret key token |
| `SMARTVISION_HOST` | `0.0.0.0` | Gateway bind address |
| `SMARTVISION_PORT` | `8000` | Gateway HTTP/WS port |
| `SMARTVISION_FORCE_SYNTHETIC` | `false` | Force synthetic camera for headless CI |

When `SMARTVISION_AUTH_ENABLED=true`:
- **REST Endpoints:** Must supply `X-API-Key: <key>`, `Authorization: Bearer <key>`, or URL parameter `?token=<key>`.
- **WebSocket Endpoints:** Must supply URL parameter `?token=<key>` or header `X-API-Key: <key>`. Unauthorized connections close with status `1008 Policy Violation`.

---

## 7. Local Execution & Verification Guide

### 7.1 Running the Server Locally
To start the gateway using the virtual environment:
```powershell
# Navigate to repository root
cd "d:\Project\Rana Project\smartvision"

# Launch Uvicorn with auto-reload
& ".\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Once running:
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc Documentation: `http://localhost:8000/redoc`
- System Status: `http://localhost:8000/api/v1/system/status`
- Live MJPEG Video Stream: `http://localhost:8000/api/v1/stream/video.mjpeg`
- ESP32 Firmware WebSocket: `ws://localhost:8000/ws/device`
- Frontend Operator WebSocket: `ws://localhost:8000/ws/client`

### 7.2 Running Automated Test Suite
To verify the entire backend subsystem:
```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests/test_backend_gateway.py -v
```
All 20 test cases execute and pass in $< 2.0\text{ seconds}$.
