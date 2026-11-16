# SmartVision: Production Operational User Manual & Maintenance Guide

**Document Reference:** `SV-P9-OPSMAN-01`  
**Phase:** 9 — Production Documentation, Packaging & Final Handover  
**Release:** Production 1.0.0  
**Status:** Certified Operational Manual  

---

## 1. System Overview & Safety Principles

SmartVision is an autonomous 2-Degree-of-Freedom (2-DOF) pan-tilt optical tracking system engineered with hardware-enforced fail-safes, real-time telemetry, and multi-tier process isolation.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           OPERATOR WORKSTATION / WEB UI                         │
│                    Next.js 14 Dashboard • HTML5 Canvas HUD                      │
└────────────────────────────────────▲──┬─────────────────────────────────────────┘
                                     │  │ Full-Duplex WebSockets (/ws/client)
                                     │  │ MJPEG Video Stream (/api/v1/stream)
                                     ▼  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         CENTRAL GATEWAY & VISION ENGINE                         │
│                 FastAPI Gateway • YOLOv8n Tracker • Dual-Axis PID               │
└────────────────────────────────────▲──┬─────────────────────────────────────────┘
                                     │  │ Full-Duplex WebSockets (/ws/device)
                                     ▼  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         EMBEDDED GIMBAL & SENSOR RIG                            │
│                 ESP32-S3 • PCA9685 • MG996R / MG90S • HC-SR04/501               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Core Safety Rules
> [!IMPORTANT]
> 1. **Dedicated External Power Supply:** Servos MUST be powered by an external 5.0V regulated power supply capable of at least 3.0A (5.0A recommended). Never power servos directly from the ESP32-S3 3.3V or 5V USB pin.
> 2. **Common Ground Connection:** The external servo supply ground (GND) and the ESP32 ground (GND) must be tied together.
> 3. **Decoupling Capacitance:** A $1000\ \mu\text{F}$ 16V low-ESR electrolytic capacitor must be placed across the PCA9685 power terminal block to suppress servo inductive switching transients.
> 4. **Motion Clearance:** Maintain at least 30 cm of unobstructed spherical radius around the pan/tilt gimbal assembly.

---

## 2. Hardware Bill of Materials & Mechanical Specs

| Component | Part / Model | Operating Voltage | Mechanical / Electrical Spec | Function |
|---|---|---|---|---|
| **MCU** | ESP32-S3 N16R8 | 3.3V (USB / LDO) | Dual Xtensa @ 240MHz, 16MB Flash, 8MB PSRAM | Sensor ingestion, FreeRTOS tasks, Wi-Fi bridge |
| **PWM Controller** | PCA9685 (I2C 0x40) | 3.3V VCC / 5V V+ | 16-channel, 12-bit resolution @ 50 Hz | Jitter-free hardware PWM servo timing |
| **Pan Servo** | TowerPro MG996R | 4.8V – 6.0V | High torque ($10\text{ kg}\cdot\text{cm}$), Metal Gears | Horizontal base rotation ($15^\circ - 165^\circ$) |
| **Tilt Servo** | TowerPro MG90S | 4.8V – 6.0V | Micro metal-gear ($2.2\text{ kg}\cdot\text{cm}$) | Vertical pitch elevation ($60^\circ - 135^\circ$) |
| **Distance Sensor** | HC-SR04 | 5.0V VCC / 3.3V Echo | Ultrasonic 40 kHz, range $2 - 400\text{ cm}$ | Forward obstacle proximity detection |
| **PIR Motion** | HC-SR501 | 5.0V VCC / 3.3V Out | Pyroelectric passive infrared, $120^\circ$ FOV | Intrusion and movement auto-trigger |
| **Acoustic Alarm**| Active 5V Piezo | 5.0V via 2N2222 | Continuous 85 dB @ 10 cm | Audible warning and failsafe alarm |
| **Webcam** | UVC USB Camera | 5.0V USB | 640x480 @ 30 FPS, MJPEG/YUYV | Optical input for YOLO person tracking |

---

## 3. Physical Assembly, Wiring & Calibration

### 3.1 Wiring Schematic Summary

```
ESP32-S3 GPIO Mapping:
  GPIO 8  ────────► PCA9685 SDA (I2C)
  GPIO 9  ────────► PCA9685 SCL (I2C)
  GPIO 5  ────────► HC-SR04 TRIG (Direct 3.3V pulse)
  GPIO 4  ◄──────── HC-SR04 ECHO (Via 1kΩ / 2kΩ Voltage Divider to 3.33V)
  GPIO 6  ◄──────── HC-SR501 OUT (Direct 3.3V logic)
  GPIO 7  ────────► 2N2222 Base via 1kΩ (Active Buzzer Driver)

PCA9685 PWM Channels:
  Channel 0 ──────► MG996R Pan Servo Signal (Orange / Yellow)
  Channel 1 ──────► MG90S Tilt Servo Signal (Orange / Yellow)
```

### 3.2 Mechanical Zero-Point Calibration Procedure
1. Before attaching servo horns to the pan-tilt bracket, power the system and execute the centering command:
   ```bash
   python -c "import urllib.request, json; req = urllib.request.Request('http://localhost:8000/api/v1/camera/control', data=json.dumps({'pan':90.0,'tilt':90.0}).encode(), headers={'Content-Type':'application/json'}); urllib.request.urlopen(req)"
   ```
2. With servos actively held at $90.0^\circ$ neutral:
   - Attach the **Pan Servo horn** such that the camera points forward (orthogonal to the base).
   - Attach the **Tilt Servo horn** such that the camera lens is perfectly horizontal ($0^\circ$ horizon / $90^\circ$ servo angle).
3. Verify mechanical freedom of movement through the certified ranges:
   - **Pan Range:** $15.0^\circ$ (full right) to $165.0^\circ$ (full left).
   - **Tilt Range:** $60.0^\circ$ (downward depression) to $135.0^\circ$ (upward elevation).

---

## 4. Software Environment Setup

### 4.1 Prerequisites
- **Python 3.10+** (Python 3.11 or 3.12 recommended)
- **Node.js 18+** with npm
- **Git**

### 4.2 Installation

```bash
# 1. Clone repository
git clone <repository_url>
cd "Rana Project"

# 2. Configure Python Virtual Environment
cd smartvision
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install Python backend and vision requirements
pip install -r backend/requirements.txt
pip install -r tests/requirements.txt

# 3. Configure Operator Dashboard (Next.js)
cd frontend
npm install
cd ../..
```

---

## 5. One-Click System Launch

SmartVision provides unified launch scripts supporting physical hardware and zero-hardware simulation environments.

### 5.1 Zero-Hardware Simulation Mode (Workstation Testing)
Test the entire four-tier stack without physical servos or webcams attached:

```powershell
# Windows (PowerShell)
.\start_system.ps1 -MockHardware -Synthetic

# Windows (Command Prompt)
start_system.bat --mock-esp32 --synthetic

# Linux / macOS (Bash)
./start_system.sh --mock-esp32 --synthetic
```

### 5.2 Production Hardware Mode
Launch against connected USB webcam and physical ESP32-S3 over local network:

```powershell
# Windows (PowerShell)
.\start_system.ps1

# Windows (Command Prompt)
start_system.bat

# Linux / macOS (Bash)
./start_system.sh
```

### 5.3 Command-Line Supervisor Options
The launcher `run_system.py` supports modular operation:
- `--check-only`: Executes preflight dependency, port, and runtime checks without booting.
- `--no-frontend`: Boots Central Gateway only (headless server deployment).
- `--port 8080`: Customizes backend port.
- `--frontend-port 3001`: Customizes Next.js web client port.
- `--detector-mode [auto|yolo|mock]`: Forces specific vision detector.
- `--debug`: Enables verbose debug trace output.

---

## 6. Operator Dashboard Usage & Tactical HUD

Once launched, navigate to `http://localhost:3000` in any modern web browser.

```
┌───────────────────────────────────────────┬─────────────────────────────────┐
│          LIVE OPTICAL VIEWPORT            │         TELEMETRY PANEL         │
│                                           │                                 │
│    [ID 1: Person (94%)]                   │  Pan:   92.4° [====|====]       │
│    ┌──────────────┐                       │  Tilt:  88.1° [====|====]       │
│    │      ┼       │                       │  Sonar: 84.5 cm [============== ] │
│    │  (Reticle)   │                       │  PIR:   IDLE (No Motion)        │
│    └──────────────┘                       │                                 │
│          ▲                                ├─────────────────────────────────┤
│    [Deadband Box]                         │         MANUAL CONTROLS         │
│                                           │            [  ▲  ]              │
│  HUD Status: ACQUIRED | Error: -4.2px     │        [ ◄ ][ ⊙ ][ ► ]          │
│                                           │            [  ▼  ]              │
│                                           │   Speed: 80%  [ E-STOP ]        │
└───────────────────────────────────────────┴─────────────────────────────────┘
```

### 6.1 Tactical HUD Elements
- **Bounding Boxes:** Yellow/green outlines identify detected human candidates with tracking IDs and model confidence scores.
- **Lock Reticle (Cyan Crosshair):** Highlights the primary target currently tracked by the closed-loop PID controller.
- **Center Deadband Box (Dashed):** Visual representation of the $\pm 15\text{ px}$ hysteresis deadband. When the target centroid rests inside this box, servos cease movement (`is_settled: true`) to prevent mechanical hunting.
- **Kalman Velocity Vectors:** Green trailing lines projecting the predicted target motion trajectory over the next 200 ms.

### 6.2 Target Locking Workflow
1. **Click-to-Track:** Click directly on any detected person's bounding box in the video viewport. The system immediately engages `auto_track` on that track ID.
2. **Auto-Acquire Heuristic:** If no target is manually clicked, the tracker auto-selects according to configured priority:
   - `center_closest`: Target nearest to optical center (default).
   - `largest`: Target with greatest bounding box area (closest subject).
   - `highest_conf`: Target with highest detection score.
3. **Occlusion Coasting:** If a tracked person walks behind an obstacle, ByteTrack maintains track trajectory in `COASTING` state for up to 400 ms. If unrecovered after 3.0 seconds, the system disengages gracefully without jumping to bystanders.

### 6.3 Manual Controls & Speed Responsiveness
- **4-Way D-Pad / Joystick:** Provides direct manual jog actuation. Commands are smoothly interpolated by the ESP32 slew engine ($80.0^\circ/\text{s}$).
- **Speed Slider (0.1 to 1.0):** Dynamically scales servo slew rate from fine precision ($16^\circ/\text{s}$) to high-speed repositioning ($120^\circ/\text{s}$).
- **Center Button (⊙):** Commands instantaneous return to calibrated neutral $(90.0^\circ, 90.0^\circ)$.

### 6.4 Emergency Stop & Failsafe Recovery
- **Global E-Stop Button:** Red button located at the bottom-right of the control panel. Clicking E-Stop immediately sends `sys.safestop`, freezing servo PWM pulses and disengaging all motion.
- **Failsafe Clear / Resume:** Once the mechanical or environmental obstruction is resolved, click "Resume Tracking" to clear the failsafe and resume normal operation.

---

## 7. Diagnostics & Troubleshooting Matrix

| Symptom / Alert | Probable Root Cause | Verified Remediation Step |
|---|---|---|
| **ESP32 reboots when servos move** | Voltage sag / inductive brownout | Verify external 5V 5A power supply. Ensure common ground is connected. Add $1000\ \mu\text{F}$ capacitor across PCA9685 power rails. |
| **`failsafe_active: true` / Buzzer alarming** | 800 ms communication watchdog tripped | Check Wi-Fi signal quality between ESP32 and gateway. Verify router port forwarding and ping latency. Clear failsafe via dashboard. |
| **Servos move erratically / jitter** | PCA9685 I2C noise or PWM drift | Ensure I2C pullup resistors ($4.7\text{ k}\Omega$) are present on SDA/SCL. Keep servo signal lines away from high-current AC mains. |
| **Camera feed shows synthetic test card** | Physical webcam disconnected or index busy | Check USB cable connection. Verify camera index in `SMARTVISION_CAMERA_DEVICE_INDEX` (default 0). Check DirectShow permissions. |
| **Motion blocked with `proximity_obstruction`** | Object closer than 20.0 cm to HC-SR04 sonar | Remove physical obstruction from front of gimbal. Motion auto-unlocks when distance exceeds 25.0 cm (5 cm hysteresis). |
| **PIR sensor false triggering repeatedly** | Thermal drafts or warm-up incomplete | Allow 30-second thermal stabilization after power-on. Avoid placing gimbal directly below HVAC heat vents or in direct sunlight. |
| **WebSocket disconnects with 1006** | Browser network sleep or client port clash | Verify backend is running on port 8000. Restart stack using `start_system.ps1`. Check local firewall permissions. |
