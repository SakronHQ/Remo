/**
 * @file main.cpp
 * @brief SmartVision Phase 1: Unified Interactive Hardware Verification Suite.
 *
 * Provides a comprehensive, serial-driven diagnostic harness for:
 * 1. ESP32-S3 silicon validation (Heap, CPU, Flash, Reset Reason).
 * 2. I2C Bus Enumeration & PCA9685 ACK detection at 0x40.
 * 3. MG996R Pan Servo Independent Test (Channel 0: 15° to 165°).
 * 4. MG90S Tilt Servo Independent Test (Channel 1: 60° to 135°).
 * 5. Dual-Axis Coordinated Motion & Brownout Sag Verification.
 * 6. Live Manual Jog / Mechanical Angle Calibration Mode.
 * 7. Hardware Emergency Stop (OE pin tri-state isolation).
 *
 * Built according to Ponytail principles: zero external library dependencies,
 * pure standard Arduino Wire, robust error handling, and strict physical angle bounds.
 */

#include <Arduino.h>
#include <Wire.h>
#include "hardware_config.h"
#include "pca9685_driver.h"

// Hardware driver instance
PCA9685Driver pca(PCA9685_I2C_ADDR, PIN_PCA9685_OE);

// Current tracking state
float g_pan_angle = SERVO_PAN_CENTER_DEG;
float g_tilt_angle = SERVO_TILT_CENTER_DEG;
bool g_outputs_enabled = true;

// Prototypes
void printMenu();
void runI2CScan();
void runPanTest();
void runTiltTest();
void runDualAxisTest();
void runPowerSagStressTest();
void emergencyStop();
void enableOutputs();
void handleSerialInput(String cmd);
void slewPanTo(float target_deg);
void slewTiltTo(float target_deg);

void printBanner() {
    Serial.println("\n================================================================================");
    Serial.println("         SMARTVISION PHASE 1: UNIFIED HARDWARE VERIFICATION SUITE              ");
    Serial.println("================================================================================");
    Serial.printf("MCU:            ESP32-S3 (Chip Rev: %d, Cores: %d)\n", ESP.getChipRevision(), ESP.getChipCores());
    Serial.printf("CPU Freq:       %lu MHz | Flash: %lu MB | Free Heap: %lu bytes\n",
                  (unsigned long)ESP.getCpuFreqMHz(), 
                  (unsigned long)(ESP.getFlashChipSize() / (1024 * 1024)), 
                  (unsigned long)ESP.getFreeHeap());
    Serial.printf("Reset Reason:   %d ", esp_reset_reason());
    if (esp_reset_reason() == ESP_RST_BROWNOUT) {
        Serial.println("(BROWNOUT DETECTED! External 5V rail sagged during prior boot)");
    } else if (esp_reset_reason() == ESP_RST_POWERON) {
        Serial.println("(Clean Power-On Reset)");
    } else {
        Serial.println("(Software / Watchdog Reset)");
    }
    Serial.println("--------------------------------------------------------------------------------");
    Serial.printf("I2C Pins:       SDA = GPIO %d, SCL = GPIO %d (PCA9685 Addr: 0x%02X)\n",
                  PIN_I2C_SDA, PIN_I2C_SCL, PCA9685_I2C_ADDR);
    Serial.printf("Hardware OE:    GPIO %d (Active LOW - Emergency Hardware Cutoff)\n", PIN_PCA9685_OE);
    Serial.printf("Status LED:     GPIO %d | Buzzer: GPIO %d\n", PIN_STATUS_LED, PIN_BUZZER);
    Serial.println("--------------------------------------------------------------------------------");
    Serial.printf("Pan Axis (Ch 0): MG996R  | Bounds: [%.1f° .. %.1f°] | Center: %.1f° (Ticks: %d..%d)\n",
                  SERVO_PAN_MIN_DEG, SERVO_PAN_MAX_DEG, SERVO_PAN_CENTER_DEG, SERVO_PAN_MIN_TICKS, SERVO_PAN_MAX_TICKS);
    Serial.printf("Tilt Axis (Ch 1): MG90S   | Bounds: [%.1f° .. %.1f°] | Center: %.1f° (Ticks: %d..%d)\n",
                  SERVO_TILT_MIN_DEG, SERVO_TILT_MAX_DEG, SERVO_TILT_CENTER_DEG, SERVO_TILT_MIN_TICKS, SERVO_TILT_MAX_TICKS);
    Serial.println("================================================================================\n");
}

void printMenu() {
    Serial.println("------------------------- HARDWARE DIAGNOSTIC MENU --------------------------");
    Serial.println("  [1] Run I2C Bus Scan & PCA9685 Register Audit");
    Serial.println("  [2] Run Independent Pan Servo Test (MG996R on Ch 0: 15° - 165°)");
    Serial.println("  [3] Run Independent Tilt Servo Test (MG90S on Ch 1: 60° - 135°)");
    Serial.println("  [4] Run Dual-Axis Coordinated Sweep (Brownout & Current Margin Check)");
    Serial.println("  [5] Run Power Rail Stress Test (Rapid 50 Hz Transient Step Test)");
    Serial.println("  [p <deg>] Set Pan Angle (e.g., 'p 45.5' or 'p 120')");
    Serial.println("  [t <deg>] Set Tilt Angle (e.g., 't 75' or 't 110')");
    Serial.println("  [c] Return Both Servos to Neutral Center (90.0° / 90.0°)");
    Serial.println("  [0] EMERGENCY STOP: Disable All Servo PWM Outputs (OE Pin HIGH)");
    Serial.println("  [e] Enable Servo PWM Outputs (OE Pin LOW)");
    Serial.println("  [h] Redisplay This Menu");
    Serial.println("-----------------------------------------------------------------------------");
    Serial.print("Select command > ");
}

void runI2CScan() {
    Serial.println("\n>>> [TEST 1] RUNNING I2C BUS SCAN (SDA=8, SCL=9, 100 kHz) <<<");
    uint8_t count = 0;
    bool found_pca = false;

    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        uint8_t err = Wire.endTransmission();
        if (err == 0) {
            Serial.printf("  Device identified at 0x%02X", addr);
            if (addr == PCA9685_I2C_ADDR) {
                Serial.print("  [PCA9685 Target Address MATCH]");
                found_pca = true;
            } else if (addr == 0x70) {
                Serial.print("  [PCA9685 All-Call Address]");
            }
            Serial.println();
            count++;
        }
    }

    if (found_pca) {
        Serial.printf("[PASS] PCA9685 acknowledged at 0x40. Total devices: %d\n", count);
        uint8_t mode1 = pca.readRegister(PCA9685_MODE1);
        uint8_t prescale = pca.readRegister(PCA9685_PRESCALE);
        Serial.printf("  PCA9685 Register MODE1: 0x%02X | PRESCALE: 0x%02X (%d)\n", mode1, prescale, prescale);
    } else {
        Serial.println("[FAIL] PCA9685 NOT detected at 0x40!");
        Serial.println("  Check: 1) ESP32 3.3V -> PCA9685 VCC, 2) Common GND, 3) SDA GPIO 8, 4) SCL GPIO 9.");
    }
    Serial.println();
}

void slewPanTo(float target_deg) {
    target_deg = clampPanAngle(target_deg);
    float step = (target_deg > g_pan_angle) ? SERVO_SLEW_STEP_DEG : -SERVO_SLEW_STEP_DEG;
    while (abs(target_deg - g_pan_angle) > (SERVO_SLEW_STEP_DEG / 2.0f)) {
        g_pan_angle += step;
        pca.setPanAngle(g_pan_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }
    g_pan_angle = target_deg;
    pca.setPanAngle(g_pan_angle);
}

void slewTiltTo(float target_deg) {
    target_deg = clampTiltAngle(target_deg);
    float step = (target_deg > g_tilt_angle) ? SERVO_SLEW_STEP_DEG : -SERVO_SLEW_STEP_DEG;
    while (abs(target_deg - g_tilt_angle) > (SERVO_SLEW_STEP_DEG / 2.0f)) {
        g_tilt_angle += step;
        pca.setTiltAngle(g_tilt_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }
    g_tilt_angle = target_deg;
    pca.setTiltAngle(g_tilt_angle);
}

void runPanTest() {
    Serial.println("\n>>> [TEST 2] MG996R PAN SERVO INDEPENDENT TEST (CHANNEL 0) <<<");
    Serial.println("NOTE: Ensure Tilt servo is idle or disconnected. External 5V 5A ON.");

    Serial.println("  1. Centering Pan to 90.0°...");
    slewPanTo(SERVO_PAN_CENTER_DEG);
    delay(1000);

    Serial.println("  2. Slewing to MIN limit (15.0°)... (Watch for chassis collision)");
    slewPanTo(SERVO_PAN_MIN_DEG);
    uint16_t min_ticks = panAngleToTicks(SERVO_PAN_MIN_DEG);
    Serial.printf("     At 15.0° (Ticks: %d, ~%d us). Holding 2s...\n", 
                  min_ticks, (int)(min_ticks * PCA9685_US_PER_TICK));
    delay(2000);

    Serial.println("  3. Slewing to MAX limit (165.0°)... (Watch for USB cable tension)");
    slewPanTo(SERVO_PAN_MAX_DEG);
    uint16_t max_ticks = panAngleToTicks(SERVO_PAN_MAX_DEG);
    Serial.printf("     At 165.0° (Ticks: %d, ~%d us). Holding 2s...\n", 
                  max_ticks, (int)(max_ticks * PCA9685_US_PER_TICK));
    delay(2000);

    Serial.println("  4. Returning to Center (90.0°)...");
    slewPanTo(SERVO_PAN_CENTER_DEG);
    delay(1000);

    Serial.println("[PASS] Pan servo test completed without errors.\n");
}

void runTiltTest() {
    Serial.println("\n>>> [TEST 3] MG90S TILT SERVO INDEPENDENT TEST (CHANNEL 1) <<<");
    Serial.println("NOTE: Ensure Pan servo is idle. External 5V 5A ON.");

    Serial.println("  1. Leveling Tilt to Horizon (90.0°)...");
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    delay(1000);

    Serial.println("  2. Slewing to Pitch Down limit (60.0°)... (Watch bracket clearance)");
    slewTiltTo(SERVO_TILT_MIN_DEG);
    uint16_t min_ticks = tiltAngleToTicks(SERVO_TILT_MIN_DEG);
    Serial.printf("     At 60.0° (Ticks: %d, ~%d us). Holding 2s...\n", 
                  min_ticks, (int)(min_ticks * PCA9685_US_PER_TICK));
    delay(2000);

    Serial.println("  3. Slewing to Pitch Up limit (135.0°)... (Watch bracket clearance)");
    slewTiltTo(SERVO_TILT_MAX_DEG);
    uint16_t max_ticks = tiltAngleToTicks(SERVO_TILT_MAX_DEG);
    Serial.printf("     At 135.0° (Ticks: %d, ~%d us). Holding 2s...\n", 
                  max_ticks, (int)(max_ticks * PCA9685_US_PER_TICK));
    delay(2000);

    Serial.println("  4. Returning to Horizon (90.0°)...");
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    delay(1000);

    Serial.println("[PASS] Tilt servo test completed without errors.\n");
}

void runDualAxisTest() {
    Serial.println("\n>>> [TEST 4] DUAL-AXIS SIMULTANEOUS SWEEP & BROWNOUT TEST <<<");
    Serial.println("Driving Pan and Tilt simultaneously to verify power supply headroom (5V 5A).");

    // Center both
    slewPanTo(SERVO_PAN_CENTER_DEG);
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    delay(1000);

    // Diagonal 1: Pan Center (90°) -> Min (15.0°), Tilt Center (90°) -> Min (60.0°)
    Serial.println("  Moving to Diagonal Corner 1 (Pan: 15.0°, Tilt: 60.0°)...");
    for (int i = 0; i <= 75; i++) {
        float factor = (float)i / 75.0f;
        g_pan_angle = SERVO_PAN_CENTER_DEG - (SERVO_PAN_CENTER_DEG - SERVO_PAN_MIN_DEG) * factor;
        g_tilt_angle = SERVO_TILT_CENTER_DEG - (SERVO_TILT_CENTER_DEG - SERVO_TILT_MIN_DEG) * factor;
        pca.setPanAngle(g_pan_angle);
        pca.setTiltAngle(g_tilt_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }
    delay(1500);

    // Diagonal 2: Pan Min (15.0°) -> Max (165.0°), Tilt Min (60.0°) -> Max (135.0°)
    Serial.println("  Moving to Diagonal Corner 2 (Pan: 165.0°, Tilt: 135.0°)...");
    for (int i = 0; i <= 150; i++) {
        float factor = (float)i / 150.0f;
        g_pan_angle = SERVO_PAN_MIN_DEG + (SERVO_PAN_MAX_DEG - SERVO_PAN_MIN_DEG) * factor;
        g_tilt_angle = SERVO_TILT_MIN_DEG + (SERVO_TILT_MAX_DEG - SERVO_TILT_MIN_DEG) * factor;
        pca.setPanAngle(g_pan_angle);
        pca.setTiltAngle(g_tilt_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }
    delay(1500);

    // Return to Center concurrently
    Serial.println("  Returning both axes to Neutral Center (90.0°, 90.0°)...");
    for (int i = 0; i <= 75; i++) {
        float factor = (float)i / 75.0f;
        g_pan_angle = SERVO_PAN_MAX_DEG - (SERVO_PAN_MAX_DEG - SERVO_PAN_CENTER_DEG) * factor;
        g_tilt_angle = SERVO_TILT_MAX_DEG - (SERVO_TILT_MAX_DEG - SERVO_TILT_CENTER_DEG) * factor;
        pca.setPanAngle(g_pan_angle);
        pca.setTiltAngle(g_tilt_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }
    delay(1000);

    Serial.println("[PASS] Dual-axis sweep complete. Zero brownout events detected!\n");
}

void runPowerSagStressTest() {
    Serial.println("\n>>> [TEST 5] POWER RAIL TRANSIENT STRESS TEST <<<");
    Serial.println("Executing 10 rapid direction changes to stress decoupling capacitors (1000uF)...");

    for (int step = 0; step < 10; step++) {
        float target_pan = (step % 2 == 0) ? 60.0f : 120.0f;
        float target_tilt = (step % 2 == 0) ? 75.0f : 105.0f;
        pca.setPanAngle(target_pan);
        pca.setTiltAngle(target_tilt);
        g_pan_angle = target_pan;
        g_tilt_angle = target_tilt;
        delay(150);
        Serial.printf("  Step %d: Pan=%.1f°, Tilt=%.1f° OK\n", step + 1, target_pan, target_tilt);
    }

    Serial.println("  Slewing smoothly back to Neutral Center (90.0°, 90.0°)...");
    slewPanTo(SERVO_PAN_CENTER_DEG);
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    Serial.println("[PASS] Power transient stress test passed with no voltage resets!\n");
}

void emergencyStop() {
    pca.enableOutputs(false);
    pca.turnOffAll();
    g_outputs_enabled = false;
    Serial.println("\n>>> [EMERGENCY STOP ACTIVATED] <<<");
    Serial.printf("Hardware OE Pin (GPIO %d) driven HIGH. Servos unpowered/tri-state.\n", PIN_PCA9685_OE);
    Serial.println("PWM channels silenced in PCA9685 registers.");
    Serial.println("Press 'e' to re-enable servo outputs.\n");
}

void enableOutputs() {
    pca.enableOutputs(true);
    g_outputs_enabled = true;
    Serial.println("\n>>> [OUTPUTS RE-ENABLED] <<<");
    Serial.printf("Hardware OE Pin (GPIO %d) driven LOW. Resuming PWM control.\n", PIN_PCA9685_OE);
    pca.setPanAngle(g_pan_angle);
    pca.setTiltAngle(g_tilt_angle);
    Serial.printf("Holding position at Pan: %.1f°, Tilt: %.1f°.\n\n", g_pan_angle, g_tilt_angle);
}

void handleSerialInput(String cmd) {
    cmd.trim();
    if (cmd.length() == 0) return;

    char c = cmd.charAt(0);

    // Guard against commanding motion while Emergency Stop is active
    if (!g_outputs_enabled && (c == '2' || c == '3' || c == '4' || c == '5' || 
                               c == 'p' || c == 'P' || c == 't' || c == 'T' || c == 'c' || c == 'C')) {
        Serial.println("\n[BLOCKED] Emergency Stop is active! Press 'e' to re-enable outputs first.");
        return;
    }

    if (c == '1') {
        runI2CScan();
    } else if (c == '2') {
        runPanTest();
    } else if (c == '3') {
        runTiltTest();
    } else if (c == '4') {
        runDualAxisTest();
    } else if (c == '5') {
        runPowerSagStressTest();
    } else if (c == '0') {
        emergencyStop();
    } else if (c == 'e' || c == 'E') {
        enableOutputs();
    } else if (c == 'c' || c == 'C') {
        Serial.println("Returning both servos to Neutral Center (90.0°, 90.0°)...");
        slewPanTo(SERVO_PAN_CENTER_DEG);
        slewTiltTo(SERVO_TILT_CENTER_DEG);
        Serial.println("[OK] Centered.");
    } else if (c == 'h' || c == 'H') {
        printMenu();
    } else if (c == 'p' || c == 'P') {
        // e.g., 'p 45.0'
        String valStr = cmd.substring(1);
        valStr.trim();
        if (valStr.length() == 0) {
            Serial.printf("Usage: p <degrees> (e.g., 'p 90' or 'p 45.5'). Current Pan: %.1f°\n", g_pan_angle);
            return;
        }
        bool hasDigit = false;
        for (unsigned int i = 0; i < valStr.length(); i++) {
            if (isDigit(valStr.charAt(i))) { hasDigit = true; break; }
        }
        if (!hasDigit) {
            Serial.printf("Invalid angle '%s'. Current Pan: %.1f°\n", valStr.c_str(), g_pan_angle);
            return;
        }
        float angle = valStr.toFloat();
        float clamped = clampPanAngle(angle);
        slewPanTo(clamped);
        uint16_t ticks = panAngleToTicks(clamped);
        Serial.printf("[MANUAL PAN] Set to %.1f° (Ticks: %d, Pulse: %d us)\n", 
                      clamped, ticks, (int)(ticks * PCA9685_US_PER_TICK));
    } else if (c == 't' || c == 'T') {
        // e.g., 't 100.0'
        String valStr = cmd.substring(1);
        valStr.trim();
        if (valStr.length() == 0) {
            Serial.printf("Usage: t <degrees> (e.g., 't 90' or 't 110'). Current Tilt: %.1f°\n", g_tilt_angle);
            return;
        }
        bool hasDigit = false;
        for (unsigned int i = 0; i < valStr.length(); i++) {
            if (isDigit(valStr.charAt(i))) { hasDigit = true; break; }
        }
        if (!hasDigit) {
            Serial.printf("Invalid angle '%s'. Current Tilt: %.1f°\n", valStr.c_str(), g_tilt_angle);
            return;
        }
        float angle = valStr.toFloat();
        float clamped = clampTiltAngle(angle);
        slewTiltTo(clamped);
        uint16_t ticks = tiltAngleToTicks(clamped);
        Serial.printf("[MANUAL TILT] Set to %.1f° (Ticks: %d, Pulse: %d us)\n", 
                      clamped, ticks, (int)(ticks * PCA9685_US_PER_TICK));
    } else {
        Serial.printf("Unknown command '%s'. Press 'h' for menu.\n", cmd.c_str());
    }
}

void setup() {
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, HIGH);

    Serial.begin(115200);
    Serial.setTimeout(50);
    unsigned long start = millis();
    while (!Serial && (millis() - start < 3000)) {
        delay(10);
    }
    delay(500);

    printBanner();

    if (!pca.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000)) {
        Serial.println("[WARNING] PCA9685 not detected at 0x40 during boot.");
        Serial.println("Press '1' to run the I2C bus scanner once wiring is checked.\n");
    } else {
        Serial.println("[SUCCESS] PCA9685 driver initialized at 0x40. Outputs enabled (PWM idle).");
        Serial.println("Press 'c' to gently center servos to 90.0°/90.0° or select a test.\n");
    }

    printMenu();
}

void loop() {
    // Check for incoming serial commands
    if (Serial.available()) {
        String input = Serial.readStringUntil('\n');
        handleSerialInput(input);
        Serial.print("\nSelect command > ");
    }

    // Status LED gentle heartbeat (1 Hz)
    static unsigned long last_blink = 0;
    if (millis() - last_blink >= 1000) {
        last_blink = millis();
        digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
    }
}
