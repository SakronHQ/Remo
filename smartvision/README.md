# SmartVision: Autonomous 2-DOF Pan-Tilt Vision Tracking System

[![Phase](https://img.shields.io/badge/Phase-9%20Production%20Packaging-brightgreen.svg)](#)
[![Tests](https://img.shields.io/badge/Tests-140%20Passed%20(100%25)-brightgreen.svg)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)
[![Status](https://img.shields.io/badge/Status-Production%20Certified-brightgreen.svg)](#)

SmartVision is a high-performance, fail-safe, 2-Degree-of-Freedom (2-DOF) pan-tilt camera tracking and surveillance platform. The system combines an **ESP32-S3 N16R8** embedded controller for real-time actuator driving and sensor acquisition, a **PC-hosted Computer Vision & FastAPI Hub** for YOLOv8n person detection and dual-axis PID control, and a modern **Next.js 14+ Operator Dashboard** for low-latency live streaming, interactive target selection, and telemetry monitoring.

---

## 1. System Overview & Architecture

SmartVision segregates hard real-time hardware actuation from computationally intensive deep learning vision pipelines. Communication across tiers is arbitrated over WebSocket and HTTP streaming connections.

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

## 2. Hardware Bill of Materials (BOM)

### 2.1 Core Components
| Component | Specification | Function in System |
|---|---|---|
| **Microcontroller** | ESP32-S3 N16R8 (16MB Flash, 8MB Octal PSRAM) | FreeRTOS real-time actuator control, sensor polling & Wi-Fi bridge |
| **PWM Driver** | PCA9685 16-Channel 12-Bit I2C PWM Controller | Generates precise 50 Hz PWM servo signals without MCU jitter |
| **Pan Servo** | TowerPro MG996R (Metal Gear, High-Torque) | Horizontal base rotation ($15.0^\circ$ to $165.0^\circ$, neutral $90.0^\circ$) |
| **Tilt Servo** | TowerPro MG90S (Metal Gear, Micro) | Vertical elevation tilt ($60.0^\circ$ to $135.0^\circ$, neutral $90.0^\circ$) |
| **Distance Sensor** | HC-SR04 Ultrasonic Sensor | Forward obstacle proximity detection (2 cm to 400 cm) |
| **Motion Sensor** | HC-SR501 Passive Infrared (PIR) Sensor | Wide-angle thermal motion detection for auto-wake / intrusion alert |
| **Audible Alarm** | Active 5V Piezo/Electromagnetic Buzzer | Acoustic alerts for proximity obstruction and watchdog timeouts |
| **Power Supply** | Regulated 5.0V DC, 5.0A (25 Watts) | Dedicated high-current external servo and logic power |
| **Vision Camera** | USB UVC Webcam (DirectShow, 640x480 @ 30 FPS) | Live video capture for PC YOLOv8 tracking engine |

### 2.2 Supporting Electrical Components
- **Echo Voltage Divider:** $1.0\text{ k}\Omega$ and $2.0\text{ k}\Omega$ (1/4W) resistors stepping down HC-SR04 5V Echo pulse to $3.33\text{ V}$.
- **Buzzer Driver:** 2N2222 NPN BJT transistor, $1.0\text{ k}\Omega$ base resistor, $10\text{ k}\Omega$ base pull-down, and 1N4148 flyback clamp diode.
- **Power Decoupling:** $1000\ \mu\text{F}$ low-ESR electrolytic capacitor + $0.1\ \mu\text{F}$ ceramic capacitor across PCA9685 $V+$ and GND.
- **Hardware Mounting:** 2-DOF Pan-Tilt gimbal bracket with cable strain relief loop.

---

## 3. Software Stack & Technology Choices

| Subsystem | Technologies & Libraries | Key Responsibilities |
|---|---|---|
| **Embedded Firmware** | C++, PlatformIO, FreeRTOS, Arduino-ESP32 | Core-pinned tasks, PCA9685 I2C driver, non-blocking sensor timing, 800ms watchdog |
| **Computer Vision** | Python 3.10+, OpenCV, Ultralytics YOLOv8n, ByteTrack | UVC video capture, person detection, persistent tracking ID, PID control, deadzone/EMA filters |
| **Backend Gateway** | Python 3.10+, FastAPI, Uvicorn, WebSockets, Pydantic v2 | Multi-client WebSocket routing, MJPEG streaming engine, command validation, state arbitration |
| **Frontend Dashboard** | Next.js 14+ (App Router), React, TypeScript, Tailwind CSS | Live video stream, synchronized HTML5 Canvas vector overlay, click-to-lock, manual D-pad, telemetry |
| **Test & Mock Suite** | Python, asyncio, pytest | Standalone simulation of camera frames, virtual ESP32, and closed-loop convergence |

---

## 4. Project Directory Layout

```
smartvision/
├── README.md                      # Project overview, BOM, and quickstart (this file)
├── docs/                          # Authoritative Technical Documentation
│   ├── architecture.md            # Comprehensive end-to-end system architecture
│   ├── wiring.md                  # Electrical pinout, level shifting, power budget
│   ├── protocol.md                # WebSocket JSON protocol schemas & safety specs
│   ├── testing.md                 # Standalone verification procedures & mock usage
│   └── roadmap.md                 # Phase 1 through 9 implementation roadmap
├── firmware/                      # ESP32-S3 FreeRTOS Embedded Firmware
│   └── README.md                  # Firmware architecture & flashing guide
├── vision/                        # PC Computer Vision & Tracking Engine
│   └── README.md                  # Vision pipeline, YOLOv8n, and PID guide
├── backend/                       # FastAPI Central Gateway & WebSockets
│   └── README.md                  # Backend server, endpoints, and architecture
├── frontend/                      # Next.js Operator Dashboard
│   └── README.md                  # Dashboard UI, canvas overlay, and controls
└── tests/                         # Standalone Mock & Verification Suite
    ├── requirements.txt           # Test dependencies
    ├── mock_camera_stream.py      # Synthetic 640x480 video frame generator
    ├── mock_esp32_firmware.py     # Virtual ESP32 WebSocket client & sensor emulator
    ├── mock_backend_client.py     # Simulated operator client & load tester
    └── run_system_sim.py          # Automated closed-loop system convergence simulator
```

---

## 5. Quickstart & Verification Instructions

### 5.1 Environment Prerequisites
- Python 3.10 or higher.
- Git.

### 5.2 Standalone Verification (No Hardware Required)
You can test the entire control loop, WebSocket protocol, and tracking mathematics in standalone simulation:

1. **Install Dependencies:**
   ```bash
   pip install -r tests/requirements.txt
   pip install opencv-python
   ```

2. **Run Person Detection & Tracking Engine Verification (Phase 5):**
   ```bash
   python -m pytest tests/test_vision_tracking.py -v
   ```

3. **Run PC Camera System Verification (Phase 4):**
   ```bash
   python tests/test_camera_system.py
   ```

4. **Run Sensor Integration Verification (Phase 2):**
   ```bash
   python tests/test_sensor_integration.py
   ```

5. **Run Hardware Calibration Verification (Phase 1):**
   ```bash
   python tests/test_hardware_calibration.py
   ```

5. **Run the Closed-Loop Simulation:**
   ```bash
   python tests/run_system_sim.py
   ```
   *The simulator spawns a virtual moving target, executes the deadzone and PID tracking mathematics, sends motion commands to a virtual ESP32 firmware, and verifies that tracking error converges to zero within deadband limits.*

3. **Run the Synthetic Camera Generator:**
   ```bash
   python tests/mock_camera_stream.py --pattern sinusoidal --fps 30 --duration 5
   ```

4. **Run the Virtual ESP32 Firmware Client:**
   ```bash
   python tests/mock_esp32_firmware.py --mode standalone
   ```

5. **Run the Operator Stress Client:**
   ```bash
   python tests/mock_backend_client.py --mode test
   ```

---

## 6. One-Click System Launchers & Demo Showcase

### 6.1 One-Click Launch (Zero-Hardware Workstation Mode)
```powershell
# Windows (PowerShell)
.\start_system.ps1 -MockHardware -Synthetic

# Windows (Command Prompt)
start_system.bat --mock-esp32 --synthetic

# Linux / macOS (Bash)
./start_system.sh --mock-esp32 --synthetic
```

### 6.2 Automated Demonstration Showcase
Run the end-to-end multi-tier showcase verifying all 8 operational scenarios:
```bash
python tests/demo_system_showcase.py
```
*Results and timing metrics are automatically recorded to `captures/demo_showcase_log.json`.*

---

## 7. Master Documentation Index
- [System Architecture Specification](docs/architecture.md)
- [Electrical & Wiring Interfacing Plan](docs/wiring.md)
- [Communication Protocol Specification](docs/protocol.md)
- [Phase 1: Hardware Bench Verification Guide](docs/hardware_verification_guide.md)
- [Phase 2: Sensor Integration & Verification Guide](docs/sensor_integration_guide.md)
- [Phase 3: ESP32-S3 Firmware Guide](docs/firmware_guide.md)
- [Phase 4: PC Camera System & Video Pipeline Guide](docs/camera_system_guide.md)
- [Phase 5: Computer Vision & Person Tracking Guide](docs/vision_tracking_guide.md)
- [Phase 6: Central Gateway Backend Guide](docs/backend_gateway_guide.md)
- [Phase 7/8: Operator Dashboard & Web UI Guide](docs/frontend_dashboard_guide.md)
- [Phase 8: System Integration & Field Verification Report](docs/system_integration_report.md)
- [Phase 9: Operational User Manual & Maintenance Guide](docs/operational_user_manual.md)
- [Phase 9: API Documentation & WebSocket Protocol](docs/api_documentation.md)
- [Phase 9: Machine-Readable OpenAPI 3.1 Specification](docs/openapi.json)
- [Phase 9: Final Handover & Certification Sign-Off Report](docs/final_handover_report.md)
- [Testing & Verification Procedures](docs/testing.md)
- [Project Phases 0–9 Implementation Roadmap](docs/roadmap.md)
