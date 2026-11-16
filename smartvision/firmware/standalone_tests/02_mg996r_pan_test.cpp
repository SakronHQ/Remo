/**
 * @file 02_mg996r_pan_test.cpp
 * @brief Standalone Test 2: TowerPro MG996R Pan Servo Independent Verification.
 *
 * Hardware Setup:
 * - MG996R connected to PCA9685 Channel 0.
 * - Signal (Orange/White) -> PWM Pin 0.
 * - Power (Red) -> V+ Pin 0.
 * - Ground (Brown/Black) -> GND Pin 0.
 * - PCA9685 V+ and GND powered by External 5V 5A Power Supply.
 * - 1000uF Low-ESR capacitor installed across PCA9685 V+ and GND terminals.
 * - Common GND connected between ESP32-S3 GND and PCA9685 GND.
 * - TILT SERVO MUST BE UNPLUGGED during this test to isolate the high-torque pan motor.
 *
 * Conservative Motion Limits:
 * - Min: 15.0 deg  (137 ticks / ~667 us pulse)
 * - Max: 165.0 deg (478 ticks / ~2333 us pulse)
 * - Center: 90.0 deg (307 ticks / ~1500 us pulse)
 */

#include <Arduino.h>
#include <Wire.h>
#include "hardware_config.h"
#include "pca9685_driver.h"

PCA9685Driver pca(PCA9685_I2C_ADDR, PIN_PCA9685_OE);
float current_pan_angle = SERVO_PAN_CENTER_DEG;

void printBanner() {
    Serial.println("\n========================================================");
    Serial.println("   SMARTVISION HARDWARE TEST 02: MG996R PAN SERVO (CH 0)");
    Serial.println("========================================================");
    Serial.println("Safety Constraints Enforced:");
    Serial.printf("  Channel:                Channel %d\n", SERVO_PAN_CHANNEL);
    Serial.printf("  Conservative Min Limit: %.1f deg (Ticks: %d, ~%d us)\n", 
                  SERVO_PAN_MIN_DEG, SERVO_PAN_MIN_TICKS, (int)(SERVO_PAN_MIN_TICKS * PCA9685_US_PER_TICK));
    Serial.printf("  Center / Neutral:       %.1f deg (Ticks: %d, ~%d us)\n", 
                  SERVO_PAN_CENTER_DEG, SERVO_PAN_CENTER_TICKS, (int)(SERVO_PAN_CENTER_TICKS * PCA9685_US_PER_TICK));
    Serial.printf("  Conservative Max Limit: %.1f deg (Ticks: %d, ~%d us)\n", 
                  SERVO_PAN_MAX_DEG, SERVO_PAN_MAX_TICKS, (int)(SERVO_PAN_MAX_TICKS * PCA9685_US_PER_TICK));
    Serial.println("Power & Wiring Check:");
    Serial.println("  1. External 5V 5A supply MUST be connected to PCA9685 V+ / GND.");
    Serial.println("  2. Common GND MUST be bonded between ESP32 and PCA9685.");
    Serial.println("  3. 1000uF capacitor MUST be across V+ and GND screw terminals.");
    Serial.println("  4. Tilt servo MUST BE UNPLUGGED for this single-axis test.");
    Serial.println("========================================================\n");

    if (esp_reset_reason() == ESP_RST_BROWNOUT) {
        Serial.println(">>> [WARNING] LAST RESET WAS CAUSED BY A BROWNOUT! <<<");
        Serial.println(">>> The 5V power supply sagged below 2.8V during servo movement.");
        Serial.println(">>> Ensure heavy 20-22 AWG power wires and 1000uF capacitor are fitted!\n");
    }
}

/**
 * @brief Smoothly slew the pan servo from current angle to target angle.
 * Prevents high-current inrush spikes that cause brownout resets.
 */
void slewPanTo(float target_deg) {
    target_deg = clampPanAngle(target_deg);
    float step = (target_deg > current_pan_angle) ? SERVO_SLEW_STEP_DEG : -SERVO_SLEW_STEP_DEG;

    Serial.printf("  [SLEW] Moving Pan from %.1f deg -> %.1f deg... ", current_pan_angle, target_deg);
    
    while (abs(target_deg - current_pan_angle) > (SERVO_SLEW_STEP_DEG / 2.0f)) {
        current_pan_angle += step;
        pca.setPanAngle(current_pan_angle);
        delay(SERVO_SLEW_DELAY_MS);
    }

    current_pan_angle = target_deg;
    uint16_t ticks = pca.setPanAngle(current_pan_angle);
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

    // Ensure Channel 1 (Tilt) is silenced for this single-axis test
    pca.turnOff(SERVO_TILT_CHANNEL);

    Serial.println("[STEP 1] Initializing Pan to Neutral Center (90.0 deg)...");
    pca.setPanAngle(SERVO_PAN_CENTER_DEG);
    current_pan_angle = SERVO_PAN_CENTER_DEG;
    delay(1500);
    Serial.println("[PASS] Pan servo centered. Starting verification sweep sequence.\n");
}

void loop() {
    static uint32_t cycle = 1;
    Serial.printf("--- Starting Pan Sweep Cycle #%lu ---\n", (unsigned long)cycle++);

    // 1. Move to Conservative Minimum Limit (15.0 deg)
    Serial.println("Testing Pan Minimum Limit (15.0 deg):");
    slewPanTo(SERVO_PAN_MIN_DEG);
    Serial.println("  Holding at 15.0 deg for 2.0 seconds... (Check for mechanical binding or cable tension)");
    delay(2000);

    // 2. Move to Neutral Center (90.0 deg)
    Serial.println("Returning to Center (90.0 deg):");
    slewPanTo(SERVO_PAN_CENTER_DEG);
    delay(1000);

    // 3. Move to Conservative Maximum Limit (165.0 deg)
    Serial.println("Testing Pan Maximum Limit (165.0 deg):");
    slewPanTo(SERVO_PAN_MAX_DEG);
    Serial.println("  Holding at 165.0 deg for 2.0 seconds... (Check for mechanical binding or cable tension)");
    delay(2000);

    // 4. Return to Center (90.0 deg)
    Serial.println("Returning to Center (90.0 deg):");
    slewPanTo(SERVO_PAN_CENTER_DEG);
    Serial.println("  Cycle Complete! Holding at center for 4 seconds.\n");
    delay(4000);
}
