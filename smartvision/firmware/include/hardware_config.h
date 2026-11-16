/**
 * @file hardware_config.h
 * @brief SmartVision Hardware Pinout, PCA9685 Parameters, and Calibrated Servo Limits.
 *
 * Designed for ESP32-S3 N16R8, PCA9685 I2C 16-channel PWM driver,
 * TowerPro MG996R (Pan, Ch 0), and TowerPro MG90S (Tilt, Ch 1).
 */

#pragma once

#include <Arduino.h>

// ============================================================================
// 1. ESP32-S3 Pin Definitions
// ============================================================================
#define PIN_I2C_SDA         8   // I2C Data (Bidirectional, 4.7k pull-up)
#define PIN_I2C_SCL         9   // I2C Clock (Clock, 4.7k pull-up)
#define PIN_PCA9685_OE     12   // Hardware Output Enable (Active LOW, LOW=enabled, HIGH=disabled)
#define PIN_STATUS_LED     10   // On-board / System Status LED (Active HIGH via 330R)
#define PIN_BUZZER          7   // Active Buzzer Driver (via 2N2222 NPN)
#define PIN_ULTRASONIC_TRIG 4   // HC-SR04 Trigger (3.3V push-pull)
#define PIN_ULTRASONIC_ECHO 5   // HC-SR04 Echo (via 1k/2k voltage divider to 3.3V)
#define PIN_PIR_INPUT       6   // HC-SR501 PIR Output (Native 3.3V logic)

// Silicon Constraint Check: GPIO 33-37 are Octal PSRAM bonded; never use them.
#define ASSERT_VALID_PIN(pin) static_assert(!((pin) >= 33 && (pin) <= 37), "FATAL: GPIO 33-37 are reserved for Octal PSRAM!");

// Validate all active SmartVision pins at compile time
ASSERT_VALID_PIN(PIN_I2C_SDA)
ASSERT_VALID_PIN(PIN_I2C_SCL)
ASSERT_VALID_PIN(PIN_PCA9685_OE)
ASSERT_VALID_PIN(PIN_STATUS_LED)
ASSERT_VALID_PIN(PIN_BUZZER)
ASSERT_VALID_PIN(PIN_ULTRASONIC_TRIG)
ASSERT_VALID_PIN(PIN_ULTRASONIC_ECHO)
ASSERT_VALID_PIN(PIN_PIR_INPUT)

// ============================================================================
// 2. PCA9685 I2C Registers and Timing
// ============================================================================
#define PCA9685_I2C_ADDR    0x40    // Default address when A0..A5 solder pads open
#define PCA9685_MODE1       0x00    // Control Register 1
#define PCA9685_MODE2       0x01    // Control Register 2
#define PCA9685_SUBADR1     0x02    // I2C-bus subaddress 1
#define PCA9685_SUBADR2     0x03    // I2C-bus subaddress 2
#define PCA9685_SUBADR3     0x04    // I2C-bus subaddress 3
#define PCA9685_ALLCALLADR  0x05    // LED All Call I2C-bus address
#define PCA9685_LED0_ON_L   0x06    // LED0 output and brightness control byte 0
#define PCA9685_PRESCALE    0xFE    // Prescaler for PWM output frequency

#define PCA9685_PWM_FREQ    50      // 50 Hz standard servo frequency (20ms period)
#define PCA9685_OSC_CLOCK   25000000L // 25 MHz internal oscillator
// Prescale = round(25000000 / (4096 * 50)) - 1 = round(122.07) - 1 = 121 (0x79)
#define PCA9685_PRESCALE_VAL 121

// Tick resolution: 20000 us / 4096 ticks = 4.8828125 us/tick
#define PCA9685_US_PER_TICK 4.8828125f

// ============================================================================
// 3. Servo Calibration Limits (TowerPro MG996R & MG90S)
// ============================================================================
// Physical RC servo timing: 0.0° = 500 µs, 180.0° = 2500 µs
#define SERVO_PULSE_MIN_US      500.0f  // Pulse width at 0° (102 ticks)
#define SERVO_PULSE_MAX_US      2500.0f // Pulse width at 180° (512 ticks)

// Pan Servo: TowerPro MG996R on PCA9685 Channel 0
#define SERVO_PAN_CHANNEL       0
#define SERVO_PAN_MIN_DEG       15.0f   // Conservative safe limit (prevents chassis collision)
#define SERVO_PAN_MAX_DEG       165.0f  // Conservative safe limit (prevents USB cable strain)
#define SERVO_PAN_CENTER_DEG    90.0f   // Neutral pointing angle
#define SERVO_PAN_MIN_TICKS     137     // 15 deg  (~667 us)
#define SERVO_PAN_MAX_TICKS     478     // 165 deg (~2333 us)
#define SERVO_PAN_CENTER_TICKS  307     // 90 deg  (~1500 us)

// Tilt Servo: TowerPro MG90S on PCA9685 Channel 1
#define SERVO_TILT_CHANNEL      1
#define SERVO_TILT_MIN_DEG      60.0f   // Conservative limit (prevents downward gimbal collision)
#define SERVO_TILT_MAX_DEG      135.0f  // Conservative limit (prevents upward cable pinch)
#define SERVO_TILT_CENTER_DEG   90.0f   // Neutral pointing angle (level horizon)
#define SERVO_TILT_MIN_TICKS    239     // 60 deg  (~1167 us)
#define SERVO_TILT_MAX_TICKS    410     // 135 deg (~2000 us)
#define SERVO_TILT_CENTER_TICKS 307     // 90 deg  (~1500 us)

// Slew Rate Limits for Soft Movement (Degrees per Step)
#define SERVO_SLEW_STEP_DEG     1.0f    // 1 degree per step
#define SERVO_SLEW_DELAY_MS     15      // 15 ms delay between steps (~66.7 deg/sec)

// ============================================================================
// 4. Utility Functions for Safe Mapping & Clamping
// ============================================================================

/**
 * @brief Strictly clamp pan angle to certified conservative limits [15.0, 165.0].
 * Safely defaults to neutral center (90.0°) if input is NaN.
 */
inline float clampPanAngle(float deg) {
    if (isnan(deg)) return SERVO_PAN_CENTER_DEG;
    if (deg < SERVO_PAN_MIN_DEG) return SERVO_PAN_MIN_DEG;
    if (deg > SERVO_PAN_MAX_DEG) return SERVO_PAN_MAX_DEG;
    return deg;
}

/**
 * @brief Strictly clamp tilt angle to certified conservative limits [60.0, 135.0].
 * Safely defaults to neutral center (90.0°) if input is NaN.
 */
inline float clampTiltAngle(float deg) {
    if (isnan(deg)) return SERVO_TILT_CENTER_DEG;
    if (deg < SERVO_TILT_MIN_DEG) return SERVO_TILT_MIN_DEG;
    if (deg > SERVO_TILT_MAX_DEG) return SERVO_TILT_MAX_DEG;
    return deg;
}

/**
 * @brief Map physical angle [0..180] to PCA9685 12-bit tick count based on 500-2500 us pulse.
 */
inline uint16_t angleToTicks(float deg) {
    if (isnan(deg)) return SERVO_PAN_CENTER_TICKS;
    float pulse_us = SERVO_PULSE_MIN_US + (deg / 180.0f) * (SERVO_PULSE_MAX_US - SERVO_PULSE_MIN_US);
    return (uint16_t)((pulse_us / PCA9685_US_PER_TICK) + 0.5f);
}

/**
 * @brief Convert pan angle in degrees to PCA9685 12-bit tick count (137 - 478)
 */
inline uint16_t panAngleToTicks(float deg) {
    return angleToTicks(clampPanAngle(deg));
}

/**
 * @brief Convert tilt angle in degrees to PCA9685 12-bit tick count (239 - 410)
 */
inline uint16_t tiltAngleToTicks(float deg) {
    return angleToTicks(clampTiltAngle(deg));
}

// ============================================================================
// 5. Sensor Configuration & Thresholds (Phase 2)
// ============================================================================

// HC-SR04 Ultrasonic Distance Sensor
#define ULTRASONIC_MIN_DISTANCE_CM      2.0f    // Minimum reliable sensing distance (cm)
#define ULTRASONIC_MAX_DISTANCE_CM      400.0f  // Maximum reliable sensing distance (cm)
#define ULTRASONIC_TIMEOUT_US           30000UL // 30ms echo timeout (~514cm max flight time)
#define ULTRASONIC_TRIG_PULSE_US        10UL    // 10 microsecond trigger pulse width
#define ULTRASONIC_SAMPLE_INTERVAL_MS   100UL   // 10 Hz sampling cadence (prevents acoustic ringing)
#define SPEED_OF_SOUND_20C_CM_PER_US    0.034342f // 343.42 m/s at 20°C
#define DEFAULT_AMBIENT_TEMP_C          20.0f   // Nominal ambient room temperature in dry air

// Proximity Warning & Safety Stop Thresholds (matching docs/protocol.md)
#define PROXIMITY_OBSTRUCTION_CM        20.0f   // Critical threshold: halts servo movement (< 20 cm)
#define PROXIMITY_WARNING_CM            40.0f   // Warning threshold: triggers warning chirps (20 - 40 cm)

// HC-SR501 PIR Motion Sensor
#define PIR_WARMUP_DEFAULT_MS           30000UL // 30-second thermal stabilization window
#define PIR_DEBOUNCE_MS                 50UL    // Software debounce filter

// Active Buzzer Driver (GPIO 7 via 2N2222 NPN)
#define BUZZER_ACTIVE_LEVEL             HIGH    // HIGH turns ON NPN transistor (low-side sink)
#define BUZZER_DEFAULT_BEEP_MS          150UL   // Standard notification beep
#define BUZZER_CHIRP_PULSE_MS           70UL    // Alert chirp pulse duration
#define BUZZER_CHIRP_GAP_MS             50UL    // Inter-pulse gap for chirp
#define BUZZER_ALARM_INTERVAL_MS        150UL   // Emergency alarm toggle interval

/**
 * @brief Calculate speed of sound in air (cm/us) for a given ambient temperature in Celsius.
 * Formula: v(T) = (331.3 + 0.606 * T) m/s
 * Note: Must use ambient air temperature, NEVER uncalibrated MCU CPU die junction temperature.
 */
inline float calculateSpeedOfSoundCmPerUs(float temp_c = DEFAULT_AMBIENT_TEMP_C) {
    if (isnan(temp_c) || temp_c < -40.0f || temp_c > 85.0f) {
        temp_c = DEFAULT_AMBIENT_TEMP_C; // Safe default
    }
    return (331.3f + 0.606f * temp_c) * 100.0f / 1000000.0f;
}

/**
 * @brief Convert ultrasonic roundtrip echo time in microseconds to distance in centimeters.
 * Returns -1.0f on timeout or out-of-range (< 2.0 cm or > 400.0 cm).
 */
inline float echoTimeToDistanceCm(uint32_t echo_us, float temp_c = DEFAULT_AMBIENT_TEMP_C) {
    if (echo_us == 0 || echo_us >= ULTRASONIC_TIMEOUT_US) {
        return -1.0f;
    }
    float speed = calculateSpeedOfSoundCmPerUs(temp_c);
    float dist = (echo_us * speed) * 0.5f;
    if (dist < (ULTRASONIC_MIN_DISTANCE_CM - 0.1f) || dist > (ULTRASONIC_MAX_DISTANCE_CM + 0.1f)) {
        return -1.0f;
    }
    return dist;
}
