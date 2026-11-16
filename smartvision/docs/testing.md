# SmartVision: Standalone Verification Procedures & Test Interfaces

**Document Version:** 1.0.0 (Phase 0 Baseline)  
**Author:** SmartVision Engineering Team  
**Scope:** Standalone Testing Procedures, Mock Interface Usage, and Phase 1 Transition Criteria  
**Status:** Approved Testing Specification  

---

## 1. Verification Strategy & Decoupled Testing Rationale

A core engineering principle of SmartVision is **subsystem decoupling**. Hardware, firmware, vision algorithms, backend messaging, and frontend dashboards must each be independently verifiable in isolation.

Through standalone mock interfaces:
- The **Vision Engine** can be tuned against synthetic video frames before the USB camera is mounted.
- The **FastAPI Backend & Next.js Frontend** can be tested against a virtual ESP32 firmware before physical microcontrollers are powered.
- The **ESP32 Firmware** can be verified against simulated WebSocket commands before the full PC stack is deployed.
- The **Complete Closed Loop** can be validated in software simulation (`run_system_sim.py`) to verify PID convergence and protocol stability without risking servo stall or mechanical binding.

---

## 2. Subsystem-by-Subsystem Standalone Verification Procedures

### 2.1 Hardware Bench Verification Procedures (Phase 1 Bench Checklist)

#### Test HW-1: Power Rail Voltage & Ground Continuity
- **Objective:** Verify 5.0V external supply voltage, 3.3V ESP32 rail, and common ground bonding.
- **Tools:** Digital Multimeter (DMM).
- **Procedure:**
  1. Measure DC voltage across PCA9685 $V+$ and GND screw terminals. Confirm $4.90\text{ V} \le V \le 5.20\text{ V}$.
  2. Measure DC voltage between ESP32-S3 3.3V pin and GND. Confirm $3.25\text{ V} \le V \le 3.35\text{ V}$.
  3. Power off supply. Measure resistance between ESP32-S3 GND, PCA9685 GND, and power supply negative terminal. Confirm continuity ($R < 0.5\ \Omega$).
- **Pass Criteria:** Stable voltages within tolerance; solid ground bonding.

#### Test HW-2: HC-SR04 Voltage Divider Validation (Pre-MCU Connection)
- **Objective:** Ensure the Echo signal divider never presents $> 3.6\text{ V}$ to ESP32 GPIO 5.
- **Tools:** Multimeter or Oscilloscope.
- **Procedure:**
  1. Connect HC-SR04 $V_{CC}$ to 5V and GND to common GND.
  2. Connect $1.0\text{ k}\Omega$ resistor from Echo to divider junction, and $2.0\text{ k}\Omega$ (or $3.3\text{ k}\Omega$) resistor from junction to GND. **Leave GPIO 5 disconnected.**
  3. Trigger sensor or place hand in front of transducer.
  4. Measure peak voltage at divider junction.
- **Pass Criteria:** Peak voltage is strictly between $3.00\text{ V}$ and $3.35\text{ V}$.

#### Test HW-3: Transistor Buzzer Driver & Flyback Diode Check
- **Objective:** Verify 2N2222 low-side switching and 1N4148 inductive spike clamping.
- **Procedure:**
  1. Temporarily pull the $1\text{ k}\Omega$ base resistor to 3.3V. Buzzer must sound clearly.
  2. Pull the base resistor to GND. Buzzer must immediately silence completely.
  3. Verify diode polarity: Cathode (striped end) connects to +5V, Anode connects to Transistor Collector.

#### Test HW-4: PCA9685 I2C Bus Enumeration
- **Objective:** Verify I2C communication at address `0x40` on GPIO 8 (SDA) and GPIO 9 (SCL).
- **Procedure:** Upload standard I2C scanner firmware.
- **Expected Console Output:**
  ```text
  Scanning I2C bus (SDA=GPIO8, SCL=GPIO9)...
  I2C device found at address 0x40 !
  I2C scan complete. 1 device found.
  ```

---

### 2.2 Firmware Logic Verification Procedures

#### Test FW-1: Angle Clamping & Tick Computation
- **Objective:** Assert PCA9685 pulse width formulas and hard software bounds.
- **Target Logic:**
  - Pan: $\theta_{\text{pan}} \in [15.0^\circ, 165.0^\circ] \implies \text{ticks} \in [137, 478]$
  - Tilt: $\theta_{\text{tilt}} \in [60.0^\circ, 135.0^\circ] \implies \text{ticks} \in [239, 410]$
- **Verification:** Unit test validates that passing $0^\circ$ clamps to $15^\circ$ ($137$ ticks), and $180^\circ$ clamps to $165^\circ$ ($478$ ticks).

#### Test FW-2: Hardware Comm-Loss Watchdog Timeout
- **Objective:** Verify that servos halt and fail-safe engages when WebSocket packets cease.
- **Procedure:** Send continuous motion commands, then terminate the WebSocket server.
- **Pass Criteria:** ESP32 triggers `FAILSAFE_ACTIVE` within $800\text{ ms}$, freezes servos, and issues warning chirps.

---

### 2.3 Computer Vision Pipeline Verification Procedures

#### Test CV-1: YOLOv8n Person Detection & Bounding Box Extraction
- **Objective:** Verify person detection inference latency and bounding box accuracy.
- **Procedure:** Feed synthetic frames from `tests/mock_camera_stream.py`.
- **Pass Criteria:** Detection latency $\le 35\text{ ms}$ on PC CPU/GPU; person class (`class 0`) correctly detected with confidence $\ge 0.50$.

#### Test CV-2: Dead-Band Non-Linear Filter & Hysteresis
- **Objective:** Verify that noise around frame center ($320 \pm 15\text{ px}$) produces zero angular delta.
- **Procedure:** Feed simulated jittering centroid values ($318\text{ px} \to 322\text{ px} \to 317\text{ px}$).
- **Pass Criteria:** Commanded delta angle remains identically $0.0^\circ$.

---

### 2.4 FastAPI Backend & WebSocket Verification Procedures

#### Test BE-1: Pydantic Schema Validation & Out-of-Bounds Rejection
- **Objective:** Verify that malformed JSON or illegal angles are rejected before reaching firmware.
- **Procedure:** Submit `cmd.servo.move` with `pan: 195.0` or `tilt: 10.0`.
- **Pass Criteria:** FastAPI rejects payload with HTTP 400 / `ERR_OUT_OF_BOUNDS`.

#### Test BE-2: MJPEG Streaming Endpoint
- **Objective:** Verify `/api/v1/stream/video.mjpeg` serves valid multipart JPEG streams without dropping connection.
- **Procedure:** Open endpoint in web browser or run `curl -v http://localhost:8000/api/v1/stream/video.mjpeg`.
- **Pass Criteria:** Server returns `Content-Type: multipart/x-mixed-replace; boundary=frame`.

---

## 3. Mock & Simulation Suite Reference & Usage Guide

The `tests/` directory provides four self-contained standalone tools:

### 3.1 Mock Camera Stream (`tests/mock_camera_stream.py`)
Generates synthetic 640x480 RGB video frames at 30 FPS featuring an animated test pattern and a moving target proxy.

**Features:**
- **Sinusoidal Trajectory:** Horizontal oscillation $x(t) = 320 + 200 \sin(2\pi f t)$.
- **Diagonal Bounce:** Simulates dual-axis pan-tilt motion.
- **Intermittent Occlusion:** Target disappears for 0.5 s every 4 s to test tracking coasting and reacquisition.

**Usage:**
```bash
python tests/mock_camera_stream.py --pattern sinusoidal --fps 30 --duration 10
```

---

### 3.2 Mock ESP32 Firmware (`tests/mock_esp32_firmware.py`)
Emulates the physical ESP32-S3 over WebSocket.

**Features:**
- Connects to backend at `ws://localhost:8000/ws/device`.
- Maintains virtual servo angles with realistic slew-rate inertia ($60^\circ/\text{s}$).
- Enforces mechanical limit checks ($15^\circ \le \theta_{\text{pan}} \le 165^\circ$, $60^\circ \le \theta_{\text{tilt}} \le 135^\circ$).
- Dispatches 10 Hz `telem.sensors` packets with simulated HC-SR04 distance and PIR triggers.
- Implements an 800ms communication watchdog timer.

**Usage:**
```bash
python tests/mock_esp32_firmware.py --url ws://localhost:8000/ws/device --interval 0.1
```

---

### 3.3 Mock Backend Client (`tests/mock_backend_client.py`)
Simulates an automated operator dashboard connected to `ws://localhost:8000/ws/client`.

**Features:**
- Subscribes to telemetry and alert event streams.
- Dispatches manual jog commands (`cmd.servo.move`).
- Stress tests the backend rate limiter by injecting high-frequency command bursts (50 Hz).
- Injects out-of-bounds angles to verify validation errors.

**Usage:**
```bash
python tests/mock_backend_client.py --url ws://localhost:8000/ws/client --mode test
```

---

### 3.4 Automated System Convergence Simulator (`tests/run_system_sim.py`)
Executes a complete closed-loop software simulation without physical hardware:
1. Instantiates a synthetic moving target at offset $x = 480\text{ px}$ (raw error $+160\text{ px}$).
2. Computes deadband filter and PID control delta.
3. Issues `cmd.servo.move` to virtual ESP32 firmware.
4. Updates simulated servo position and camera frame coordinate.
5. Verifies that tracking error $|e_x| \le 15\text{ px}$ converges within $< 1.5\text{ seconds}$.

**Usage:**
```bash
python tests/run_system_sim.py
```

---

## 4. Phase 0 Completion Checklist & Phase 1 Transition Criteria

### Phase 0 Completion Checklist
- [x] Complete system architecture document (`docs/architecture.md`) approved.
- [x] Complete electrical and wiring plan (`docs/wiring.md`) detailing GPIO mapping, level shifting, driver circuits, and power budget.
- [x] Comprehensive communication protocol specification (`docs/protocol.md`) defining typed JSON envelopes, WebSocket schemas, safety policies, and motion smoothing.
- [x] Standalone verification procedures and test interfaces documented (`docs/testing.md`).
- [x] Detailed implementation roadmap for Phases 1 through 9 documented (`docs/roadmap.md`).
- [x] Modular directory structure initialized under `smartvision/` (`firmware/`, `vision/`, `backend/`, `frontend/`, `docs/`, `tests/`).
- [x] Executable mock and simulation scripts implemented in `tests/`:
  - `tests/mock_camera_stream.py`
  - `tests/mock_esp32_firmware.py`
  - `tests/mock_backend_client.py`
  - `tests/run_system_sim.py`
  - `tests/requirements.txt`
- [x] Subsystem starter READMEs created in `firmware/`, `vision/`, `backend/`, `frontend/`.

### Phase 1 Transition Criteria (Hardware Bench Bring-Up)
Phase 1 hardware integration may commence only when the following criteria are satisfied:
1. **Power Supply & Ground Isolation:** External 5V 5A power supply bench-tested and verified with DMM. Common ground bonding wired and checked with continuity tester.
2. **Voltage Divider Pre-Screening:** HC-SR04 5V Echo divider bench-tested with oscilloscope or DMM to verify peak voltage $\le 3.35\text{ V}$ before connection to ESP32 GPIO 5.
3. **Decoupling Installed:** $1000\ \mu\text{F}$ low-ESR capacitor firmly installed across PCA9685 $V+$ and GND screw terminals.
4. **Mechanical Bracket Inspection:** Pan and tilt servo horns manually checked for free rotation throughout the calibrated safe span ($15^\circ - 165^\circ$ pan, $60^\circ - 135^\circ$ tilt) without mechanical binding or cable strain.
5. **Software Test Simulation Pass:** `tests/run_system_sim.py` executes cleanly and confirms closed-loop PID convergence.
