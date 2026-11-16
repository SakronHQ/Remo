# SmartVision FastAPI Central Gateway & WebSockets

## Overview
The SmartVision backend is an asynchronous Python 3.10+ server powered by **FastAPI** and **Uvicorn**. It acts as the central switchboard and safety arbiter connecting the ESP32-S3 firmware, the PC computer vision engine, and multiple operator dashboards.

## Key Responsibilities
- **Dual WebSocket Routing:**
  - `/ws/device`: Bi-directional bridge for the ESP32-S3. Receives 10 Hz sensor telemetry and issues validated servo commands.
  - `/ws/client`: Bi-directional bridge for Next.js operator dashboards. Broadcasts telemetry, detections, and alerts; ingests manual jog commands and click-to-lock target selections with 20 Hz rate-limiting.
- **MJPEG Video Streaming:**
  - `/api/v1/stream/video.mjpeg`: HTTP multipart stream (`multipart/x-mixed-replace`) consumable directly by HTML5 `<img>` tags with tactical HUD annotations.
- **Message Validation & Safety Clamping:**
  - Enforces Pydantic v2 schemas across all messages. Rejects out-of-bounds angles ($< 15^\circ$ or $> 165^\circ$ pan; $< 60^\circ$ or $> 135^\circ$ tilt) with HTTP 422 / 400.
- **System State Manager:**
  - Thread-safe, asyncio-locked state repository arbitrating control authority between manual operator commands, autonomous CV tracking, and emergency stop (E-Stop).
- **Communication Watchdog & Safe-Stop:**
  - Monitors firmware ping intervals; alerts clients and engages failsafe if firmware goes offline for $> 1200\text{ ms}$.
- **Decoupled Background Tracking Worker:**
  - Background async worker consuming frames from `CameraService`, executing ByteTrack inference in thread pool, computing PID corrections, and dispatching servo actuation commands at 20 Hz.

## Directory Structure
```
backend/
├── requirements.txt           # fastapi, uvicorn, pydantic, websockets, pytest, aiohttp
├── app/
│   ├── main.py                # FastAPI app initialization, lifespan, routes
│   ├── config.py              # Host/port settings, timeouts, angle limits, presets
│   ├── auth.py                # API key / Bearer token security verification
│   ├── schemas/               # Pydantic v2 models (protocol.py, rest.py)
│   ├── routers/               # rest_api.py, stream.py, websockets.py
│   └── services/              # state_manager.py, connection_hub.py, failsafe.py, tracking_worker.py
└── README.md
```

## Running Locally
```powershell
# Start gateway server
& "d:\Project\Rana Project\smartvision\.venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Running Tests
```powershell
& "d:\Project\Rana Project\smartvision\.venv\Scripts\python.exe" -m pytest tests/test_backend_gateway.py -v
```
