/**
 * @file 06_pir_test.cpp
 * @brief Standalone Test 06: HC-SR501 PIR Motion Sensor Verification.
 *
 * Verifies 30-60 second boot thermal stabilization window management,
 * spurious startup noise rejection, debounced rising-edge motion detection,
 * trigger counting, and hardware Status LED visualization (GPIO 10).
 *
 * Built according to Ponytail principles: lightweight, zero external bloat.
 */

#include <Arduino.h>
#include "hardware_config.h"
#include "hcsr501_driver.h"

HCSR501Driver pir(PIN_PIR_INPUT, PIR_WARMUP_DEFAULT_MS);

uint32_t last_display_ms = 0;
bool prev_warmup_state = true;

void setup() {
    Serial.begin(115200);
    delay(1000);

    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    Serial.println("\n================================================================================");
    Serial.println("         SMARTVISION PHASE 2: HC-SR501 PIR MOTION SENSOR TEST                   ");
    Serial.println("================================================================================");
    Serial.printf("MCU:            ESP32-S3 (Chip Rev: %d)\n", ESP.getChipRevision());
    Serial.printf("PIR Input Pin:  GPIO %d (Native 3.3V logic level, internal pull-down)\n", PIN_PIR_INPUT);
    Serial.printf("Status LED Pin: GPIO %d (Active HIGH motion indicator)\n", PIN_STATUS_LED);
    Serial.printf("Warm-up Window: %lu ms (30.0 seconds thermal stabilization)\n", (unsigned long)PIR_WARMUP_DEFAULT_MS);
    Serial.println("Jumper Mode:    Ensure jumper is set to 'H' (Repeatable Trigger mode)");
    Serial.println("Trimpot Notes:  Tx (Time Delay) fully CCW (~3s); Sx (Sensitivity) ~50% (3-5m)");
    Serial.println("================================================================================");
    Serial.println("Commands: [f] Force bypass warm-up | [r] Reset trigger counter | [h] Help");

    pir.begin();
}

void loop() {
    uint32_t now = millis();
    bool new_trigger = pir.update(now);

    // Drive status LED to mirror motion state
    digitalWrite(PIN_STATUS_LED, pir.isMotionDetected() ? HIGH : LOW);

    // Warm-up Countdown Display
    if (pir.isWarmingUp()) {
        if (now - last_display_ms >= 1000) {
            last_display_ms = now;
            uint32_t remaining_s = (pir.getWarmupRemainingMs(now) + 999) / 1000;
            float progress = pir.getWarmupProgress(now);

            // Render ASCII progress bar
            int bar_width = 30;
            int filled = (int)(progress * bar_width);
            Serial.printf("[WARMING UP] [%.*s%.*s] %2lu s remaining (Raw Pin: %s)\r",
                          filled, "==============================",
                          bar_width - filled, "                              ",
                          (unsigned long)remaining_s,
                          pir.getRawLevel() ? "HIGH (Ignored)" : "LOW");
        }
    } else {
        // Detect transition from warming-up to stabilized
        if (prev_warmup_state) {
            prev_warmup_state = false;
            Serial.println("\n\n>>> [SYSTEM ARMED] HC-SR501 PIR thermal stabilization complete! Monitoring motion...");
            Serial.println("+-------------------+---------------------+------------------+------------------+");
            Serial.println("| Timestamp (ms)    | Event               | Trigger Count    | Raw Pin Level    |");
            Serial.println("+-------------------+---------------------+------------------+------------------+");
        }

        if (new_trigger) {
            Serial.printf("| %-17lu | MOTION DETECTED     | %-16lu | HIGH             |\n",
                          (unsigned long)now, (unsigned long)pir.getTriggerCount());
        }
    }

    if (Serial.available()) {
        char ch = Serial.read();
        while (Serial.available() && (Serial.peek() == '\r' || Serial.peek() == '\n')) {
            Serial.read();
        }

        if (ch == 'f' || ch == 'F') {
            pir.forceWarmupComplete();
            Serial.println("\n>>> [COMMAND] Forced warm-up bypass! Sensor armed immediately.");
        } else if (ch == 'r' || ch == 'R') {
            pir.resetStats();
            Serial.println("\n>>> [COMMAND] Trigger counter reset to 0.");
        } else if (ch == 'h' || ch == 'H') {
            Serial.println("\nCommands: [f] Force bypass warm-up | [r] Reset trigger counter | [h] Help");
        }
    }
}
