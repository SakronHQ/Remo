/**
 * @file sensor_engine.h
 * @brief Unified Sensor Acquisition Engine (HC-SR04, HC-SR501, Active Buzzer).
 *
 * Coordinates non-blocking 10 Hz ultrasonic distance sampling, median filtering,
 * PIR motion trigger tracking, buzzer state machine execution, and proximity threshold alerts.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"
#include "hcsr04_driver.h"
#include "hcsr501_driver.h"
#include "buzzer_driver.h"
#include "firmware_types.h"

class SensorEngine {
public:
    SensorEngine();

    /**
     * @brief Configure GPIOs, start PIR stabilization timer, and initialize drivers.
     */
    void begin();

    /**
     * @brief Update buzzer state machine and, when interval elapses, sample sensors.
     * Call frequently in the sensor task (e.g. every 10 ms).
     * @return true if a new 10 Hz sensor sample was acquired on this call.
     */
    bool update();

    /**
     * @brief Dispatch buzzer command pattern.
     * @param action "beep", "chirp", "alarm", "pulse", or "mute" / "off".
     * @param duration_ms Pulse duration in milliseconds.
     * @param count Pulse repetitions for pulse pattern.
     * @param interval_ms Inter-pulse gap for pulse pattern.
     */
    void commandBuzzer(const char* action, uint16_t duration_ms = 150, uint8_t count = 3, uint16_t interval_ms = 100);

    /**
     * @brief Trigger emergency failsafe warning chirp cadence.
     */
    void triggerFailsafeChirp();

    /**
     * @brief Silence all buzzer output immediately.
     */
    void muteBuzzer();

    /**
     * @brief Extract thread-safe snapshot of sensor telemetry.
     */
    void getSnapshot(SensorSnapshot_t& snapshot) const;

    float getDistanceCm() const { return _last_distance_cm; }
    bool  isMotionDetected() const { return _pir.isMotionDetected(); }
    bool  isProximityObstruction() const { return _proximity_obstruction; }
    bool  isProximityWarning() const { return _proximity_warning; }

private:
    HCSR04Driver _sonar;
    HCSR501Driver _pir;
    BuzzerDriver  _buzzer;

    uint32_t _last_sample_ms;
    float    _last_distance_cm;
    bool     _sonar_valid;
    char     _sonar_status[16];

    bool     _proximity_warning;
    bool     _proximity_obstruction;
    bool     _prev_obstruction;

    void _sampleSensors();
};
