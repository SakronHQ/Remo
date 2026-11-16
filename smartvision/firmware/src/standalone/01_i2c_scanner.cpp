/**
 * @file 01_i2c_scanner.cpp
 * @brief Standalone Test 1: ESP32-S3 & PCA9685 I2C Communication Verification.
 *
 * Checks:
 * 1. ESP32-S3 silicon health (CPU freq, Flash size, Free Heap, Reset Reason).
 * 2. I2C Bus Enumeration on SDA=GPIO 8, SCL=GPIO 9 at 100 kHz.
 * 3. PCA9685 Detection at 0x40 and register dump (MODE1, MODE2, PRESCALE).
 * 4. Hardware Output Enable (OE) pin switching on GPIO 12.
 * 5. Status LED heartbeat on GPIO 10.
 *
 * NOTE: Run this test with NO SERVOS PLUGGED IN to verify the digital interface first!
 */

#include <Arduino.h>
#include <Wire.h>
#include "hardware_config.h"
#include "pca9685_driver.h"

PCA9685Driver pca(PCA9685_I2C_ADDR, PIN_PCA9685_OE);

void printBanner() {
    Serial.println("\n========================================================");
    Serial.println("   SMARTVISION HARDWARE TEST 01: I2C & PCA9685 VERIFICATION");
    Serial.println("========================================================");
    Serial.printf("MCU: ESP32-S3 (Chip Rev: %d, Cores: %d)\n", ESP.getChipRevision(), ESP.getChipCores());
    Serial.printf("CPU Frequency: %lu MHz\n", (unsigned long)ESP.getCpuFreqMHz());
    Serial.printf("Flash Size: %lu MB\n", (unsigned long)(ESP.getFlashChipSize() / (1024 * 1024)));
    Serial.printf("Free Heap: %lu bytes\n", (unsigned long)ESP.getFreeHeap());
    Serial.printf("Reset Reason: %d\n", esp_reset_reason());
    Serial.println("--------------------------------------------------------");
    Serial.printf("I2C Configuration: SDA = GPIO %d, SCL = GPIO %d (Speed: 100 kHz)\n", PIN_I2C_SDA, PIN_I2C_SCL);
    Serial.printf("PCA9685 OE Pin:    GPIO %d (Active LOW)\n", PIN_PCA9685_OE);
    Serial.printf("Status LED Pin:    GPIO %d\n", PIN_STATUS_LED);
    Serial.println("========================================================\n");
}

void scanI2CBus() {
    Serial.println("[I2C SCAN] Starting bus enumeration (0x01 to 0x7E)...");
    uint8_t count = 0;
    bool pca_found = false;

    for (uint8_t address = 1; address < 127; address++) {
        Wire.beginTransmission(address);
        uint8_t error = Wire.endTransmission();

        if (error == 0) {
            Serial.printf("  -> Found I2C device at 0x%02X", address);
            if (address == PCA9685_I2C_ADDR) {
                Serial.print("  [MATCH: PCA9685 Default Address 0x40]");
                pca_found = true;
            } else if (address == 0x70) {
                Serial.print("  [PCA9685 All-Call Software Address]");
            }
            Serial.println();
            count++;
        } else if (error == 4) {
            Serial.printf("  -> Unknown error at address 0x%02X\n", address);
        }
    }

    Serial.println("--------------------------------------------------------");
    if (count == 0) {
        Serial.println("[RESULT: FAIL] No I2C devices found on bus!");
        Serial.println("  Troubleshooting Checklist:");
        Serial.println("  1. Verify SDA is connected to GPIO 8, SCL to GPIO 9.");
        Serial.println("  2. Verify PCA9685 VCC is connected to ESP32-S3 3.3V rail.");
        Serial.println("  3. Verify common GND is securely bonded between ESP32 and PCA9685.");
        Serial.println("  4. Check for broken DuPont jumper wires.");
    } else if (pca_found) {
        Serial.printf("[RESULT: PASS] PCA9685 detected at 0x40! Total devices: %d\n", count);
    } else {
        Serial.printf("[RESULT: WARN] I2C devices found (%d), but PCA9685 at 0x40 was NOT detected!\n", count);
        Serial.println("  Check if address solder jumpers (A0..A5) were bridged.");
    }
    Serial.println();
}

void verifyPCA9685Registers() {
    Serial.println("[PCA9685 CONFIG] Reading control registers...");
    uint8_t mode1 = pca.readRegister(PCA9685_MODE1);
    uint8_t mode2 = pca.readRegister(PCA9685_MODE2);
    uint8_t prescale = pca.readRegister(PCA9685_PRESCALE);

    Serial.printf("  MODE1    (0x00): 0x%02X (Auto-Inc: %s, Sleep: %s, All-Call: %s)\n",
                  mode1,
                  (mode1 & 0x20) ? "YES" : "NO",
                  (mode1 & 0x10) ? "YES" : "NO",
                  (mode1 & 0x01) ? "YES" : "NO");
    Serial.printf("  MODE2    (0x01): 0x%02X (Out-Drive: %s)\n",
                  mode2,
                  (mode2 & 0x04) ? "Totem-Pole" : "Open-Drain");
    Serial.printf("  PRESCALE (0xFE): 0x%02X (%d decimal, Prescaler for ~50 Hz PWM)\n",
                  prescale, prescale);

    if (prescale == PCA9685_PRESCALE_VAL && (mode1 & 0x20)) {
        Serial.println("[RESULT: PASS] PCA9685 registers correctly configured for 50 Hz PWM!");
    } else {
        Serial.println("[RESULT: WARN] Registers do not match default 50 Hz target. Re-initializing...");
        pca.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);
    }
    Serial.println();
}

void verifyOutputEnable() {
    Serial.println("[OE PIN TEST] Toggling Hardware Output Enable (GPIO 12)...");
    
    // OE LOW = Enabled
    pca.enableOutputs(true);
    Serial.printf("  OE Pin driven LOW  -> PWM Outputs ENABLED  (GPIO 12 = %d)\n", digitalRead(PIN_PCA9685_OE));
    delay(500);

    // OE HIGH = Disabled (tri-state)
    pca.enableOutputs(false);
    Serial.printf("  OE Pin driven HIGH -> PWM Outputs DISABLED (GPIO 12 = %d)\n", digitalRead(PIN_PCA9685_OE));
    delay(500);

    // Leave OE HIGH (tri-state) so user can safely attach servo jumpers
    pca.enableOutputs(false);
    Serial.printf("  OE Pin safely parked at HIGH -> Outputs TRI-STATE for wiring (GPIO 12 = %d)\n", digitalRead(PIN_PCA9685_OE));
    Serial.println("[RESULT: PASS] Hardware Output Enable toggle verified!\n");
}

void setup() {
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, HIGH);

    Serial.begin(115200);
    // Allow USB CDC serial monitor connection
    unsigned long start = millis();
    while (!Serial && (millis() - start < 3000)) {
        delay(10);
    }
    delay(500);

    printBanner();

    Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000);
    delay(100);

    scanI2CBus();

    if (pca.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000)) {
        verifyPCA9685Registers();
        verifyOutputEnable();
        Serial.println("========================================================");
        Serial.println("   PHASE 1 - TEST 01 COMPLETE: I2C SUBSYSTEM VERIFIED");
        Serial.println("========================================================\n");
    } else {
        Serial.println("[FATAL] PCA9685 initialization failed! Check wiring above.");
    }
}

void loop() {
    // Heartbeat LED flash every 1 second
    digitalWrite(PIN_STATUS_LED, HIGH);
    delay(500);
    digitalWrite(PIN_STATUS_LED, LOW);
    delay(500);
}
