/**
 * @file 04_buzzer_test.cpp
 * @brief Standalone Test 04: Active Buzzer Driver Verification (GPIO 7 via 2N2222 NPN).
 *
 * Verifies low-side transistor switching, inductive flyback clamping,
 * and non-blocking pattern generation (Beep, Chirp, Alarm, Pulse, Mute).
 *
 * Built according to Ponytail principles: zero external library bloat.
 */

#include <Arduino.h>
#include "hardware_config.h"
#include "buzzer_driver.h"

BuzzerDriver buzzer(PIN_BUZZER);

void printMenu() {
    Serial.println("\n--------------------------------------------------------------------------------");
    Serial.println("         TEST 04: ACTIVE BUZZER DRIVER VERIFICATION (GPIO 7)                    ");
    Serial.println("--------------------------------------------------------------------------------");
    Serial.println("  [1] Emit Short Alert Chirp (70ms ON / 50ms OFF / 70ms ON)");
    Serial.println("  [2] Emit Standard Notification Beep (150ms)");
    Serial.println("  [3] Start Emergency Alarm Pattern (150ms ON / 150ms OFF continuous)");
    Serial.println("  [4] Emit 3 Warning Pulses (100ms ON / 100ms OFF)");
    Serial.println("  [5] Emit Long Alert Tone (500ms)");
    Serial.println("  [0] Mute / Silence Immediately");
    Serial.println("  [h] Redisplay Menu");
    Serial.println("--------------------------------------------------------------------------------");
    Serial.print("Select command > ");
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("\n================================================================================");
    Serial.println("         SMARTVISION PHASE 2: ACTIVE BUZZER INDEPENDENT TEST                    ");
    Serial.println("================================================================================");
    Serial.printf("MCU:            ESP32-S3 (Chip Rev: %d)\n", ESP.getChipRevision());
    Serial.printf("Buzzer GPIO:    Pin %d (Driven via 2N2222 NPN low-side switch)\n", PIN_BUZZER);
    Serial.printf("Base Resistor:  1.0 kOhm (IB ~ 2.6 mA, saturation forced beta ~ 15)\n");
    Serial.printf("Flyback Diode:  1N4148 antiparallel across buzzer coil\n");
    Serial.println("================================================================================");

    buzzer.begin();
    printMenu();
}

void loop() {
    buzzer.update();

    if (Serial.available()) {
        char ch = Serial.read();
        while (Serial.available() && (Serial.peek() == '\r' || Serial.peek() == '\n')) {
            Serial.read();
        }

        switch (ch) {
            case '1':
                Serial.println("\n>>> [COMMAND] Emitting Alert Chirp...");
                buzzer.chirp();
                break;
            case '2':
                Serial.println("\n>>> [COMMAND] Emitting 150ms Beep...");
                buzzer.beep(150);
                break;
            case '3':
                Serial.println("\n>>> [COMMAND] Starting Continuous Emergency Alarm (Press '0' to stop)...");
                buzzer.alarm(true);
                break;
            case '4':
                Serial.println("\n>>> [COMMAND] Emitting 3 Pulsed Beeps...");
                buzzer.pulse(3, 100, 100);
                break;
            case '5':
                Serial.println("\n>>> [COMMAND] Emitting 500ms Long Tone...");
                buzzer.beep(500);
                break;
            case '0':
            case 'm':
                Serial.println("\n>>> [COMMAND] Muting Buzzer...");
                buzzer.mute();
                break;
            case 'h':
            case 'H':
                printMenu();
                break;
            default:
                break;
        }
    }
}
