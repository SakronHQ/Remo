# SmartVision Operator Dashboard (Phase 7 Frontend Guide)

## 1. Executive Summary & Architecture

The **SmartVision Operator Dashboard** is the primary command-and-control interface for the SmartVision Autonomous Pan-Tilt Person Tracking System. Built on **Next.js 14+ (App Router)**, **React 18**, **TypeScript**, and **Tailwind CSS**, it delivers a minimal, high-contrast, dark surveillance console engineered for high responsiveness, sub-50ms command actuation, and synchronized video telemetry.

```
                              ┌───────────────────────────────────┐
                              │     Next.js Operator Dashboard    │
                              │       (Port 3000 / Browser)       │
                              └─────────────────┬─────────────────┘
                                                │
                 ┌──────────────────────────────┴──────────────────────────────┐
                 │ HTTP (MJPEG Video Stream)                                   │ WebSocket (JSON Envelopes)
                 │ GET /api/v1/stream/video.mjpeg                              │ WS /ws/client (20 Hz rate limit)
                 ▼                                                             ▼
┌─────────────────────────────────┐                           ┌─────────────────────────────────┐
│     FastAPI Backend Gateway     │                           │   FastAPI WebSocket Hub         │
│   (MJPEG Streaming Service)     │                           │  (Bi-directional State Router)  │
└─────────────────────────────────┘                           └────────────────┬────────────────┘
                                                                               │
                                                                               │ ESP-NOW / WiFi / WS
                                                                               ▼
                                                              ┌─────────────────────────────────┐
                                                              │  ESP32-S3 Edge Microcontroller  │
                                                              │ (Servos, Sonar, PIR, Buzzer)    │
                                                              └─────────────────────────────────┘
```

### Core Design Philosophy (Ponytail / Minimal Bloat)
- **Zero Bloat:** Standard HTML5 Canvas, native CSS Flex/Grid, Lucide icons, and React hooks. No heavy UI framework wrappers or bloated animation engines.
- **Dark Surveillance Theme:** Slate `#070a12` dark background, high-contrast HUD cyan `#00e5ff` and emerald `#10b981` indicators, rose `#ef4444` emergency indicators.
- **Robustness:** Native 20 Hz outbound client rate limiting, auto-reconnecting WebSocket with exponential backoff, hardware boundary clipping, and failsafe states.

---

## 2. Directory Structure

```
smartvision/frontend/
├── package.json               # Dependencies, scripts, test runner
├── tsconfig.json              # TypeScript compilation settings & path aliases (@/*)
├── tailwind.config.ts         # Surveillance color palette and typography
├── postcss.config.js          # Tailwind & Autoprefixer plugin configuration
├── next.config.mjs            # API rewrite proxy to backend (http://localhost:8000)
├── tests/
│   └── protocol.test.mjs      # Fast unit tests for envelopes, bounds, and hit-tests
└── src/
    ├── app/
    │   ├── layout.tsx         # Dark theme HTML root layout
    │   ├── page.tsx           # Assembled single-pane surveillance workspace
    │   └── globals.css        # Tailwind directives and tactical scrollbar styles
    ├── components/
    │   ├── HeaderStatus.tsx   # Hub/ESP32/Cam indicators, latency, and E-Stop
    │   ├── VideoViewport.tsx  # Live MJPEG stream, HTML5 vector HUD, click-to-track
    │   ├── ManualControls.tsx # Proportional joystick, D-pad, and angle gauges
    │   ├── TrackingControls.tsx# Mode tabs, active target status, detected persons
    │   ├── SensorMonitoring.tsx# Sonar distance bar, PIR badge, buzzer tests
    │   └── EventLogFeed.tsx   # Timestamped audit log with severity filters
    ├── hooks/
    │   ├── useSmartVisionWebSocket.ts # Full-duplex WebSocket link & state reducer
    │   └── useKeyboardControls.ts     # WASD / Arrow key jog shortcuts
    └── types/
        └── protocol.ts        # TypeScript schemas matching docs/protocol.md
```

---

## 3. UI Component Breakdown

### 3.1 Header & System Connection Status (`HeaderStatus.tsx`)
- **Gateway Hub Status:**
  - Displays `CONNECTED` (green), `RECONNECTING` (amber), or `DISCONNECTED` (red).
  - Displays round-trip time (RTT) latency in milliseconds.
  - Manual reconnect button triggers immediate socket retry.
- **ESP32 Edge Device Status:**
  - Online/Offline indicator reflecting microcontroller WebSocket heartbeat.
  - Microcontroller IP address, Wi-Fi RSSI (dBm), and edge boot uptime `[hh:mm:ss]`.
- **Camera Service Metrics:**
  - Video FPS counter, resolution indicator (`640x480`), and simulation badge when synthetic generator is active.
- **Global Emergency Stop (E-Stop):**
  - High-visibility red button with safety confirmation modal.
  - Immediately halts all servo actuation, disengages tracking, and triggers failsafe mode.
  - When active, presents a prominent `RESUME / RESET` button to clear the fault safely.

### 3.2 Live Camera Feed & Canvas Viewport (`VideoViewport.tsx`)
- **Low-Latency Video Stream:**
  - Streams multipart JPEG from `/api/v1/stream/video.mjpeg`.
  - Graceful fallback to radar-style standby canvas if backend stream is unreachable.
- **Synchronized HTML5 Vector HUD:**
  - Rendered at 30-60 FPS over the video layer without DOM node overhead.
  - Dynamic `ResizeObserver` container tracking to prevent canvas stretching or coordinate drift.
  - HUD header metrics: Real-time FPS counter, connection latency (ms), frame resolution (`640x480`), and tracking mode badge.
  - **Center Reticle & Deadband Circle:** Highlights the central PID deadband (within which servo movement is suppressed to prevent oscillation).
  - **Detection Bounding Boxes:** Gray/slate rectangles around detected persons with ByteTrack IDs and confidence percentages.
  - **Active Target Reticle:** High-contrast bracketed corner reticle (cyan/emerald), centroid dot, and dashed targeting line connecting center to target.
- **Interactive Click-to-Track:**
  - Operators can click anywhere on the video frame.
  - Emits `track.target_select` with normalized coordinates $[x, y]$ ($0.0 \le x, y \le 1.0$) invariant of canvas display scale.
  - If the click intersects a person bounding box, locks onto that person's `track_id`.
  - Generates an animated ripple effect on the canvas for instant operator visual feedback.

### 3.3 Manual Pan/Tilt Gimbal Controls (`ManualControls.tsx`)
- **Proportional 2-Axis Joystick:**
  - Touch and pointer-captured virtual joystick.
  - Dragging the thumb stick sends throttled relative jog commands proportional to deflection.
- **Directional D-Pad:**
  - Discrete Pan Left/Right and Tilt Up/Down buttons.
  - Quick **HOME CENTER** button returning servos to calibrated neutral ($90.0^\circ, 90.0^\circ$).
- **Servo Boundaries & Gauges:**
  - Visual progress bar gauges tracking current angles against hardware limits:
    - Pan: $15.0^\circ$ to $165.0^\circ$ (Center: $90.0^\circ$)
    - Tilt: $60.0^\circ$ to $135.0^\circ$ (Level: $90.0^\circ$)
- **Fine-Tuning Controls:**
  - Normalized speed factor slider ($0.1\times$ to $1.0\times$).
  - Discrete step angle selector ($1.0^\circ, 2.5^\circ, 5.0^\circ, 10.0^\circ$).

### 3.4 Automatic Tracking Controls (`TrackingControls.tsx`)
- **Operating Mode Switcher:**
  - `Auto-Track`: Closed-loop autonomous visual tracking via ByteTrack and anti-windup PID.
  - `Manual`: Operator controls servos via joystick, D-pad, or keyboard.
  - `Patrol`: Autonomous continuous azimuth sweep between $30^\circ$ and $150^\circ$.
  - `Idle`: Servos hold position; vision processing runs passively.
- **Active Locked Target Card:**
  - Displays locked Track ID, detection confidence, centroid error ($\Delta x, \Delta y$), and tracking state:
    - `TRACKING` (Emerald): Active visual lock within dynamic tracking window.
    - `COASTING` (Amber): Temporary occlusion handling with Kalman velocity coast.
    - `HOLDING` (Cyan): Target within central deadband; servos static.
    - `LOST` (Rose): Target departed frame; timeout countdown active.
  - Unlock / Stop Tracking button.
- **Detected Persons List:**
  - Displays all detected individuals currently in the camera's field of view.
  - 1-click **SELECT & TRACK** buttons to instantly transfer the tracking lock.

### 3.5 Sensor Telemetry & Edge I/O (`SensorMonitoring.tsx`)
- **HC-SR04 Ultrasonic Sonar:**
  - Numeric distance display in centimeters ($2.0\text{ cm}$ to $400.0\text{ cm}$).
  - 3-tier proximity indicator bar:
    - **Safe Range (Green):** $> 40\text{ cm}$
    - **Warning Proximity (Yellow):** $20\text{ cm} - 40\text{ cm}$
    - **Critical Proximity (Red):** $< 20\text{ cm}$ (triggers audible proximity alert)
- **HC-SR501 PIR Motion Detector:**
  - High-visibility 3-state badge:
    - `WARMING UP (Xs)` (Amber): 30-second thermal stabilization countdown after boot.
    - `ACTIVE (MOTION DETECTED)` (Rose): Motion trigger actively fired.
    - `CLEAR / STABILIZED` (Emerald): Pyroelectric sensor armed and clear.
  - Lifetime motion trigger counter and time since last motion event.
- **Acoustic Buzzer Controls:**
  - Real-time buzzer status indicator (`ACTIVE` vs `MUTED`).
  - One-click acoustic test triggers: **Beep**, **Chirp**, **Alarm**, and **Mute**.
- **Edge Diagnostics:**
  - Wi-Fi RSSI (dBm), free heap memory (KB), and microcontroller CPU temperature.

### 3.6 Event Log & Alert Feed (`EventLogFeed.tsx`)
- **Live Stream Audit:**
  - Displays timestamped audit events emitted by backend services and ESP32 firmware.
  - Badges for `CRITICAL`, `WARNING`, and `INFO`.
- **Search & Filters:**
  - Severity tab filter (`All`, `Info`, `Warning`, `Critical`).
  - Full-text keyword search across event types and messages.
  - One-click Clear Logs button.

---

## 4. WebSocket Hook & Protocol Contract

The frontend connects to the backend gateway over `ws://localhost:8000/ws/client` using the custom React hook `useSmartVisionWebSocket`.

### Outbound Envelope Specification
All client commands adhere to the authoritative 5-field envelope:
```json
{
  "type": "cmd.servo.move",
  "timestamp": 1731657100000,
  "sender": "frontend",
  "seq": 101,
  "corr_id": null,
  "payload": {
    "mode": "absolute",
    "pan": 90.0,
    "tilt": 90.0,
    "speed": 0.5,
    "smooth": true
  }
}
```

### Supported Outbound Commands
| Command Type | Payload Parameters | Description |
| :--- | :--- | :--- |
| `cmd.servo.move` | `{ mode, pan, tilt, speed, smooth }` | Absolute or relative servo movement |
| `cmd.jog` | `{ delta_pan, delta_tilt, speed }` | Relative incremental jog |
| `cmd.servo.center` | `{ speed }` | Slew to $(90.0^\circ, 90.0^\circ)$ home |
| `cmd.servo.patrol` | `{ enabled, pan_min, pan_max, speed_deg_s }` | Toggle automated patrol sweep |
| `cmd.estop` | `{ action: "freeze"\|"resume", reason }` | Trigger or clear emergency stop |
| `cmd.buzzer` | `{ action: "beep"\|"chirp"\|"alarm"\|"off", duration_ms }` | Test acoustic buzzer pattern |
| `track.mode_set` | `{ mode: "auto_track"\|"manual"\|"idle"\|"patrol" }` | Switch tracking operating mode |
| `track.target_select` | `{ coordinates: [x,y] }` or `{ track_id }` | Lock tracking via normalized coordinates $[0.0, 1.0]$ or track ID |
| `track.select_id` | `{ track_id }` | Lock tracking onto specific ByteTrack ID |
| `track.click_to_track` | `{ click_x, click_y }` | Lock tracking via pixel coordinate hit-test |
| `sys.ping` | `{}` | Heartbeat ping to calculate latency |

### 20 Hz Outbound Rate Limiting
To strictly prevent flooding the WebSocket and tripping the backend rate limiter, the hook maintains an internal timestamp check (`lastSendTimeRef`):
- Any non-critical move or jog command dispatched within **45ms** of the previous command is automatically suppressed.
- Critical commands (e.g., E-Stop, Mode changes) bypass the rate-limit gate.

### Automatic Reconnection Strategy
The connection manager implements exponential backoff:
$$\text{delay} = \min\left(1000 \times 1.5^{\text{attempt}}, 10000\right)\text{ ms}$$
Upon link severance, the hook transitions to `reconnecting` status and resets attempts upon successful handshake.

---

## 5. Keyboard Navigation & Hotkeys

When the dashboard is active and the operator is not typing in a text field, global hotkeys are enabled:
| Key Binding | Action |
| :--- | :--- |
| **Arrow Up / W** | Tilt Up ($+5.0^\circ$) |
| **Arrow Down / S** | Tilt Down ($-5.0^\circ$) |
| **Arrow Left / A** | Pan Left ($-5.0^\circ$) |
| **Arrow Right / D** | Pan Right ($+5.0^\circ$) |
| **C** | Center Position ($(90.0^\circ, 90.0^\circ)$) |

---

## 6. Verification & Test Suite

The frontend includes a fast unit test suite executed with Node's native test runner:
```bash
npm test
```

### Verified Test Cases (11/11 passing):
1. `Envelope conforms to authoritative 5-field schema`
2. `Calibrated boundary clamping protects servo hardware (15°-165° Pan, 60°-135° Tilt)`
3. `Ultrasonic distance thresholds correctly tier proximity alerts (>40 safe, 20-40 warning, <20 crit)`
4. `Hit testing identifies clicked detection bounding box from vector coordinates`
5. `Safe-stop payload structures freeze and resume correctly`
6. `Exponential backoff reconnect bounds and scales appropriately`
7. `Client 20 Hz outbound throttling enforces 45ms minimum interval`
8. `Alert filtering and search works across severities and keywords`
9. `Track target select builds valid payloads and clamps normalized coordinates`
10. `PIR sensor warm-up countdown and detection state resolution`
11. `Header and video HUD status telemetry formatting (FPS, Latency, Resolution, Uptime)`

### Production Build Validation:
```bash
cd "d:\Project\Rana Project\smartvision\frontend"
npm run build
```
Build Output:
- Route `/`: **17 kB** (First Load JS: **104 kB**)
- Zero TypeScript warnings or compilation errors.

---

## 7. Deployment Instructions

### Development Mode
```bash
# 1. Start FastAPI backend (port 8000)
cd "d:\Project\Rana Project\smartvision"
& .venv\Scripts\python.exe -m smartvision.backend.app.main

# 2. Start Next.js development server (port 3000)
cd "d:\Project\Rana Project\smartvision\frontend"
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in any modern browser.

### Production Standalone Deployment
```bash
cd "d:\Project\Rana Project\smartvision\frontend"
npm run build
npm start
```

### Environment Configuration
The frontend automatically points to `ws://<host>:8000/ws/client` and proxies `/api/v1` to `http://<host>:8000`. To customize endpoints, create a `.env.local` file:
```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/client
```
