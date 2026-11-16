# SmartVision: PC Camera Subsystem & Low-Latency Video Pipeline Guide

**Document Version:** 1.0.0 (Phase 4 Specification)  
**Author:** SmartVision Engineering Team  
**Scope:** Architecture, Capability Probing, Buffer Draining, Failover, Streaming, and Tuning  
**Status:** Approved Master Guide  

---

## 1. System Overview & Latency Architecture

In real-time computer vision and dual-axis servo tracking, video latency is the primary cause of control loop instability, overshoot, and servo hunting. Standard OpenCV video ingestion via `cv2.VideoCapture.read()` introduces significant latency due to underlying OS driver buffering.

```
+-------------------------------------------------------------------------+
|                          CAMERA INGESTION SUBSYSTEM                     |
+-------------------------------------------------------------------------+
|                                                                         |
|  +--------------------+                                                 |
|  |   UVC Hardware     |                                                 |
|  |  USB 2.0 / USB 3.0 |                                                 |
|  +---------+----------+                                                 |
|            | DirectShow (Win) / V4L2 (Linux)                            |
|            v                                                            |
|  +---------+--------------------+                                       |
|  | OS Video Driver 3-5 FIFO Buf | (Source of 100-200ms default lag)     |
|  +---------+--------------------+                                       |
|            |                                                            |
|            v                                                            |
|  +------------------------------+                                       |
|  |   CameraCaptureThread        | <--- Continuous non-blocking drain    |
|  |  (High-Priority Producer)    |      at native camera FPS             |
|  +---------+--------------------+                                       |
|            |                                                            |
|            | Atomic Reference Swap (Thread-Safe Lock / Condition)       |
|            v                                                            |
|  +------------------------------+                                       |
|  | Double-Buffer / Fresh Frame  | <--- ZERO-LAG LATEST FRAME SLOT       |
|  +----+--------------------+----+                                       |
|       |                    |                                            |
|       v                    v                                            |
|  +----+-----------+   +----+-----------+   +-----------------------+    |
|  | YOLOv8/ByteTrack|   | MJPEG Streamer |   | Preview Utility (CLI) |    |
|  | Tracking Worker|   | FastAPI Web    |   | Operator HUD Display  |    |
|  +----------------+   +----------------+   +-----------------------+    |
|                                                                         |
+-------------------------------------------------------------------------+
```

### 1.1 The Root Cause of Video Lag
When an application calls `cv2.VideoCapture.read()`, the operating system driver (DirectShow on Windows or V4L2 on Linux) typically buffers 3 to 5 video frames in an internal hardware queue. If a downstream consumer (such as deep learning inference or an HTTP stream) processes a frame in 40 ms while the camera generates frames every 33.3 ms, standard synchronous `read()` calls retrieve stale frames from the head of the driver queue. Over time, the application lags several hundred milliseconds behind real-time reality.

### 1.2 Zero-Lag Decoupled Capture Solution
SmartVision solves this problem via `CameraCaptureThread`:
1. **Aggressive Buffer Draining:** A dedicated background daemon thread invokes `cap.read()` continuously at full sensor frame rate, immediately draining the OS driver queue.
2. **Double-Buffering & Atomic Overwrite:** As each fresh frame arrives, it overwrites the internal slot protected by a thread-safe mutex and condition variable (`threading.Condition`).
3. **Dropped Frame Telemetry:** If a newer frame arrives before an inference consumer requests one, the stale frame is superseded and `dropped_frames` is incremented.
4. **Immediate Non-Blocking Delivery:** Any downstream pipeline calling `get_frame()` or `get_frame_nowait()` receives the exact frame captured just milliseconds earlier.

---

## 2. Camera Discovery & Capability Probing

The `CameraProbe` module (`vision.camera.probe`) detects connected USB video devices, probes backend support, and queries supported resolutions, frame rates, and FourCC pixel formats.

### 2.1 CLI Probe Execution
Run the camera probe directly from the terminal:

```bash
# Formatted ASCII capability report
python -m vision.camera.probe

# Output raw JSON for automated tooling / backend integration
python -m vision.camera.probe --json

# Probe a specific camera index only
python -m vision.camera.probe --device 0
```

### 2.2 Sample Probe Output
```
==============================================================================
        SMARTVISION PC CAMERA DISCOVERY & CAPABILITY PROBE
==============================================================================

[+] Device Index: 0 (DSHOW)
    - Default Resolution : 1280x720
    - Default FourCC     : MJPG
    - Default FPS        : 30.0
    - Tested Resolutions : 1920x1080, 1280x720, 800x600, 640x480, 320x240
    - Tested FourCC Formats: MJPG, YUY2, NV12
    - Supported FPS      : 60, 30, 24, 15
==============================================================================
```

### 2.3 Programmatic Usage
```python
from vision.camera.probe import CameraProbe

# 1. Discover all openable device indices
available_indices = CameraProbe.probe_available_indices(max_index=4)
print("Available camera indices:", available_indices)

# 2. Query detailed capabilities for a specific camera
device_info = CameraProbe.probe_device_capabilities(index=0)
print(f"Supported resolutions: {device_info.supported_resolutions}")
print(f"Supported FourCC codecs: {device_info.supported_fourccs}")
```

---

## 3. Configuration Reference (`CameraConfig`)

The `CameraConfig` dataclass centralizes all camera ingestion parameters:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `device_index` | `int` | `0` | Operating system camera index to open. |
| `width` | `int` | `640` | Requested frame capture width in pixels. |
| `height` | `int` | `480` | Requested frame capture height in pixels. |
| `fps` | `float` | `30.0` | Target camera frame rate. |
| `fourcc` | `str` | `"MJPG"` | Video FourCC compression codec (`"MJPG"`, `"YUY2"`, `"NV12"`). |
| `backend` | `CameraBackend` | `AUTO` | Platform backend (`AUTO`, `DSHOW`, `V4L2`, `MSMF`, `SYNTHETIC`). |
| `buffer_size` | `int` | `1` | Driver internal buffer size (`CAP_PROP_BUFFERSIZE`). |
| `auto_reconnect` | `bool` | `True` | Automatically attempt hardware recovery on disconnect. |
| `reconnect_interval_s` | `float` | `2.0` | Polling cadence in seconds during hardware disconnection. |
| `max_consecutive_errors` | `int` | `5` | Consecutive read failures required to engage synthetic failover. |
| `enable_synthetic_fallback` | `bool` | `True` | Never crash if hardware is missing; activate synthetic test card. |
| `synthetic_pattern` | `str` | `"moving_target"` | Pattern style (`"moving_target"`, `"sinusoidal"`, `"center_static"`). |

---

## 4. Synthetic Fallback & Virtual Camera Generator

To uphold the core rule that the SmartVision software **never crashes if a physical webcam is missing or disconnected**, the subsystem features an integrated virtual camera generator (`SyntheticCamera` and `SyntheticTestPattern`).

### 4.1 Features of the Synthetic Test Card
- **SMPTE Color Bars:** 7 standard calibration bars (White, Yellow, Cyan, Green, Magenta, Red, Blue) with 8-level grayscale step wedge.
- **Dynamic Human Target Physics:** Simulates a moving person target with sinusoidal or diagonal bounce physics, bounding box, centroid crosshairs, confidence score (`0.96`), and coordinate label.
- **Live On-Screen Display (OSD):** Real-time UTC timestamp down to milliseconds, sequential frame counter (`FRAME: 000123`), resolution badge, and rotating live heartbeat indicator.
- **OpenCV Interface Parity:** Fully implements `isOpened()`, `read()`, `grab()`, `retrieve()`, `get()`, `set()`, and `release()`.

```python
from vision.camera.synthetic import SyntheticCamera

# Instantiate synthetic camera generating 640x480 @ 30 FPS
cam = SyntheticCamera(width=640, height=480, fps=30.0, realtime_pacing=True)
ret, frame = cam.read()
# frame is a (480, 640, 3) BGR numpy ndarray
print("Ground truth target centroid:", cam.last_ground_truth["centroid"])
cam.release()
```

---

## 5. Camera Service & Auto-Reconnection

`CameraService` orchestrates the complete camera lifecycle, monitoring hardware health and orchestrating seamless failover:

```python
from vision.camera import CameraConfig, CameraService

config = CameraConfig(device_index=0, width=640, height=480, fps=30.0)

# Option A: Context Manager (clean auto-shutdown)
with CameraService(config) as service:
    success, frame, metadata = service.get_frame(timeout=1.0)
    if success:
        print(f"Captured Frame #{metadata.frame_id} (FPS: {metadata.fps_measured})")

# Option B: Explicit Start/Stop
service = CameraService(config)
service.start()
# ... application execution ...
stats = service.get_stats()
print(f"Uptime: {stats['uptime_seconds']}s | Dropped: {stats['dropped_frames']}")
service.stop()
```

### 5.1 Fault Recovery Sequence
1. If a physical camera is unplugged or fails during operation, `CameraCaptureThread` detects consecutive read errors.
2. Upon reaching `max_consecutive_errors` (default 5), `CameraService.on_capture_error()` triggers.
3. The active capture source in `CameraCaptureThread` is instantly hot-swapped to `SyntheticCamera` without throwing exceptions or breaking active HTTP/FastAPI streams.
4. An asynchronous reconnect worker awakens and probes the hardware port every `reconnect_interval_s` (2 seconds).
5. As soon as the USB webcam is plugged back in and successfully reads frames, `CameraService` hot-swaps hardware back into the pipeline.

---

## 6. Low-Latency MJPEG Video Streaming

The streaming generator (`vision.camera.stream.get_mjpeg_stream`) formats video frames into standard HTTP multipart boundaries compatible with any browser and FastAPI:

### 6.1 FastAPI Integration Example
```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from vision.camera import CameraConfig, CameraService, get_mjpeg_stream

app = FastAPI(title="SmartVision Video API")
camera_service = CameraService(CameraConfig(width=640, height=480, fps=30.0))

@app.on_event("startup")
def startup():
    camera_service.start()

@app.on_event("shutdown")
def shutdown():
    camera_service.stop()

@app.get("/api/v1/stream/video.mjpeg")
def video_feed():
    return StreamingResponse(
        get_mjpeg_stream(camera_service, quality=80, overlay_hud=True),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
```

### 6.2 Multipart Boundary Format
Each frame chunk emitted complies with the standard multipart specification:
```http
--frame
Content-Type: image/jpeg
Content-Length: 24512

<JPEG_BINARY_DATA>
```

---

## 7. Local Live Camera Preview Utility

The `preview` utility provides an interactive desktop preview window with a real-time telemetry HUD:

```bash
# Launch preview on default camera (index 0)
python -m vision.camera.preview

# Launch preview with specific resolution and target FPS
python -m vision.camera.preview --index 1 --width 640 --height 480 --fps 30

# Force synthetic test pattern fallback
python -m vision.camera.preview --synthetic

# Run in headless mode for 5 seconds (ideal for automated smoke tests or remote CI)
python -m vision.camera.preview --headless --duration 5.0
```

### 7.1 Interactive Keybindings
| Key | Action | Description |
| :--- | :--- | :--- |
| **`Q` / `ESC`** | Quit | Cleanly stops capture threads and closes window. |
| **`S`** | Snapshot | Captures high-res uncompressed frame to `captures/snapshot_YYYYMMDD_HHMMSS.jpg`. |
| **`F`** | Toggle Fallback | Forces or releases synthetic failover mode to test failover behavior. |
| **`H`** | Toggle HUD | Toggles telemetry overlay (FPS, resolution, dropped frames, status). |

---

## 8. Latency Tuning & Hardware Best Practices

### 8.1 Windows DirectShow (`cv2.CAP_DSHOW`) vs Media Foundation (`cv2.CAP_MSMF`)
- **DirectShow (`CAP_DSHOW`):** Recommended for UVC webcams on Windows. DirectShow exposes fast property negotiation, allows driver buffer size clamping (`CAP_PROP_BUFFERSIZE = 1`), and yields lower acquisition latency (typically 15-25 ms).
- **Media Foundation (`CAP_MSMF`):** Modern Windows API, but OpenCV's MSMF backend often forces 3-frame asynchronous queues that resist buffer clamping.

### 8.2 FourCC Codec Selection: MJPG vs YUY2
- **`MJPG` (Motion JPEG):** The camera sensor compresses frames to JPEG in onboard hardware before transmitting over USB. This is mandatory for running 640x480 @ 30 FPS or 1080p @ 30 FPS over USB 2.0 without exceeding USB bus bandwidth limits.
- **`YUY2` (Raw Uncompressed 4:2:2):** Transmits uncompressed pixel buffers. Consumes ~3x the USB bandwidth. Recommended only when operating over high-speed USB 3.0 ports.

---

## 9. Automated Verification

The automated verification suite in `tests/test_camera_system.py` validates all aspects of the PC camera system:

```bash
# Run standalone unit test runner
python tests/test_camera_system.py

# Or execute with pytest
pytest tests/test_camera_system.py -v
```

### Verified Test Cases (26 Tests):
1. `TestCameraConfig`: Defaults, serialization, platform backend resolution (`CAP_DSHOW` / `CAP_V4L2`).
2. `TestCameraProbe`: Device index discovery, capability querying, graceful handling of non-existent devices, DirectShow FourCC GUID decoding (`RGB24`/`RGB32`).
3. `TestSyntheticPatternAndCamera`: Frame shape, dtype, dynamic target trajectories, OpenCV interface parity, drift-free monotonic pacing.
4. `TestCameraCaptureThread`: Double-buffering, zero-lag queue draining, dropped frame counting, rolling FPS, concurrent multi-client frame consumption without race conditions.
5. `TestCameraService`: Physical startup, synthetic forced startup, failover on repeated errors, auto-reconnect hardware restoration, enforcement of disabled fallback.
6. `TestMJPEGStreaming`: Multipart boundary formatting, JPEG magic byte validation (`\xff\xd8\xff`), async stream generation, multi-client async streaming, FPS limiting.
