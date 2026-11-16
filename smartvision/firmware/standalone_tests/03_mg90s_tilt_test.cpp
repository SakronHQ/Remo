/**
 * @file 03_mg90s_tilt_test.cpp
 * @brief Standalone Test 3: TowerPro MG90S Tilt Servo Independent Verification.
 *
 * Hardware Setup:
 * - MG90S connected to PCA9685 Channel 1.
 * - Signal (Orange/White) -> PWM Pin 1.
 * - Power (Red) -> V+ Pin 1.
 * - Ground (Brown/Black) -> GND Pin 1.
 * - PCA9685 V+ and GND powered by External 5V 5A Power Supply.
 * - Common GND connected between ESP32-S3 GND and PCA9685 GND.
 * - PAN SERVO (MG996R) MUST BE UNPLUGGED during this test to isolate the tilt axis.
 *
 * Conservative Motion Limits:
 * - Min (Downward Pitch): 60.0 deg  (239 ticks / ~1167 us pulse)
 * - Max (Upward Pitch):   135.0 deg (410 ticks / ~2000 us pulse)
 * - Center / Horizon:     90.0 deg  (307 ticks / ~1500 us pulse)
 */

#include <Arduino.h>
#include <Wire.h>
#include "hardware_config.h"
#include "pca9685_driver.h"

PCA9685Driver pca(PCA9685_I2C_ADDR, PIN_PCA9685_OE);
float current_tilt_angle = SERVO_TILT_CENTER_DEG;

void printBanner() {
    Serial.println("\n========================================================");
    Serial.println("   SMARTVISION HARDWARE TEST 03: MG90S TILT SERVO (CH 1)");
    Serial.println("========================================================");
    Serial.println("Safety Constraints Enforced:");
    Serial.printf("  Channel:                Channel %d\n", SERVO_TILT_CHANNEL);
    Serial.printf("  Conservative Min Limit: %.1f deg (Ticks: %d, ~%d us - Pitch Down)\n", 
                  SERVO_TILT_MIN_DEG, SERVO_TILT_MIN_TICKS, (int)(SERVO_TILT_MIN_TICKS * PCA9685_US_PER_TICK));
    Serial.printf("  Center / Level Horizon: %.1f deg (Ticks: %d, ~%d us)\n", 
                  SERVO_TILT_CENTER_DEG, SERVO_TILT_CENTER_TICKS, (int)(SERVO_TILT_CENTER_TICKS * PCA9685_US_PER_TICK));
    Serial.printf("  Conservative Max Limit: %.1f deg (Ticks: %d, ~%d us - Pitch Up)\n", 
                  SERVO_TILT_MAX_DEG, SERVO_TILT_MAX_TICKS, (int)(SERVO_TILT_MAX_TICKS * PCA9685_US_PER_TICK));
    Serial.println("Power & Wiring Check:");
    Serial.println("  1. External 5V 5A supply connected to PCA9685 V+ / GND.");
    Serial.println("  2. Common GND bonded between ESP32 and PCA9685.");
    Serial.println("  3. Pan servo (MG996R) UNPLUGGED for this single-axis test.");
    Serial.println("========================================================\n");
}

/**
 * @brief Smoothly slew the tilt servo from current angle to target angle.
 */
void slewTiltTo(float target_deg) {
    target_deg = clampTiltAngle(target_deg);
    float step = (target_deg > current_tilt_angle) ? SERVO_SLEW_STEP_DEG : -SERVO_SLEW_STEP_DEG;

    Serial.printf("  [SLEW] Moving Tilt from %.1f deg -> %.1f deg... ", current_tilt_angle, target_deg);
    
    while (abs(target_deg - current_tilt_angle) > (SERVO_SLEW_STEP_DEG / 2.0f)) {
        current_tilt_angle += step;
        pca.setTiltAngle(current_tilt_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }

    current_tilt_angle = target_deg;
    uint16_t ticks = pca.setTiltAngle(current_tilt_angle);
    Serial.printf("ARRIVED! (Ticks: %d, Pulse: %d us)\n", ticks, (int)(ticks * PCA9685_US_PER_TICK));
}

void setup() {
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, HIGH);

    Serial.begin(115200);
    unsigned long start = millis();
    while (!Serial && (millis() - start < 3000)) {
        delay(10);
    }
    delay(500);

    printBanner();

    if (!pca.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000)) {
        Serial.println("[FATAL] PCA9685 not detected at 0x40! Check I2C wiring.");
        while (1) {
            digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
            delay(200);
        }
    }

    // Ensure Channel 0 (Pan) is silenced for this single-axis test
    pca.turnOff(SERVO_PAN_CHANNEL);

    Serial.println("[STEP 1] Initializing Tilt to Level Horizon (90.0 deg)...");
    pca.setTiltAngle(SERVO_TILT_CENTER_DEG);
    current_tilt_angle = SERVO_TILT_CENTER_DEG;
    delay(1500);
    Serial.println("[PASS] Tilt servo leveled. Starting verification sweep sequence.\n");
}

void loop() {
    static uint32_t cycle = 1;
    Serial.printf("--- Starting Tilt Sweep Cycle #%lu ---\n", (unsigned long)cycle++);

    // 1. Move to Conservative Minimum Limit (60.0 deg - Pitch Down)
    Serial.println("Testing Tilt Minimum Limit (60.0 deg - Down):");
    slewTiltTo(SERVO_TILT_MIN_DEG);
    Serial.println("  Holding at 60.0 deg for 2.0 seconds... (Check camera bracket clearance)");
    delay(2000);

    // 2. Return to Level Horizon (90.0 deg)
    Serial.println("Returning to Level (90.0 deg):");
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    delay(1000);

    // 3. Move to Conservative Maximum Limit (135.0 deg - Pitch Up)
    Serial.println("Testing Tilt Maximum Limit (135.0 deg - Up):");
    slewTiltTo(SERVO_TILT_MAX_DEG);
    Serial.println("  Holding at 135.0 deg for 2.0 seconds... (Check camera bracket clearance)");
    delay(2000);

    // 4. Return to Level Horizon (90.0 deg)
    Serial.println("Returning to Level (90.0 deg):");
    slewTiltTo(SERVO_TILT_CENTER_DEG);
    Serial.println("  Cycle Complete! Holding at level for 4 seconds.\n");
    delay(4000);
}
