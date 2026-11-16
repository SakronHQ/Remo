/**
 * @file hcsr501_driver.h
 * @brief HC-SR501 PIR Motion Sensor Driver with Warm-up Stabilization Management.
 *
 * Handles the 30-60 second boot warm-up window of pyroelectric infrared sensors,
 * suppresses spurious startup transients, and provides debounced motion detection,
 * trigger counting, and timestamp tracking.
 *
 * Follows Ponytail principles: lightweight, zero external dependencies.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"

class HCSR501Driver {
public:
    explicit HCSR501Driver(uint8_t pin = PIN_PIR_INPUT, 
                           uint32_t warmup_duration_ms = PIR_WARMUP_DEFAULT_MS)
        : _pin(pin),
          _warmup_duration_ms(warmup_duration_ms),
          _boot_time_ms(0),
          _warmup_complete(false),
          _motion_detected(false),
          _raw_level(false),
          _prev_level(false),
          _trigger_count(0),
          _last_trigger_ms(0),
          _last_edge_ms(0) {
    }

    /**
     * @brief Configure PIR digital input pin with internal pull-down and record boot time.
     */
    void begin() {
        pinMode(_pin, INPUT_PULLDOWN);
        _boot_time_ms = millis();
        _warmup_complete = (_warmup_duration_ms == 0);
        _motion_detected = false;
        _raw_level = (digitalRead(_pin) == HIGH);
        _prev_level = _raw_level;
        _trigger_count = 0;
        _last_trigger_ms = 0;
        _last_edge_ms = millis();
    }

    /**
     * @brief Non-blocking sensor update. Polls pin, checks warm-up window, debounces edges.
     * @return True if a new motion trigger (rising edge) occurred on this call.
     */
    bool update() {
        return update(millis());
    }

    /**
     * @brief Non-blocking sensor update with explicit timestamp.
     * @param now_ms Current timestamp in milliseconds.
     * @return True if a new motion trigger (rising edge) occurred on this call.
     */
    bool update(uint32_t now_ms) {
        _raw_level = (digitalRead(_pin) == HIGH);

        // Check if boot warm-up stabilization window has elapsed
        if (!_warmup_complete) {
            if (now_ms - _boot_time_ms >= _warmup_duration_ms) {
                _warmup_complete = true;
                _prev_level = _raw_level; // Synchronize with warm-up exit state
                _motion_detected = false; // Strictly false at the warm-up boundary
                return false;
            } else {
                // During warm-up, pyroelectric transients are discarded
                _motion_detected = false;
                _prev_level = _raw_level;
                return false;
            }
        }

        // Post-warmup active monitoring
        bool new_trigger = false;

        if (_raw_level != _prev_level) {
            // Software debounce check
            if (now_ms - _last_edge_ms >= PIR_DEBOUNCE_MS) {
                _last_edge_ms = now_ms;
                if (_raw_level) {
                    // Rising edge: Motion detected
                    _trigger_count++;
                    _last_trigger_ms = now_ms;
                    _motion_detected = true;
                    new_trigger = true;
                } else {
                    // Falling edge: Motion cleared
                    _motion_detected = false;
                }
                _prev_level = _raw_level;
            }
        } else {
            _motion_detected = _raw_level;
        }

        return new_trigger;
    }

    /**
     * @brief Whether motion is currently detected. Strictly false during warm-up.
     */
    bool isMotionDetected() const {
        return _warmup_complete ? _motion_detected : false;
    }

    /**
     * @brief Direct instantaneous logic level of PIR input pin (useful for diagnostics).
     */
    bool getRawLevel() const {
        return _raw_level;
    }

    /**
     * @brief Check whether sensor has completed its boot stabilization window.
     */
    bool isWarmupComplete() const {
        return _warmup_complete;
    }

    /**
     * @brief Check whether sensor is still in its boot stabilization window.
     */
    bool isWarmingUp() const {
        return !_warmup_complete;
    }

    /**
     * @brief Remaining warm-up duration in milliseconds. Returns 0 if complete.
     */
    uint32_t getWarmupRemainingMs(uint32_t now_ms = 0) const {
        if (_warmup_complete) return 0;
        if (now_ms == 0) now_ms = millis();
        uint32_t elapsed = now_ms - _boot_time_ms;
        return (elapsed >= _warmup_duration_ms) ? 0 : (_warmup_duration_ms - elapsed);
    }

    /**
     * @brief Elapsed time since boot in milliseconds.
     */
    uint32_t getWarmupElapsedMs(uint32_t now_ms = 0) const {
        if (now_ms == 0) now_ms = millis();
        return now_ms - _boot_time_ms;
    }

    /**
     * @brief Warm-up progress factor from 0.0f (boot) to 1.0f (fully stabilized).
     */
    float getWarmupProgress(uint32_t now_ms = 0) const {
        if (_warmup_complete || _warmup_duration_ms == 0) return 1.0f;
        if (now_ms == 0) now_ms = millis();
        uint32_t elapsed = now_ms - _boot_time_ms;
        if (elapsed >= _warmup_duration_ms) return 1.0f;
        return (float)elapsed / (float)_warmup_duration_ms;
    }

    /**
     * @brief Total count of confirmed motion triggers since warm-up.
     */
    uint32_t getTriggerCount() const {
        return _trigger_count;
    }

    /**
     * @brief Timestamp (millis) of the most recent confirmed rising-edge motion trigger.
     */
    uint32_t getLastTriggerMs() const {
        return _last_trigger_ms;
    }

    /**
     * @brief Bypass warm-up countdown (useful for automated testing or bench calibration).
     */
    void forceWarmupComplete() {
        _warmup_complete = true;
        _prev_level = _raw_level;
        _motion_detected = false;
    }

    /**
     * @brief Reset cumulative trigger count to zero.
     */
    void resetStats() {
        _trigger_count = 0;
    }

    void setWarmupDurationMs(uint32_t ms) {
        _warmup_duration_ms = ms;
    }

    uint8_t getPin() const {
        return _pin;
    }

private:
    uint8_t _pin;
    uint32_t _warmup_duration_ms;
    uint32_t _boot_time_ms;
    bool _warmup_complete;
    bool _motion_detected;
    bool _raw_level;
    bool _prev_level;
    uint32_t _trigger_count;
    uint32_t _last_trigger_ms;
    uint32_t _last_edge_ms;
};
