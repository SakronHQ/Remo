/**
 * @file 05_ultrasonic_test.cpp
 * @brief Standalone Test 05: HC-SR04 Ultrasonic Distance Sensor Verification.
 *
 * Verifies non-blocking trigger/echo timing, safe 1k/2k voltage divider echo shifting,
 * conversion to cm, out-of-range rejection, and proximity alert thresholds.
 *
 * Built according to Ponytail principles: zero external dependencies, bounded timeouts.
 */

#include <Arduino.h>
#include "hardware_config.h"
#include "hcsr04_driver.h"

HCSR04Driver sonar(PIN_ULTRASONIC_TRIG, PIN_ULTRASONIC_ECHO);

uint32_t last_print_ms = 0;
bool stream_enabled = true;
uint32_t sample_counter = 0;

void printHeader() {
    Serial.println("\n+------------+------------+---------------+--------------+----------------------+");
    Serial.println("| Sample #   | Echo (us)  | Distance (cm) | Status       | Proximity Zone       |");
    Serial.println("+------------+------------+---------------+--------------+----------------------+");
}

void printRow(uint32_t count, uint32_t echo_us, float dist_cm, const char* status) {
    const char* zone = "NORMAL";
    if (sonar.isObstruction()) {
        zone = "OBSTRUCTION (<20cm)";
    } else if (sonar.isWarning()) {
        zone = "WARNING (20-40cm)";
    } else if (strcmp(status, "timeout") == 0) {
        zone = "TIMEOUT (>400cm)";
    } else if (strcmp(status, "out_of_range") == 0) {
        zone = "OUT OF RANGE";
    }

    Serial.printf("| %-10lu | %-10lu | %-13.1f | %-12s | %-20s |\n",
                  (unsigned long)count, (unsigned long)echo_us, dist_cm, status, zone);
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("\n================================================================================");
    Serial.println("         SMARTVISION PHASE 2: HC-SR04 ULTRASONIC SENSOR TEST                    ");
    Serial.println("================================================================================");
    Serial.printf("MCU:            ESP32-S3 (Chip Rev: %d)\n", ESP.getChipRevision());
    Serial.printf("Trigger Pin:    GPIO %d (3.3V push-pull, 10 us pulse)\n", PIN_ULTRASONIC_TRIG);
    Serial.printf("Echo Pin:       GPIO %d (5V stepped down to 3.33V via 1k/2k voltage divider)\n", PIN_ULTRASONIC_ECHO);
    Serial.printf("Sampling Rate:  10 Hz (every 100 ms)\n");
    Serial.printf("Range Limits:   %.1f cm to %.1f cm (Timeout: %lu us)\n", 
                  ULTRASONIC_MIN_DISTANCE_CM, ULTRASONIC_MAX_DISTANCE_CM, (unsigned long)ULTRASONIC_TIMEOUT_US);
    Serial.printf("Safety Zones:   Obstruction < %.1f cm | Warning < %.1f cm\n",
                  PROXIMITY_OBSTRUCTION_CM, PROXIMITY_WARNING_CM);
    Serial.println("================================================================================");
    Serial.println("Commands: [s] Pause/Resume Stream | [p] Single Ping | [h] Help");

    sonar.begin();
    printHeader();
}

void loop() {
    uint32_t now = millis();

    // Sample distance at 10 Hz
    if (sonar.update(now)) {
        sample_counter++;
        if (stream_enabled) {
            printRow(sample_counter, sonar.getLastEchoUs(), sonar.getDistanceCm(), sonar.getStatusString());
        }
    }

    if (Serial.available()) {
        char ch = Serial.read();
        while (Serial.available() && (Serial.peek() == '\r' || Serial.peek() == '\n')) {
            Serial.read();
        }

        if (ch == 's' || ch == 'S') {
            stream_enabled = !stream_enabled;
            Serial.printf("\n>>> Stream %s\n", stream_enabled ? "RESUMED" : "PAUSED");
            if (stream_enabled) printHeader();
        } else if (ch == 'p' || ch == 'P') {
            float d = sonar.measureDistanceCm();
            printHeader();
            printRow(++sample_counter, sonar.getLastEchoUs(), d, sonar.getStatusString());
        } else if (ch == 'h' || ch == 'H') {
            Serial.println("\nCommands: [s] Toggle stream | [p] Single ping | [h] Help");
        }
    }
}
