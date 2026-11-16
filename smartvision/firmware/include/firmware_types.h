/**
 * @file firmware_types.h
 * @brief Common Data Structures, Enums, and Telemetry Models for SmartVision Firmware.
 *
 * Provides FreeRTOS thread-safe inter-task communication payloads:
 * - Motion commands and snapshots
 * - Sensor acquisition snapshots
 * - System health and communication metrics
 */

#pragma once

#include <Arduino.h>

// ============================================================================
// 1. Motion Command Data Types
// ============================================================================
enum MotionCommandType : uint8_t {
    MOTION_CMD_ABSOLUTE = 0,
    MOTION_CMD_RELATIVE,
    MOTION_CMD_CENTER,
    MOTION_CMD_FREEZE,
    MOTION_CMD_ESTOP,
    MOTION_CMD_RELEASE_PWM,
    MOTION_CMD_RESUME
};

struct MotionCommand_t {
    MotionCommandType type;
    float pan;              // Degrees (absolute or relative delta)
    float tilt;             // Degrees (absolute or relative delta)
    float speed;            // Normalized speed [0.1, 1.0]
    bool smooth;            // Enable slew rate interpolation
    bool release_pwm;       // Depower servo coils in estop
};

// Real-time motion engine snapshot
struct MotionSnapshot_t {
    float current_pan;
    float current_tilt;
    float target_pan;
    float target_tilt;
    bool is_moving;
    bool failsafe_active;
    bool estop_active;
    bool obstruction_halt;
};

// ============================================================================
// 2. Buzzer Command Data Types
// ============================================================================
enum BuzzerCommandAction : uint8_t {
    BUZZER_ACT_OFF = 0,
    BUZZER_ACT_BEEP,
    BUZZER_ACT_CHIRP,
    BUZZER_ACT_ALARM,
    BUZZER_ACT_PULSE,
    BUZZER_ACT_MUTE
};

struct BuzzerCommand_t {
    BuzzerCommandAction action;
    uint16_t duration_ms;
    uint8_t count;
    uint16_t interval_ms;
};

// ============================================================================
// 3. Sensor Acquisition Snapshot
// ============================================================================
struct SensorSnapshot_t {
    // HC-SR04 Ultrasonic Sensor
    float sonar_distance_cm;
    bool sonar_valid;
    char sonar_status[16];   // "in_range", "out_of_range", "timeout"

    // HC-SR501 PIR Motion Sensor
    bool pir_motion;
    uint32_t pir_trigger_count;
    uint32_t pir_last_trigger_ms;
    bool pir_warmup_complete;

    // Active Buzzer Driver
    bool buzzer_active;
    char buzzer_pattern[16]; // "off", "beep", "chirp", "alarm", "pulse"

    // Safety Threshold Flags
    bool proximity_warning;     // 20cm <= distance <= 40cm
    bool proximity_obstruction; // distance < 20cm (critical halt)
};

// ============================================================================
// 4. System & Telemetry Snapshot
// ============================================================================
struct SystemSnapshot_t {
    uint32_t uptime_ms;
    int32_t rssi_dbm;
    uint32_t free_heap_bytes;
    uint32_t psram_free_bytes;
    float cpu_temp_c;
    bool wifi_connected;
    bool ws_connected;
    bool failsafe_active;
    bool estop_active;
    char ip_addr[24];
};

// Outbound message container for inter-task queue
struct OutboxMessage_t {
    char json[768];
};
