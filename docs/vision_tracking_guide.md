# SmartVision: Computer Vision & Person Tracking Engine Guide

**Document Version:** 1.0.0 (Phase 5 Baseline)  
**Author:** SmartVision Engineering Team  
**Scope:** Deep Learning Person Detection, ByteTrack Multi-Object Tracking, Dual-Axis PID Control, and Visual HUD  
**Status:** Approved Technical Manual  

---

## 1. Subsystem Architectural Overview

The Computer Vision & Person Tracking Engine forms the perceptual and autonomous tracking core of the SmartVision system. It operates on the PC Central Hub tier, consuming raw frames from the `CameraService` (Phase 4), performing deep learning inference, tracking multiple individuals concurrently with persistent IDs, calculating optical error vectors relative to frame center ($320, 240$), executing closed-loop dual-axis PID control with anti-jitter filtering, and emitting formatted JSON movement commands and telemetry.

```
                      +---------------------------------------+
                      |        CameraService (Phase 4)        |
                      |  (Physical Webcam / Synthetic Card)   |
                      +---------------------------------------+
                                          |
                                          | 640x480 @ 30 FPS BGR
                                          v
                      +---------------------------------------+
                      |     YOLOv8n Person Detector           |
                      |  (COCO Class 0, CPU/CUDA or Mock)     |
                      +---------------------------------------+
                                          |
                                          | List[PersonDetection]
                                          v
                      +---------------------------------------+
                      |       ByteTrack Multi-Object Tracker  |
                      |   - 8D Kalman State Estimator         |
                      |   - 2-Stage Bipartite IoU Association |
                      +---------------------------------------+
                                          |
                                          | List[STrack] (Persistent IDs)
                                          v
                      +---------------------------------------+
                      |     Target Selector State Machine     |
                      |   - Click-to-Track / ID Locking       |
                      |   - Auto-Track Heuristics             |
                      |   - Coasting -> Holding -> Timeout    |
                      +---------------------------------------+
                                          |
                                          | Active Target Centroid (cx, cy)
                                          v
                      +---------------------------------------+
                      |    Dual-Axis Closed-Loop Controller   |
                      |   - Inner/Outer Deadband (+-15/25 px) |
                      |   - EMA Low-Pass Filter (alpha=0.35)  |
                      |   - PID Anti-Windup & Slew (80 deg/s) |
                      |   - 20 Hz Command Rate Limiter        |
                      |   - Boundary Clamping [15-165,60-135] |
                      +---------------------------------------+
                                   /             \
                                  /               \
                                 v                 v
                 +-----------------------+   +-----------------------+
                 |   Tactical HUD Overlay|   |   JSON Telemetry      |
                 | - Bounding Boxes & IDs|   | - track.frame_target  |
                 | - Lock Reticle        |   | - cmd.servo.move      |
                 | - Deadband Rectangles |   |   (to ESP32-S3)       |
                 | - Telemetry Banner    |   +-----------------------+
                 +-----------------------+
```

---

## 2. Directory Layout & Module Structure

The tracking subsystem is partitioned into modular packages under `smartvision/vision/`:

```
smartvision/vision/
├── detection/
│   ├── __init__.py           # High-level detection exports
│   ├── types.py              # PersonDetection immutable data model
│   ├── base.py               # BasePersonDetector abstract contract
│   ├── mock_detector.py      # Deterministic mock & synthetic frame extractor
│   ├── yolo_detector.py      # YOLOv8 deep learning person detector (CPU/CUDA)
│   └── factory.py            # create_detector() with graceful offline failover
└── tracking/
    ├── __init__.py           # High-level tracking exports
    ├── kalman.py             # 8-dimensional BoxKalmanFilter (pure NumPy)
    ├── bytetrack.py          # Two-stage ByteTrack multi-object tracker
    ├── target_selector.py    # Target selection state machine & safe timeout
    ├── pid_controller.py     # DualAxisTrackingController & filtering
    ├── hud.py                # Visual tactical HUD overlay renderer
    ├── pipeline.py           # Unified TrackingPipeline orchestrator
    └── demo.py               # Interactive CLI tracking preview utility
```

---

## 3. Person Detection & Graceful Fallback Architecture

### 3.1 Strict Filtering to COCO Class 0 (Person)
The detector processes raw BGR image frames and filters output exclusively to COCO Class 0 (`person`). Any detections of non-human objects (chairs, bags, animals) are rejected at the inference boundary.

### 3.2 Compute Hardware Acceleration
- **CUDA / GPU Acceleration:** Automatically negotiated if `torch.cuda.is_available()`.
- **CPU Fallback:** Executes transparently on standard x86-64 / ARM CPUs using vector instructions.

### 3.3 Zero-Crash Graceful Offline Fallback
In test environments, CI pipelines, or minimal offline deployments where PyTorch or Ultralytics model weights (`yolov8n.pt`) are not present, `create_detector(mode="auto")` automatically catches missing libraries and falls back to `MockPersonDetector`:
- Extracts real-time simulated human targets rendered by `SyntheticTestPattern`.
- Procedural multi-person crossing and occlusion modes.
- Supports manual injection of arbitrary bounding boxes for deterministic unit testing.

---

## 4. ByteTrack Multi-Object Tracking Engine

### 4.1 State Vector Formulation (8-Dimensional Kalman Filter)
Each bounding box is tracked via an 8-dimensional constant-velocity discrete Kalman filter:
$$\mathbf{x} = \begin{bmatrix} c_x & c_y & a & h & v_{cx} & v_{cy} & v_a & v_h \end{bmatrix}^T$$
where:
- $c_x, c_y$: Center coordinates of the bounding box
- $a = w / h$: Aspect ratio
- $h$: Bounding box height
- $v_{cx}, v_{cy}, v_a, v_h$: Respective linear velocities

The state transition matrix $\mathbf{F}$ and measurement matrix $\mathbf{H}$ are defined as:
$$\mathbf{F} = \begin{bmatrix} \mathbf{I}_4 & \mathbf{I}_4 \\ \mathbf{0}_4 & \mathbf{I}_4 \end{bmatrix}, \quad \mathbf{H} = \begin{bmatrix} \mathbf{I}_4 & \mathbf{0}_4 \end{bmatrix}$$

### 4.2 Two-Stage Association Algorithm
Standard multi-object trackers discard detections with low confidence scores (e.g., $< 0.50$), which causes track fragmentation during momentary occlusions or motion blur. ByteTrack resolves this by partitioning detections:

1. **Stage 1 (High-Confidence Association):**
   Matches active `tracked_tracks` with high-confidence detections ($D_{\text{high}}$, confidence $\ge 0.50$) using Intersection-over-Union (IoU) distance.
2. **Stage 2 (Low-Confidence Association):**
   Matches remaining unmatched tracks with low-confidence detections ($D_{\text{low}}$, $0.10 \le \text{confidence} < 0.50$). This recovers tracks undergoing partial occlusion or motion blur without creating false positives.
3. **Stage 3 (Re-Activation):**
   Matches previously lost tracks with remaining high-confidence detections to re-acquire subjects re-entering the frame.
4. **Stage 4 (New Track Initialization):**
   Unmatched high-confidence detections ($\text{confidence} \ge 0.60$) initialize new tracklets.
5. **Stage 5 (Pruning):**
   Lost tracks exceeding `max_lost_frames` (30 frames / ~1.0 s) transition to `Removed` and are purged from memory.

---

## 5. Target Selection & Lost Target State Machine

The `TargetSelector` manages user target selection and enforces safety interlocks.

### 5.1 Selection Modes
- **Click-to-Track:** Ingests mouse click coordinates $(x, y)$. Performs point-in-polygon bounding box hit testing, selecting the intersected target (or nearest centroid within 120 px).
- **Select by Track ID:** Directly locks onto a specific track ID (e.g. keypress `1`–`9` or API command).
- **Auto-Track Primary:** Automatically acquires target using configurable heuristics:
  - `"largest"`: Subject with largest pixel area (closest to camera).
  - `"center_closest"`: Subject closest to frame center $(320, 240)$.
  - `"highest_conf"`: Subject with highest detection score.
- **Stop Tracking / Unlock:** Transitions system back to manual/idle mode.

### 5.2 Safe Occlusion & Lost Target Progression
When the actively tracked target disappears from the frame, the system adheres to strict safety phases:

| Phase | Duration | State | Behavior |
|---|---|---|---|
| **Coasting** | $0 < t_{\text{lost}} \le 400\text{ ms}$ | `TargetState.COASTING` | Decays last commanded angular velocity by $\gamma = 0.70$ per frame to smoothly track through momentary occlusions. |
| **Holding** | $400\text{ ms} < t_{\text{lost}} \le 3000\text{ ms}$ | `TargetState.HOLDING` | Velocity set to $0.0^\circ/\text{s}$. Servos hold last position while awaiting target re-emergence. |
| **Lost / Timeout** | $t_{\text{lost}} > 3000\text{ ms}$ | `TargetState.LOST` | Target lock is safely released. System returns to idle/center. **CRITICAL: System NEVER silently jumps to another person in the scene.** |

---

## 6. Closed-Loop Dual-Axis PID Tracking Controller

### 6.1 Error Vector Definition
Given active target centroid $(x_c, y_c)$ and frame center $(x_0, y_0) = (320.0, 240.0)$:
$$\epsilon_x = x_c - 320.0, \quad \epsilon_y = y_c - 240.0$$

### 6.2 Dual-Threshold Hysteresis Deadband
To eliminate mechanical servo buzzing and acoustic hunt around the center point:
- **Inner Deadband:** $\pm 15.0\text{ px}$. If the target enters this window, tracking settles and output velocity drops to $0.0$.
- **Outer Deadband:** $\pm 25.0\text{ px}$. If the target drifts beyond this window, active tracking resumes.
- **Hysteresis Band ($15\text{ px} < |\epsilon| < 25\text{ px}$):** Maintains the previous state, preventing chatter on the boundary.

$$\text{deadband\_x} = 
\begin{cases} 
0.0 & \text{if settled and } |\epsilon_x| < 25.0\text{ px} \\
0.0 & \text{if active and } |\epsilon_x| \le 15.0\text{ px} \\
\epsilon_x & \text{otherwise}
\end{cases}$$

### 6.3 Exponential Moving Average (EMA) Smoothing
Filters camera sensor quantization noise:
$$e_{\text{filtered}}[k] = \alpha \cdot e_{\text{deadband}}[k] + (1 - \alpha) \cdot e_{\text{filtered}}[k-1] \quad (\alpha = 0.35)$$

### 6.4 PID Formulation with Anti-Windup
For each axis:
$$P(k) = K_p \times e(k)$$
$$I(k) = \text{clamp}\left(I(k-1) + K_i \times e(k) \times \Delta t,\ -I_{\text{max}},\ +I_{\text{max}}\right)$$
$$D(k) = K_d \times \frac{e(k) - e(k-1)}{\Delta t}$$
$$\Delta \theta(k) = \text{clamp}\left(P(k) + I(k) + D(k),\ -\Delta \theta_{\text{max}},\ +\Delta \theta_{\text{max}}\right)$$

When the target settles inside the deadband ($|\epsilon| \le 15\text{ px}$), the integral accumulator is bled to zero to eliminate residual steady-state bias.

### 6.5 Physical Limits & Output Throttling
- **Slew Rate Limiting:** Clamped to a maximum angular rate of $80.0^\circ/\text{s}$ ($\Delta \theta_{\text{slew}} = 80.0 \times \Delta t$).
- **20 Hz Command Rate Limiter:** Servos are actuated at a maximum frequency of 20 Hz ($50\text{ ms}$ interval) to prevent FreeRTOS command buffer overflow and network congestion.
- **Physical Boundary Clamping:**
  - Pan Axis: $15.0^\circ \le \theta_{\text{pan}} \le 165.0^\circ$ (Calibrated Center: $90.0^\circ$)
  - Tilt Axis: $60.0^\circ \le \theta_{\text{tilt}} \le 135.0^\circ$ (Calibrated Center: $90.0^\circ$)

---

## 7. Tactical HUD Overlay

The visual HUD provides operator situational awareness:

| Feature | Styling / Palette | Description |
|---|---|---|
| **Candidate Person** | Thin Green Border `(0, 220, 0)` | Label: `ID: <id> (<conf>)` |
| **Locked Target Box** | Bold Yellow Border `(0, 255, 255)` | 4 Neon Corner Brackets, 12% translucent yellow fill |
| **Lock Reticle** | Concentric Circle & Crosshair | Centered on target centroid with optical line to frame center |
| **Deadband Zones** | Inner Green ($\pm 15\text{ px}$), Outer Amber ($\pm 25\text{ px}$) | Centered at $(320, 240)$ with central optical reticle |
| **Ghost Reticle** | Orange / Red Marker | Displayed during `COASTING` and `HOLDING` phases with time-lost badge |
| **Telemetry Banner** | Slate Bar `(16, 16, 16)` at top | `FPS`, `INFER`, `TARGET [STATE]`, `PAN/TILT`, `ERR`, `DEADBAND` |

---

## 8. Interactive CLI Tracking Demonstration

The interactive tracking preview tool allows full testing of detection, tracking, and servo output.

```bash
# Launch interactive preview on default webcam (Index 0)
python -m vision.tracking.demo

# Launch using synthetic moving target generator
python -m vision.tracking.demo --synthetic

# Run headless verification for 3 seconds (CI/automated tests)
python -m vision.tracking.demo --headless --duration 3.0 --synthetic
```

### Keyboard Shortcuts
- `[Mouse Click]`: Interactively select and lock target at cursor position
- `[A]`: Auto-track primary person (largest bounding box)
- `[M]`: Switch to Manual / Idle mode (unlock target)
- `[C]`: Re-center servos to neutral $(90.0^\circ, 90.0^\circ)$
- `[S]`: Save uncompressed snapshot to `captures/`
- `[H]`: Toggle tactical HUD overlay on/off
- `[1] - [9]`: Directly select and lock onto track ID 1 through 9
- `[Q]` or `[ESC]`: Clean shutdown

---

## 9. Verification & Automated Test Suite

Run the full automated test suite using the project virtual environment:

```bash
& "smartvision/.venv/Scripts/python.exe" -m pytest smartvision/tests/test_vision_tracking.py -v
```

### Test Coverage Summary (36 Assertions):
- `TestPersonDetectionModel`: Dataclass geometry, coordinates, properties, inverted coordinate normalization, JSON serialization.
- `TestPersonDetectors`: Mock detector injection, multi-person simulation, synthetic frame extraction, YOLO fallback, factory modes.
- `TestKalmanFilter`: 8D state vector initiation, constant velocity prediction, measurement update, covariance decay, numerical stability.
- `TestByteTracker`: Multi-person concurrent ID assignment, track persistence, low-confidence stage-2 association, occlusion recovery, track pruning.
- `TestTargetSelector`: Auto-track heuristics ('largest', 'center_closest'), click-to-track hit testing, direct ID locking, safe timeout progression (Coasting -> Holding -> Lost) without silent jumping.
- `TestPIDControllerAndSmoothing`: Hysteresis deadband transitions ($\pm 15$ px / $\pm 25$ px), EMA low-pass filtering, anti-windup clamping, $80^\circ/\text{s}$ slew rate limiting, 20 Hz output rate limiting, physical boundary clamping ($[15, 165]^\circ$, $[60, 135]^\circ$).
- `TestClosedLoopConvergence`: Full closed-loop optical simulation; asserts target error converges within deadband in $< 1.50\text{ s}$.
- `TestHUDOverlay`: Graphical rendering across IDLE, candidate, locked, and ghost target states.
- `TestTrackingPipeline`: Full pipeline integration, `CameraService` ingestion, and `track.frame_target` schema conformance.
