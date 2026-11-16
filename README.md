# SmartVision: Autonomous 2-DOF Pan-Tilt Vision Tracking System

[![Phase](https://img.shields.io/badge/Phase-9%20Production%20Packaging-brightgreen.svg)](#)
[![Tests](https://img.shields.io/badge/Tests-140%20Passed%20(100%25)-brightgreen.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)
[![Status](https://img.shields.io/badge/Status-Production%20Certified-brightgreen.svg)](#)

SmartVision is a high-performance, fail-safe, 2-Degree-of-Freedom (2-DOF) pan-tilt camera tracking and surveillance platform. The system combines an **ESP32-S3 N16R8** embedded controller for real-time actuator driving and sensor acquisition, a **PC-hosted Computer Vision & FastAPI Hub** for YOLOv8n person detection and dual-axis PID control, and a modern **Next.js 14+ Operator Dashboard** for low-latency live streaming, interactive target selection, and telemetry monitoring.

---

## 1. Multi-Tier System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           TIER 5: OPERATOR DASHBOARD                             │
│       Next.js 14 App Router, HTML5 Canvas Vector HUD, React Context Hub          │
└────────────────────────────────────▲──┬──────────────────────────────────────────┘
                                     │  │ Full-Duplex WebSockets (/ws/client)
                                     │  │ MJPEG Video Stream (/api/v1/stream)
                                     ▼  ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                    TIER 4: CENTRAL FASTAPI GATEWAY ROUTER                        │
│      Dual-WebSocket Hub, SystemStateManager, FailsafeService, TrackingWorker     │
└──────────────────▲─────────────────┬───────────────────────────▲─────────────────┘
                   │                 │                           │
  Capture Frame    │                 │ cmd.servo.move            │ telem.sensors
  at 30 FPS        │                 │ cmd.jog / cmd.center      │ alert.event
                   │                 ▼                           │
┌──────────────────┴──────────┐   ┌──────────────────────────────┴─────────────────┐
│ TIER 2 & 3: PC VISION STACK │   │     TIER 1: EMBEDDED HARDWARE / FIRMWARE       │
│ CameraService (UVC/Fallback)│   │ ESP32-S3 Dual-Core Xtensa LX7 @ 240MHz         │
│ YOLOv8n / Mock Detector     │   │ PCA9685 16-Channel 12-bit PWM Controller       │
│ ByteTrack Association Engine│   │ MG996R High-Torque Pan Servo [15°, 165°]       │
│ Dual-Axis PID Controller    │   │ MG90S Micro Metal Tilt Servo [60°, 135°]       │
│ Tactical HUD Overlay Canvas │   │ HC-SR04 Sonar + HC-SR501 PIR + Active Buzzer   │
└─────────────────────────────┘   └────────────────────────────────────────────────┘
```

---

## 2. One-Click Quickstart

### 2.1 Zero-Hardware Workstation Mode (No Physical Webcams or Servos Required)
Simulate all tiers on any PC workstation using procedural synthetic video and virtual ESP32 hardware:

```powershell
# Windows (PowerShell)
.\start_system.ps1 -MockHardware -Synthetic

# Windows (Command Prompt)
start_system.bat --mock-esp32 --synthetic

# Linux / macOS (Bash)
./start_system.sh --mock-esp32 --synthetic
```

### 2.2 Production Hardware Mode
Launch against connected USB webcam and physical ESP32-S3 over local network:

```powershell
# Windows (PowerShell)
.\start_system.ps1

# Windows (Command Prompt)
start_system.bat

# Linux / macOS (Bash)
./start_system.sh
```

Once running:
- **Operator Dashboard:** Open [`http://localhost:3000`](http://localhost:3000)
- **Central Gateway API:** Open [`http://localhost:8000`](http://localhost:8000)
- **Interactive Swagger Docs:** Open [`http://localhost:8000/docs`](http://localhost:8000/docs)
- **MJPEG Video Stream:** View [`http://localhost:8000/api/v1/stream/video.mjpeg`](http://localhost:8000/api/v1/stream/video.mjpeg)

---

## 3. Automated Demonstration & Verification Showcase

SmartVision includes an automated end-to-end demonstration script verifying all 8 operational scenarios (startup, WebSocket sync, autonomous PID tracking, manual jog, sonar collision interlock, PIR motion alerts, watchdog safe-stop, and re-centering):

```bash
python smartvision/tests/demo_system_showcase.py
```
*Metrics and timing are saved automatically to `captures/demo_showcase_log.json`.*

### Test Suite Execution
Run the full test suite across Python and Node.js:

```bash
# 1. Run all 121 Python Unit & Integration Tests (100% Passing)
pytest smartvision/tests -v

# 2. Run all 11 Node.js Operator Dashboard Tests (100% Passing)
cd smartvision/frontend && npm test
```

---

## 4. Master Documentation Catalog

| Document Reference | Scope & Contents | Link |
|---|---|---|
| **System Architecture** | Multi-tier pipeline, concurrency model, data flow | [`docs/architecture.md`](docs/architecture.md) |
| **Wiring & Electrical** | Schematics, pinouts, level shifting, power budget | [`docs/wiring.md`](docs/wiring.md) |
| **Communication Protocol** | WebSocket JSON framing, envelopes, schema catalog | [`docs/protocol.md`](docs/protocol.md) |
| **Operational User Manual** | Production setup, calibration, and troubleshooting | [`docs/operational_user_manual.md`](docs/operational_user_manual.md) |
| **API & Protocol Reference** | REST endpoints, WebSocket schemas, OpenAPI 3.1 | [`docs/api_documentation.md`](docs/api_documentation.md) |
| **OpenAPI 3.1.0 Specification**| Machine-readable JSON OpenAPI specification | [`docs/openapi.json`](docs/openapi.json) |
| **System Integration Report**| Phase 8 field verification, latency matrix | [`docs/system_integration_report.md`](docs/system_integration_report.md) |
| **Final Handover Report** | Phase 9 completion certification, test audit | [`docs/final_handover_report.md`](docs/final_handover_report.md) |
| **Project Roadmap** | Phase 0 through Phase 9 execution record | [`docs/roadmap.md`](docs/roadmap.md) |

---

## 5. License
MIT License. Free for research, commercial, and educational robotics development.


# Remo
