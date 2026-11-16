/**
 * @file sensor_suite.cpp
 * @brief SmartVision Phase 2: Unified Interactive Sensor Verification Suite.
 *
 * Provides a comprehensive, serial-driven diagnostic harness for:
 * 1. HC-SR04 Ultrasonic Distance Sensor (via 1k/2k safe voltage divider on GPIO 5).
 * 2. HC-SR501 PIR Motion Sensor (30-60s boot stabilization window on GPIO 6).
 * 3. Active 5V Buzzer (GPIO 7 via 2N2222 NPN transistor driver).
 * 4. Status LED (GPIO 10) hardware visualization.
 * 5. Formatted JSON telemetry streaming matching docs/protocol.md at 10 Hz.
 * 6. Integrated proximity collision avoidance & security alert routines.
 *
 * Built according to Ponytail principles: zero external library bloat,
 * non-blocking state machines, bounded timeouts, and strict silicon protection.
 */

#include <Arduino.h>
#include "hardware_config.h"
#include "buzzer_driver.h"
#include "hcsr04_driver.h"
#include "hcsr501_driver.h"

// Hardware driver instances
BuzzerDriver buzzer(PIN_BUZZER);
HCSR04Driver sonar(PIN_ULTRASONIC_TRIG, PIN_ULTRASONIC_ECHO);
HCSR501Driver pir(PIN_PIR_INPUT, PIR_WARMUP_DEFAULT_MS);

// Suite operational states
enum SuiteMode : uint8_t {
    MODE_MENU = 0,
    MODE_STREAM_TABULAR,
    MODE_STREAM_JSON,
    MODE_PROXIMITY_DEMO,
    MODE_SECURITY_DEMO
};

SuiteMode g_mode = MODE_MENU;
uint32_t g_seq_num = 0;
uint32_t g_last_sample_ms = 0;
uint32_t g_last_prox_alert_ms = 0;
uint32_t g_last_led_blink_ms = 0;
bool g_led_state = false;

// Forward declarations
void printBanner();
void printMenu();
void handleSerialInput(String cmd);
void emitJsonTelemetry();
void emitTabularRow();
void runUltrasonicBenchmark();
void runPirDiagnostic();
void runBuzzerDemo();

void printBanner() {
    Serial.println("\n================================================================================");
    Serial.println("         SMARTVISION PHASE 2: UNIFIED SENSOR VERIFICATION SUITE                 ");
    Serial.println("================================================================================");
    Serial.printf("MCU:            ESP32-S3 (Chip Rev: %d, Cores: %d)\n", ESP.getChipRevision(), ESP.getChipCores());
    Serial.printf("CPU Freq:       %lu MHz | Flash: %lu MB | Free Heap: %lu bytes\n",
                  (unsigned long)ESP.getCpuFreqMHz(), 
                  (unsigned long)(ESP.getFlashChipSize() / (1024 * 1024)), 
                  (unsigned long)ESP.getFreeHeap());
    Serial.printf("Internal Temp:  %.1f °C\n", temperatureRead());
    Serial.println("--------------------------------------------------------------------------------");
    Serial.printf("HC-SR04 Sonar:  Trig = GPIO %d | Echo = GPIO %d (1k/2k Divider -> 3.33V)\n",
                  PIN_ULTRASONIC_TRIG, PIN_ULTRASONIC_ECHO);
    Serial.printf("HC-SR501 PIR:   Out = GPIO %d (Native 3.3V, %lu ms warm-up window)\n",
                  PIN_PIR_INPUT, (unsigned long)PIR_WARMUP_DEFAULT_MS);
    Serial.printf("Active Buzzer:  GPIO %d (Low-side 2N2222 NPN driver + 1N4148 flyback clamp)\n", PIN_BUZZER);
    Serial.printf("Status LED:     GPIO %d (Active HIGH via 330R)\n", PIN_STATUS_LED);
    Serial.printf("I2C Bus:        SDA = GPIO %d | SCL = GPIO %d (PCA9685 at 0x%02X)\n",
                  PIN_I2C_SDA, PIN_I2C_SCL, PCA9685_I2C_ADDR);
    Serial.println("================================================================================\n");
}

void printMenu() {
    Serial.println("------------------------- SENSOR DIAGNOSTIC MENU ---------------------------");
    Serial.println("  [1] Stream Real-time Tabular Sensor Data (10 Hz live monitor)");
    Serial.println("  [2] Stream Formatted JSON Telemetry (10 Hz matching docs/protocol.md)");
    Serial.println("  [3] Run HC-SR04 Ultrasonic Accuracy & Noise Benchmark");
    Serial.println("  [4] Run HC-SR501 PIR Motion & Warm-up Verification");
    Serial.println("  [5] Run Active Buzzer Pattern Demo (Beep, Chirp, Alarm, Pulse, Mute)");
    Serial.println("  [6] Start Proximity Collision Avoidance Demo (Auto-alarm < 20cm)");
    Serial.println("  [7] Start Armed Security Alarm Demo (Auto-chirp on PIR trigger)");
    Serial.println("  --- Quick Action Keys ---");
    Serial.println("  [b] Single Beep (150ms)        | [c] Alert Chirp");
    Serial.println("  [a] Toggle Continuous Alarm     | [m] Mute Buzzer");
    Serial.println("  [u] Single Ultrasonic Ping     | [p] Query PIR State");
    Serial.println("  [f] Force Bypass PIR Warm-up   | [j] Single JSON Telemetry Snapshot");
    Serial.println("  [s] Stop Streaming / Return to Menu");
    Serial.println("  [h] Redisplay This Menu");
    Serial.println("----------------------------------------------------------------------------");
    Serial.print("Select command > ");
}

void emitTabularHeader() {
    Serial.println("\n+------------+---------------+--------------+------------------+------------------+-----------------+");
    Serial.println("| Time (ms)  | Distance (cm) | Sonar Status | PIR Motion State | Buzzer Pattern   | Status LED      |");
    Serial.println("+------------+---------------+--------------+------------------+------------------+-----------------+");
}

void emitTabularRow() {
    uint32_t now = millis();
    float dist = sonar.getDistanceCm();
    const char* s_status = sonar.getStatusString();
    
    char pir_str[32];
    if (pir.isWarmingUp()) {
        uint32_t rem_s = (pir.getWarmupRemainingMs(now) + 999) / 1000;
        snprintf(pir_str, sizeof(pir_str), "WARMING UP (%lus)", (unsigned long)rem_s);
    } else {
        snprintf(pir_str, sizeof(pir_str), "%s (Cnt:%lu)", 
                 pir.isMotionDetected() ? "DETECTED" : "CLEAR", (unsigned long)pir.getTriggerCount());
    }

    Serial.printf("| %-10lu | %-13.1f | %-12s | %-16s | %-16s | %-15s |\n",
                  (unsigned long)now, dist, s_status, pir_str, 
                  buzzer.getPatternName(), g_led_state ? "ON (HIGH)" : "OFF (LOW)");
}

void emitJsonTelemetry() {
    uint32_t now = millis();
    g_seq_num++;

    float dist = sonar.getFilteredDistanceCm();
    bool valid = sonar.isValid();
    const char* status = sonar.getStatusString();

    bool motion = pir.isMotionDetected();
    uint32_t trigger_count = pir.getTriggerCount();
    uint32_t last_trigger = pir.getLastTriggerMs();

    bool buzzer_active = buzzer.isActive();
    const char* pattern = buzzer.getPatternName();

    float temp_c = temperatureRead();
    uint32_t free_heap = ESP.getFreeHeap();
    uint32_t free_psram = ESP.getFreePsram();

    // Print strictly formatted JSON conforming to docs/protocol.md section 3.4
    Serial.printf("{\"type\":\"telem.sensors\",\"timestamp\":%lu,\"sender\":\"esp32\",\"seq\":%lu,\"corr_id\":null,\"payload\":{"
                  "\"sonar\":{\"distance_cm\":%.1f,\"valid\":%s,\"status\":\"%s\"},"
                  "\"pir\":{\"motion_detected\":%s,\"trigger_count\":%lu,\"last_trigger_ms\":%lu},"
                  "\"servos\":{\"pan_angle\":90.0,\"tilt_angle\":90.0,\"pan_target\":90.0,\"tilt_target\":90.0,\"is_moving\":false},"
                  "\"buzzer\":{\"active\":%s,\"pattern\":\"%s\"},"
                  "\"system\":{\"uptime_ms\":%lu,\"rssi_dbm\":-55,\"free_heap_bytes\":%lu,\"psram_free_bytes\":%lu,\"cpu_temp_c\":%.1f}"
                  "}}\n",
                  (unsigned long)now, (unsigned long)g_seq_num,
                  dist, valid ? "true" : "false", status,
                  motion ? "true" : "false", (unsigned long)trigger_count, (unsigned long)last_trigger,
                  buzzer_active ? "true" : "false", pattern,
                  (unsigned long)now, (unsigned long)free_heap, (unsigned long)free_psram, temp_c);
}

void runUltrasonicBenchmark() {
    Serial.println("\n>>> [BENCHMARK] HC-SR04 ULTRASONIC RANGE & JITTER TEST (10 SAMPLES) <<<");
    Serial.println("Acquiring 10 samples at 100ms intervals...");

    float samples[10];
    uint8_t valid_count = 0;
    float sum = 0.0f;
    float min_val = 9999.0f;
    float max_val = -1.0f;

    for (int i = 0; i < 10; i++) {
        delay(100);
        float d = sonar.measureDistanceCm(DEFAULT_AMBIENT_TEMP_C);
        samples[i] = d;
        Serial.printf("  Sample #%2d: %6.1f cm | Status: %s | Echo: %5lu us\n",
                      i + 1, d, sonar.getStatusString(), (unsigned long)sonar.getLastEchoUs());

        if (sonar.isValid()) {
            valid_count++;
            sum += d;
            if (d < min_val) min_val = d;
            if (d > max_val) max_val = d;
        }
    }

    Serial.println("--------------------------------------------------------------------------------");
    if (valid_count > 0) {
        float avg = sum / (float)valid_count;
        float variance_sum = 0.0f;
        for (int i = 0; i < 10; i++) {
            if (samples[i] > 0.0f && samples[i] <= 400.0f) {
                float diff = samples[i] - avg;
                variance_sum += diff * diff;
            }
        }
        float std_dev = sqrt(variance_sum / (float)valid_count);

        Serial.printf("Benchmark Results: Valid: %d/10 | Min: %.1f cm | Max: %.1f cm | Avg: %.1f cm | StdDev: %.2f cm\n",
                      valid_count, min_val, max_val, avg, std_dev);
    } else {
        Serial.println("Benchmark Results: No valid echoes received. Check 5V power, ground, and target alignment.");
    }
    Serial.println("================================================================================\n");
    printMenu();
}

void runPirDiagnostic() {
    Serial.println("\n>>> [DIAGNOSTIC] HC-SR501 PIR SENSOR STATUS <<<");
    Serial.printf("Raw Pin (GPIO %d) Level: %s\n", PIN_PIR_INPUT, pir.getRawLevel() ? "HIGH" : "LOW");
    Serial.printf("Stabilization State:     %s\n", pir.isWarmingUp() ? "WARMING UP (Suppressed)" : "STABILIZED & ARMED");
    if (pir.isWarmingUp()) {
        Serial.printf("Remaining Warm-up Time:  %lu seconds\n", 
                      (unsigned long)((pir.getWarmupRemainingMs() + 999) / 1000));
        Serial.printf("Warm-up Progress:        %.1f %%\n", pir.getWarmupProgress() * 100.0f);
        Serial.println("Note: Type 'f' to force bypass the warm-up window for rapid testing.");
    } else {
        Serial.printf("Confirmed Motion:        %s\n", pir.isMotionDetected() ? "YES (ACTIVE)" : "NO (CLEAR)");
        Serial.printf("Total Triggers Logged:   %lu\n", (unsigned long)pir.getTriggerCount());
        Serial.printf("Last Trigger Uptime:     %lu ms\n", (unsigned long)pir.getLastTriggerMs());
    }
    Serial.println("================================================================================\n");
    printMenu();
}

void runBuzzerDemo() {
    Serial.println("\n>>> [DEMO] ACTIVE BUZZER ALERT SEQUENCE DEMO <<<");
    Serial.println("1. Emitting standard notification beep (150ms)...");
    buzzer.beep(150);
    for (int i = 0; i < 30; i++) { buzzer.update(); delay(10); }

    Serial.println("2. Emitting double alert chirp (70ms ON, 50ms OFF, 70ms ON)...");
    buzzer.chirp();
    for (int i = 0; i < 40; i++) { buzzer.update(); delay(10); }

    Serial.println("3. Emitting 3 pulsed warning beeps (100ms ON / 100ms OFF)...");
    buzzer.pulse(3, 100, 100);
    for (int i = 0; i < 70; i++) { buzzer.update(); delay(10); }

    Serial.println("4. Emitting emergency alarm burst (3 cycles)...");
    buzzer.alarm(true);
    for (int i = 0; i < 90; i++) { buzzer.update(); delay(10); }

    Serial.println("5. Muting buzzer...");
    buzzer.mute();
    buzzer.update();

    Serial.println("Buzzer pattern sequence completed cleanly!\n");
    printMenu();
}

void handleSerialInput(String cmd) {
    cmd.trim();
    if (cmd.length() == 0) return;

    // Check for JSON commands (e.g., cmd.buzzer)
    if (cmd.startsWith("{") && cmd.endsWith("}")) {
        if (cmd.indexOf("\"cmd.buzzer\"") > 0) {
            if (cmd.indexOf("\"beep\"") > 0) {
                uint16_t dur = 150;
                int dur_idx = cmd.indexOf("\"duration_ms\":");
                if (dur_idx > 0) {
                    dur = (uint16_t)cmd.substring(dur_idx + 14).toInt();
                    if (dur == 0) dur = 150;
                }
                buzzer.beep(dur);
                Serial.printf("{\"status\":\"ok\",\"action\":\"beep\",\"duration_ms\":%u}\n", dur);
            } else if (cmd.indexOf("\"chirp\"") > 0) {
                buzzer.chirp();
                Serial.println("{\"status\":\"ok\",\"action\":\"chirp\"}");
            } else if (cmd.indexOf("\"alarm\"") > 0) {
                buzzer.alarm(true);
                Serial.println("{\"status\":\"ok\",\"action\":\"alarm\"}");
            } else if (cmd.indexOf("\"pulse\"") > 0) {
                uint16_t count = 3;
                uint16_t on_ms = 100;
                uint16_t off_ms = 100;
                int cnt_idx = cmd.indexOf("\"count\":");
                if (cnt_idx > 0) count = (uint16_t)cmd.substring(cnt_idx + 8).toInt();
                int on_idx = cmd.indexOf("\"duration_ms\":");
                if (on_idx > 0) on_ms = (uint16_t)cmd.substring(on_idx + 14).toInt();
                int off_idx = cmd.indexOf("\"interval_ms\":");
                if (off_idx > 0) off_ms = (uint16_t)cmd.substring(off_idx + 14).toInt();
                buzzer.pulse(count, on_ms, off_ms);
                Serial.printf("{\"status\":\"ok\",\"action\":\"pulse\",\"count\":%u}\n", count);
            } else if (cmd.indexOf("\"mute\"") > 0 || cmd.indexOf("\"off\"") > 0) {
                buzzer.mute();
                Serial.println("{\"status\":\"ok\",\"action\":\"mute\"}");
            }
            return;
        }
    }

    char c = cmd.charAt(0);
    switch (c) {
        case '1':
            g_mode = MODE_STREAM_TABULAR;
            emitTabularHeader();
            break;
        case '2':
            g_mode = MODE_STREAM_JSON;
            Serial.println("\n>>> [STREAMING] 10 Hz JSON TELEMETRY STREAM (Press 's' to stop) <<<");
            break;
        case '3':
            g_mode = MODE_MENU;
            runUltrasonicBenchmark();
            break;
        case '4':
            g_mode = MODE_MENU;
            runPirDiagnostic();
            break;
        case '5':
            g_mode = MODE_MENU;
            runBuzzerDemo();
            break;
        case '6':
            g_mode = MODE_PROXIMITY_DEMO;
            Serial.println("\n>>> [DEMO] PROXIMITY COLLISION AVOIDANCE ACTIVE (Press 's' to stop) <<<");
            Serial.println("Move hand close to HC-SR04: < 20cm triggers alarm; 20-40cm triggers warning.");
            break;
        case '7':
            g_mode = MODE_SECURITY_DEMO;
            Serial.println("\n>>> [DEMO] ARMED SECURITY ALARM ACTIVE (Press 's' to stop) <<<");
            Serial.println("Trigger PIR motion sensor to generate audible alert chirps & flash LED.");
            break;
        case 'b':
        case 'B':
            buzzer.beep(150);
            Serial.println(">>> [BEEP] 150ms");
            break;
        case 'c':
        case 'C':
            buzzer.chirp();
            Serial.println(">>> [CHIRP] Alert chirp");
            break;
        case 'a':
        case 'A':
            if (buzzer.getPattern() == BUZZER_PATTERN_ALARM) {
                buzzer.mute();
                Serial.println(">>> [ALARM] Stopped");
            } else {
                buzzer.alarm(true);
                Serial.println(">>> [ALARM] Started continuous alarm");
            }
            break;
        case 'm':
        case 'M':
            buzzer.mute();
            Serial.println(">>> [MUTE] Buzzer silenced");
            break;
        case 'u':
        case 'U': {
            float d = sonar.measureDistanceCm(DEFAULT_AMBIENT_TEMP_C);
            Serial.printf(">>> [PING] Distance: %.1f cm (Status: %s, Echo: %lu us)\n",
                          d, sonar.getStatusString(), (unsigned long)sonar.getLastEchoUs());
            break;
        }
        case 'p':
        case 'P':
            runPirDiagnostic();
            break;
        case 'f':
        case 'F':
            pir.forceWarmupComplete();
            Serial.println(">>> [PIR] Forced warm-up bypass! Sensor armed immediately.");
            break;
        case 'j':
        case 'J':
            emitJsonTelemetry();
            break;
        case 's':
        case 'S':
            g_mode = MODE_MENU;
            buzzer.mute();
            digitalWrite(PIN_STATUS_LED, LOW);
            Serial.println("\n>>> [STOP] Returned to Main Menu.");
            printMenu();
            break;
        case 'h':
        case 'H':
            g_mode = MODE_MENU;
            printMenu();
            break;
        default:
            Serial.println("Unknown command. Type 'h' for menu.");
            break;
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    // Setup Status LED
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    // Initialize all sensor drivers
    buzzer.begin();
    sonar.begin();
    pir.begin();

    // Print welcome banner & interactive menu
    printBanner();
    printMenu();

    // Initial alert chirp confirming successful boot
    buzzer.beep(100);
}

// Non-blocking serial command processor
static char s_serial_buf[128];
static uint8_t s_serial_buf_len = 0;

void processSerial() {
    while (Serial.available()) {
        char c = (char)Serial.read();
        if (c == '\r' || c == '\n') {
            if (s_serial_buf_len > 0) {
                s_serial_buf[s_serial_buf_len] = '\0';
                handleSerialInput(String(s_serial_buf));
                s_serial_buf_len = 0;
            }
        } else if (c == '{' || s_serial_buf_len > 0) {
            // Accumulate JSON envelope or multi-char command
            if (s_serial_buf_len < sizeof(s_serial_buf) - 1) {
                s_serial_buf[s_serial_buf_len++] = c;
                if (c == '}') {
                    s_serial_buf[s_serial_buf_len] = '\0';
                    handleSerialInput(String(s_serial_buf));
                    s_serial_buf_len = 0;
                }
            }
        } else {
            // Immediate single-character menu / diagnostic command
            char single_cmd[2] = { c, '\0' };
            handleSerialInput(String(single_cmd));
        }
    }
}

void loop() {
    uint32_t now = millis();

    // Non-blocking update of state machines
    buzzer.update(now);
    bool new_pir_trigger = pir.update(now);

    // Sample ultrasonic distance at 10 Hz (every 100 ms) using ambient air temp
    bool new_sonar_sample = sonar.update(now, DEFAULT_AMBIENT_TEMP_C);

    // Mode handling
    if (g_mode == MODE_STREAM_TABULAR && new_sonar_sample) {
        emitTabularRow();
    } else if (g_mode == MODE_STREAM_JSON && new_sonar_sample) {
        emitJsonTelemetry();
    } else if (g_mode == MODE_PROXIMITY_DEMO && new_sonar_sample) {
        float dist = sonar.getDistanceCm();
        if (sonar.isObstruction()) {
            // Critical proximity: sound alarm & blink LED (<20cm, defensively includes <2cm)
            if (buzzer.getPattern() != BUZZER_PATTERN_ALARM) {
                buzzer.alarm(true);
                Serial.printf(">>> [CRITICAL] Proximity Obstruction! Distance: %.1f cm (< 20.0 cm)\n",
                              sonar.isValid() ? dist : sonar.getRawDistanceCm());
            }
            // Rapid LED blink
            if (now - g_last_led_blink_ms >= 100) {
                g_last_led_blink_ms = now;
                g_led_state = !g_led_state;
                digitalWrite(PIN_STATUS_LED, g_led_state ? HIGH : LOW);
            }
        } else if (sonar.isWarning()) {
            // Warning zone: emit warning chirp periodically (20-40cm)
            if (buzzer.getPattern() == BUZZER_PATTERN_ALARM) {
                buzzer.mute();
            }
            if (now - g_last_prox_alert_ms >= 1000) {
                g_last_prox_alert_ms = now;
                buzzer.chirp();
                Serial.printf(">>> [WARNING] Object Approaching: %.1f cm (20.0 - 40.0 cm)\n", dist);
            }
            digitalWrite(PIN_STATUS_LED, HIGH);
        } else {
            // Clear zone or out-of-range (>40cm or timeout)
            if (buzzer.getPattern() != BUZZER_PATTERN_OFF) {
                buzzer.mute();
            }
            digitalWrite(PIN_STATUS_LED, LOW);
        }
    } else if (g_mode == MODE_SECURITY_DEMO) {
        if (new_pir_trigger) {
            Serial.printf(">>> [ALARM] Motion Detected! Trigger #%lu at %lu ms\n",
                          (unsigned long)pir.getTriggerCount(), (unsigned long)now);
            buzzer.chirp();
            digitalWrite(PIN_STATUS_LED, HIGH);
        } else if (!pir.isMotionDetected() && buzzer.getPattern() == BUZZER_PATTERN_OFF) {
            digitalWrite(PIN_STATUS_LED, LOW);
        }
    }

    // Process serial input without blocking
    processSerial();
}
