# SmartVision: Electrical & Hardware Interfacing Plan

**Document Version:** 1.0.0 (Phase 0 Baseline)  
**Author:** SmartVision Engineering Team  
**Scope:** ESP32-S3 N16R8 GPIO Mapping, Voltage Shifting, Driver Circuits, Power Budget, and Mechanical Limits  
**Status:** Approved Electrical Specification  

---

## 1. ESP32-S3 N16R8 Pin Allocation & Silicon Constraints

### 1.1 GPIO Allocation Table

| Function | ESP32-S3 GPIO | Direction | Electrical Interface / Characteristics | Destination | Default State |
|---|---|---|---|---|---|
| **PCA9685 SDA** | GPIO 8 | Bidirectional | 3.3V Open-Drain, 4.7kΩ pull-up to 3.3V | PCA9685 SDA | High (I2C Idle) |
| **PCA9685 SCL** | GPIO 9 | Output (Clock) | 3.3V Push-Pull / Open-Drain, 4.7kΩ pull-up | PCA9685 SCL | High (I2C Idle) |
| **PCA9685 OE** | GPIO 12 | Output | 3.3V Push-Pull (Active LOW Output Enable) | PCA9685 OE Pin | LOW (Enabled) |
| **HC-SR04 Trig** | GPIO 4 | Output | 3.3V Push-Pull (10 µs trigger pulse) | HC-SR04 Trig Pin | LOW |
| **HC-SR04 Echo** | GPIO 5 | Input | 3.3V Logic (Stepped down from 5V via Divider) | Divider Midpoint | High-Impedance |
| **HC-SR501 PIR** | GPIO 6 | Input | 3.3V Logic (Native 3.3V output from PIR LDO) | HC-SR501 OUT Pin | Pull-down enabled |
| **Active Buzzer** | GPIO 7 | Output | 3.3V Push-Pull (Drives 2N2222 Base via 1kΩ) | Transistor Base | LOW (Silent) |
| **Status LED** | GPIO 10 | Output | 3.3V Push-Pull via 330Ω series resistor | LED Anode | LOW |

### 1.2 Reserved & Excluded Silicon Pins (ESP32-S3 N16R8)

1. **Octal PSRAM High-Speed Bus (GPIO 33–37):**  
   The ESP32-S3 N16R8 module integrates 8 MB Octal SPI PSRAM operating at up to 120 MHz. **GPIO 33, 34, 35, 36, and 37 are internally bonded directly to the Octal PSRAM die.** Any external connection or software reconfiguration of these pins corrupts the memory controller, leading to immediate CPU panics (`Cache disabled but cached memory region accessed`). They are strictly excluded.
2. **SPI Flash Bus (GPIO 26–32):**  
   Dedicated internally to the 16 MB Quad-SPI Flash memory chip. Reserved.
3. **Boot Strapping Pins (GPIO 0, 3, 45, 46):**  
   Control boot mode selection, VDD_SPI voltage, and ROM logging. Must remain unencumbered by external pull-ups or low-impedance loads during power-on reset.
4. **Native USB Serial/JTAG (GPIO 19, 20):**  
   Wired to the on-chip USB PHY for flashing and hardware debugging over USB-C.

---

## 2. Master System Wiring Schematic

```
                         +-----------------------------------+
                         | 5V 5A Regulated DC Power Supply   |
                         +-----------------+-----------------+
                                           |
                    +----------------------+----------------------+
                    | +5V (Heavy 20-22 AWG)|                      | GND (Common Ground)
                    v                      v                      v
        +-----------------------+     +----------+     +-----------------------+
        | PCA9685 Servo Driver  |     | HC-SR04  |     | ESP32-S3 N16R8        |
        | [V+] Screw Terminal   |     | [VCC]    |     | [5V / VIN] Pin        |
        | [GND] Screw Terminal  |     | [GND]    |     | [GND] Pin             |
        +-----------+-----------+     +----+-----+     +-----------+-----------+
                    |                      |                       |
                    | (1000uF Low-ESR Cap) |                       |
                    | across V+ and GND    |                       |
                    v                      |                       |
            +---------------+              |                       |
            | Servos Power  |              |                       |
            +---------------+              |                       |
                    |                      |                       |
  +-----------------+-----------------+    |                       |
  | PCA9685 Logic & I2C Control       |    |                       |
  | [VCC] <--------------------------------------------------------+ (3.3V Logic Rail)
  | [SDA] <========================================================+ (GPIO 8 - I2C SDA)
  | [SCL] <========================================================+ (GPIO 9 - I2C SCL)
  | [OE]  <========================================================+ (GPIO 12 - Hardware OE)
  | [GND] <--------------------------------------------------------+ (Common GND)
  +-----------------------------------+                            |
                                                                   |
  +----------------------------------------------------------------+
  |
  |=== GPIO 4 (Trig Out) -------------> [Trig] HC-SR04
  |
  |                                     [Echo] HC-SR04 (5V Pulse)
  |                                       |
  |                                       +---[ 1kΩ Resistor (R1) ]---+
  |                                       |                           |
  |=== GPIO 5 (Echo In) <-----------------+ (Stepped down to 3.3V)   [2kΩ Resistor (R2)]
  |                                                                   |
  |                                                                  GND
  |
  |=== GPIO 6 (PIR In) <--------------- [OUT] HC-SR501 (Native 3.3V Out)
  |                                     [VCC] connected to 5V Rail
  |                                     [GND] connected to Common GND
  |
  |=== GPIO 7 (Buzzer Out) --[ 1kΩ ]---> Base of NPN Transistor (2N2222)
  |                                       |
  |                                      Collector ---> Buzzer (-)
  |                                       |             Buzzer (+) ---> +5V Rail
  |                                       |             (1N4148 Diode antiparallel)
  |                                      Emitter -----> Common GND
  |
  |=== GPIO 10 (Status LED) --[ 330Ω ]-> LED Anode -> Cathode -> Common GND
  +----------------------------------------------------------------
```

---

## 3. HC-SR04 5V Echo Level-Shifting Circuit

### 3.1 Problem Statement
The HC-SR04 operates at 5.0V DC and generates a 5.0V active-high pulse on its `Echo` pin. Connecting this 5.0V signal directly to an ESP32-S3 GPIO pin breaches the absolute maximum rating ($V_{DD} + 0.3\text{ V} \approx 3.6\text{ V}$), risking ESD structure breakdown and permanent silicon damage.

### 3.2 Voltage Divider Topology & Transfer Function
A passive two-resistor voltage divider safely steps down the 5.0V pulse:

```
[Echo Pin (5.0V)] ----[ R1: 1.0 kΩ ]----+---- [ ESP32-S3 GPIO 5 (3.33V) ]
                                        |
                                  [ R2: 2.0 kΩ ]
                                        |
                                      [ GND ]
```

$$V_{\text{out}} = V_{\text{in}} \cdot \frac{R_2}{R_1 + R_2}$$

Using standard resistor values:
- **Option A ($1.0\text{ k}\Omega\ /\ 2.0\text{ k}\Omega$):**
  $$V_{\text{out}} = 5.0\text{ V} \cdot \frac{2000}{1000 + 2000} = 5.0 \cdot \frac{2}{3} \approx 3.333\text{ V}$$
  - Current drawn from Echo output: $I = \frac{5.0\text{ V}}{3000\ \Omega} \approx 1.67\text{ mA}$ (well within HC-SR04 15 mA drive capability).
- **Option B ($2.0\text{ k}\Omega\ /\ 3.3\text{ k}\Omega$):**
  $$V_{\text{out}} = 5.0\text{ V} \cdot \frac{3300}{2000 + 3300} = 5.0 \cdot \frac{3.3}{5.3} \approx 3.113\text{ V}$$
  - Safely exceeds ESP32-S3 $V_{IH,\text{min}} = 0.75 \times 3.3\text{ V} = 2.475\text{ V}$, even with 5V rail fluctuations.
- **Option C (Zero-purchase 3x $1.0\text{ k}\Omega$ fallback):**
  - $R_1 = 1.0\text{ k}\Omega$, $R_2 = 1.0\text{ k}\Omega + 1.0\text{ k}\Omega$ (two in series) $\implies 1\text{ k}\Omega : 2\text{ k}\Omega$ ratio ($3.33\text{ V}$).

### 3.3 Mathematical Rise-Time & Delay Analysis
A critical concern in ultrasonic timing is whether a passive divider introduces an RC phase delay that degrades distance measurement accuracy.

1. **Thevenin Equivalent Resistance:**
   $$R_{\text{th}} = R_1 \parallel R_2 = \frac{1000 \cdot 2000}{1000 + 2000} = \frac{2 \times 10^6}{3000} \approx 666.7\ \Omega$$
2. **Parasitic Capacitance ($C_p$):**
   - ESP32-S3 input pin capacitance: $C_{\text{pin}} \approx 8\text{ pF}$
   - Breadboard / jumper stray capacitance: $C_{\text{stray}} \approx 12\text{ pF}$
   - Total parasitic capacitance: $C_p = 8 + 12 = 20\text{ pF}$
3. **Time Constant ($\tau$) and 10%–90% Rise Time ($t_r$):**
   $$\tau = R_{\text{th}} \cdot C_p = 666.7\ \Omega \cdot 20 \times 10^{-12}\text{ F} \approx 13.33\text{ ns}$$
   $$t_r = 2.2 \cdot \tau \approx 2.2 \times 13.33\text{ ns} \approx 29.3\text{ ns}$$
4. **Ultrasonic Measurement Impact:**
   - Speed of sound in air: $v \approx 343\text{ m/s} = 0.0343\text{ cm}/\mu\text{s}$.
   - Round-trip echo duration for minimum distance ($2\text{ cm}$):
     $$t_{\text{echo}} = \frac{2 \times 2\text{ cm}}{0.0343\text{ cm}/\mu\text{s}} \approx 116.6\ \mu\text{s}$$
   - Rise-time error percentage:
     $$\text{Error} = \frac{29.3\text{ ns}}{116,600\text{ ns}} \times 100\% \approx 0.025\%$$
   - Spatial error: $\Delta d = \frac{29.3\text{ ns} \times 0.0343\text{ cm}/\mu\text{s}}{2} \approx 0.0005\text{ mm}$.  
   **Conclusion:** The passive voltage divider introduces **zero measurable acoustic error**.

---

## 4. Active Buzzer Transistor Driver Circuit

### 4.1 Problem Statement
An active 5V buzzer draws 35 mA – 45 mA when active. ESP32-S3 GPIO pins are rated for a recommended maximum continuous current of 20 mA. Driving the buzzer directly causes GPIO voltage drop, potential MCU reset, and silicon degradation. Additionally, turning off the buzzer coil generates an inductive voltage transient ($V = -L \frac{di}{dt}$) that can destroy semiconductor junctions.

### 4.2 Circuit Topology
A low-side NPN BJT switch (2N2222, 2N3904, or BC547) isolates the MCU:

```
               +5V Rail
                  |
             +----+----+
             |         |
             |     [ 1N4148 Diode ]
             |     (Cathode to +5V, Anode to Collector)
             |         |
      [ Active Buzzer ]|
             |         |
             +----+----+
                  |
             Collector
                  |
GPIO 7 ---[ 1kΩ RB ]--- Base (2N2222)
                  |
             [ 10kΩ RPD ]
                  |
               Emitter
                  |
              Common GND
```

### 4.3 Component Math & Parameter Derivation
1. **Collector Current ($I_C$):** $I_C \approx 40\text{ mA}$ at 5V.
2. **Forced Beta for Deep Saturation:** $\beta_{\text{forced}} = 15$ ($V_{CE(\text{sat})} \le 0.2\text{ V}$).
3. **Required Base Current ($I_B$):**
   $$I_B = \frac{I_C}{\beta_{\text{forced}}} = \frac{40\text{ mA}}{15} \approx 2.67\text{ mA}$$
4. **Base Resistor Value ($R_B$):**
   $$R_B = \frac{V_{OH} - V_{BE(\text{sat})}}{I_B} = \frac{3.3\text{ V} - 0.7\text{ V}}{0.00267\text{ A}} = \frac{2.6\text{ V}}{0.00267\text{ A}} \approx 973.8\ \Omega$$
   - Select standard value: **$R_B = 1.0\text{ k}\Omega$ (1/4W)**.
   - Sourced current from GPIO 7: $I_B = \frac{3.3 - 0.7}{1000} = 2.60\text{ mA}$ (only $13\%$ of GPIO capacity).
5. **Inductive Flyback Clamping:**
   - Antiparallel 1N4148 diode across buzzer terminals clamps the reverse voltage spike to $V_{CC} + V_F \approx 5.0\text{ V} + 0.7\text{ V} = 5.7\text{ V}$.
6. **Base Pull-Down Resistor ($R_{PD}$):**
   - $10\text{ k}\Omega$ from Base to GND holds the transistor firmly in cutoff during ESP32 bootup and reset cycles.

---

## 5. Power Distribution Architecture & Current Budget

### 5.1 Worst-Case System Current Budget

| Subsystem / Load Component | Model / Type | Operating Voltage | Idle / Normal Current | Peak / Stall Current |
|---|---|---|---|---|
| **Horizontal Pan Servo** | TowerPro MG996R | 5.0V (PCA9685 V+) | 0.60 A (moving) | **2.50 A (full stall)** |
| **Vertical Tilt Servo** | TowerPro MG90S | 5.0V (PCA9685 V+) | 0.25 A (moving) | **0.80 A (full stall)** |
| **Microcontroller Core** | ESP32-S3 N16R8 | 5.0V (VIN / USB) | 0.12 A (active dual core) | **0.45 A (Wi-Fi 802.11b TX bursts)** |
| **Ultrasonic Distance Sensor** | HC-SR04 | 5.0V | 0.015 A | 0.02 A (40 kHz burst) |
| **PIR Motion Sensor** | HC-SR501 | 5.0V | 0.00005 A (quiescent) | 0.001 A |
| **Active Buzzer** | 5V Piezo/Mag | 5.0V | 0.00 A (off) | 0.04 A (active beep) |
| **PCA9685 Logic** | PCA9685 | 3.3V (ESP32 rail) | 0.01 A | 0.01 A |
| **System Status LED** | 3mm Red LED | 3.3V (GPIO 10) | 0.00 A | 0.005 A |
| **TOTALS** | — | — | **0.995 A (typical)** | **3.826 A (worst-case peak)** |

### 5.2 Headroom Margin & Supply Sizing
- **External Power Supply:** Regulated 5.0V DC, 5.00 A continuous rating (25 Watts).
- **Worst-Case Peak Stall Load:** $3.826\text{ A}$.
- **Net Headroom Margin:**
  $$\text{Reserve Headroom} = 5.000\text{ A} - 3.826\text{ A} = 1.174\text{ A} \quad (23.48\% \text{ safety margin})$$
- **Typical Dynamic Operating Load:** $\approx 1.30\text{ A}$ ($26\%$ of rated supply capacity). The power supply operates coolly with high efficiency.

### 5.3 Decoupling & Brownout Prevention
- Servos draw sharp current pulses ($di/dt$) at 50 Hz PWM switching edges.
- Install a **$1000\ \mu\text{F}$ to $2200\ \mu\text{F}$ Low-ESR electrolytic capacitor (10V/16V rating)** directly across the PCA9685 $V+$ and GND screw terminals.
- Parallel with a **$0.1\ \mu\text{F}$ (100 nF) ceramic capacitor** to suppress high-frequency switching transients.

### 5.4 Star-Topology Grounding & Heavy-Gauge Routing Mandate
- **Heavy Gauge Wire (20–22 AWG):** Route directly from the 5V 5A power entry terminal block to the PCA9685 screw terminals.
- **NEVER route servo high-current lines through solderless breadboard rails:** Breadboard contact clips have $0.1 - 0.3\ \Omega$ resistance per contact. A 2.5 A surge through a breadboard track creates a $0.5\text{ V} - 0.75\text{ V}$ drop, generating localized overheating and MCU brownout resets.
- **Common Ground Bonding:** The GND pins of the 5V power supply, the PCA9685 board, and the ESP32-S3 must be bonded together in a star configuration. A missing or high-impedance ground connection results in floating I2C logic levels, I2C bus lockups (`ESP_ERR_TIMEOUT`), and servo twitching.

---

## 6. Mechanical Angle Calibration Limits & Pulse Timing

### 6.1 PCA9685 Register Math
- PWM Frequency: $50\text{ Hz}$ ($T = 20,000\ \mu\text{s}$)
- Prescaler: $\text{round}\left(\frac{25,000,000}{4096 \times 50}\right) - 1 = 121 \ (\text{0x79})$
- Time resolution: $4.8828125\ \mu\text{s/count}$

### 6.2 Axis Calibration Summary Table

| Axis / Servo | PCA9685 Channel | Full Mechanical Range | Calibrated Software Limit | Pulse Width Range | PCA9685 Ticks Range | Home / Center Position | Mechanical Rationale |
|---|---|---|---|---|---|---|---|
| **Pan (MG996R)** | Channel 0 | $0^\circ \text{ to } 180^\circ$ | **$15^\circ \text{ to } 165^\circ$** | $667\ \mu\text{s} - 2333\ \mu\text{s}$ | **137 to 478** | $90.0^\circ$ (307 ticks / $1500\ \mu\text{s}$) | Prevents camera USB cable tension and chassis collision |
| **Tilt (MG90S)** | Channel 1 | $0^\circ \text{ to } 180^\circ$ | **$60^\circ \text{ to } 135^\circ$** | $1167\ \mu\text{s} - 2000\ \mu\text{s}$ | **239 to 410** | $90.0^\circ$ (307 ticks / $1500\ \mu\text{s}$) | Prevents gimbal camera body colliding with pan bracket |

### 6.3 Mechanical Strain Relief & Cable Dressing
- The USB webcam cable runs from the tilting camera head, past the pan bracket, to the host PC.
- Provide a minimum **12 cm service loop** coiled around the central pan pivot axis.
- Fasten the cable to the pan rotating base with a zip tie to isolate mechanical pulling force from the camera mount.
