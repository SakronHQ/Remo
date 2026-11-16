# SmartVision PC Computer Vision & Person Tracking Subsystem

## Overview
The computer vision subsystem is a multi-threaded Python 3.10+ application responsible for real-time video capture from a USB UVC webcam, decoupled buffer draining, automatic synthetic test card failover, deep learning inference using YOLOv8n, multi-person tracking using ByteTrack, anti-jitter mathematical filtering, visual tactical HUD overlays, and low-latency MJPEG video streaming.

## Subsystem Architecture (Phase 4 & Phase 5)
```
vision/
├── __init__.py                # Subsystem-wide top-level exports
├── README.md                  # Subsystem guide & quickstart
├── requirements.txt           # Python dependencies
├── camera/
│   ├── __init__.py            # Camera subsystem exports
│   ├── config.py              # CameraConfig, CameraBackend, FrameMetadata, Presets
│   ├── probe.py               # Hardware camera discovery & capability negotiation
│   ├── capture_thread.py      # Non-blocking double-buffered driver buffer drainer
│   ├── synthetic.py           # SMPTE test card & moving target synthetic camera
│   ├── service.py             # Lifecycle, error handling, auto-reconnect supervisor
│   ├── stream.py              # Synchronous & Asynchronous MJPEG stream generators
│   └── preview.py             # Desktop live camera preview CLI with HUD overlay
├── detection/
│   ├── __init__.py            # Detection subsystem exports
│   ├── types.py               # PersonDetection data model
│   ├── base.py                # BasePersonDetector abstract contract
│   ├── yolo_detector.py       # YOLOv8 person detector (COCO Class 0, CPU/CUDA)
│   ├── mock_detector.py       # Deterministic mock & synthetic frame extractor
│   └── factory.py             # create_detector() with graceful offline failover
└── tracking/
    ├── __init__.py            # Tracking subsystem exports
    ├── kalman.py              # 8D BoxKalmanFilter (pure NumPy)
    ├── bytetrack.py           # ByteTrack multi-object tracker (2-stage association)
    ├── target_selector.py     # Target selection state machine & safe timeout
    ├── pid_controller.py      # DualAxisTrackingController & anti-jitter deadband
    ├── hud.py                 # Visual tactical HUD overlay renderer
    ├── pipeline.py            # Unified TrackingPipeline orchestrator
    └── demo.py                # Interactive CLI tracking demonstration
```

## Quick Start

### 1. Interactive Person Tracking Preview CLI
```bash
# Launch interactive preview on default webcam (Index 0)
python -m vision.tracking.demo

# Launch with synthetic test pattern fallback (no physical webcam needed)
python -m vision.tracking.demo --synthetic

# Run in headless mode for 5 seconds (for CI/automated test verification)
python -m vision.tracking.demo --headless --duration 5.0 --synthetic
```

#### Demo Controls:
- **[Mouse Click]**: Select and lock target at cursor position
- **[A]**: Auto-track primary person (largest bounding box)
- **[M]**: Manual / Idle mode (unlock target)
- **[C]**: Re-center servos to $(90.0^\circ, 90.0^\circ)$
- **[S]**: Save snapshot image to `captures/`
- **[H]**: Toggle tactical HUD overlay
- **[1 - 9]**: Directly select and lock track ID 1 through 9
- **[Q] / [ESC]**: Quit cleanly

### 2. Probe Connected USB Webcams
```bash
# Formatted ASCII capability report
python -m vision.camera.probe

# Machine-readable JSON output
python -m vision.camera.probe --json
```

### 3. Programmatic Tracking Pipeline Usage
```python
from vision.camera import CameraConfig, CameraService
from vision.tracking import TrackingPipeline

cam_config = CameraConfig(width=640, height=480, fps=30.0)
pipeline = TrackingPipeline(frame_width=640, frame_height=480)
pipeline.auto_track_first(strategy="largest")

with CameraService(cam_config) as camera:
    success, frame, metadata = camera.get_frame(timeout=1.0)
    if success:
        result = pipeline.process_frame(frame)
        print(f"Tracking FPS: {result.fps:.1f}")
        print(f"Target locked: {result.target_result.target_locked}")
        if result.control_output.should_dispatch_command:
            servo_cmd = result.control_output.to_servo_command_payload()
            print("Command to ESP32:", servo_cmd)
```

## Automated Verification
Run the 36-test tracking verification suite or the complete project suite:
```bash
# Phase 5 Tracking Suite (36 tests)
python -m pytest tests/test_vision_tracking.py -v

# Full Subsystem Suite (82 tests)
python -m pytest tests/ -v
```
