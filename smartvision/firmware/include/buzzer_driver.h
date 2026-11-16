/**
 * @file buzzer_driver.h
 * @brief Non-blocking Active Buzzer Driver for SmartVision.
 *
 * Drives an active 5V buzzer via an NPN transistor (2N2222) connected to GPIO 7.
 * Provides a non-blocking state machine supporting Beep, Chirp, Alarm, Pulse, and Mute patterns.
 * Follows Ponytail principles: no external dependencies, zero delay() calls in update loop.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"

enum BuzzerPattern : uint8_t {
    BUZZER_PATTERN_OFF = 0,
    BUZZER_PATTERN_BEEP,
    BUZZER_PATTERN_CHIRP,
    BUZZER_PATTERN_ALARM,
    BUZZER_PATTERN_PULSE
};

class BuzzerDriver {
public:
    explicit BuzzerDriver(uint8_t pin = PIN_BUZZER, uint8_t active_level = BUZZER_ACTIVE_LEVEL)
        : _pin(pin),
          _active_level(active_level),
          _pattern(BUZZER_PATTERN_OFF),
          _pin_state(false),
          _step(0),
          _step_start_ms(0),
          _pulse_count_remaining(0),
          _pulse_on_ms(0),
          _pulse_off_ms(0) {
    }

    /**
     * @brief Configure GPIO pin mode and ensure buzzer is silent.
     */
    void begin() {
        pinMode(_pin, OUTPUT);
        _setHardwarePin(false);
        _pattern = BUZZER_PATTERN_OFF;
        _pin_state = false;
        _step = 0;
    }

    /**
     * @brief Immediately silence buzzer and reset state machine.
     */
    void mute() {
        _pattern = BUZZER_PATTERN_OFF;
        _step = 0;
        _pulse_count_remaining = 0;
        _setHardwarePin(false);
    }

    /**
     * @brief Alias for mute().
     */
    void off() {
        mute();
    }

    /**
     * @brief Trigger a single audible beep for the specified duration.
     * @param duration_ms Duration in milliseconds (default 150ms). If 0, mutes.
     */
    void beep(uint16_t duration_ms = BUZZER_DEFAULT_BEEP_MS) {
        if (duration_ms == 0) {
            mute();
            return;
        }
        _pattern = BUZZER_PATTERN_BEEP;
        _pulse_on_ms = duration_ms;
        _step = 1; // ON phase
        _step_start_ms = millis();
        _setHardwarePin(true);
    }

    /**
     * @brief Trigger a double-chirp alert (70ms ON, 50ms OFF, 70ms ON).
     */
    void chirp() {
        _pattern = BUZZER_PATTERN_CHIRP;
        _step = 1; // Step 1: 1st pulse ON
        _step_start_ms = millis();
        _setHardwarePin(true);
    }

    /**
     * @brief Start or stop a continuous emergency alarm (alternating 150ms ON / 150ms OFF).
     * @param enable True to start alarm, False to mute.
     */
    void alarm(bool enable = true) {
        if (!enable) {
            mute();
            return;
        }
        _pattern = BUZZER_PATTERN_ALARM;
        _step = 1; // ON phase
        _step_start_ms = millis();
        _setHardwarePin(true);
    }

    /**
     * @brief Trigger a fixed number of beep pulses.
     * @param count Number of pulses to emit.
     * @param on_ms Pulse duration in milliseconds.
     * @param off_ms Pause duration between pulses in milliseconds.
     */
    void pulse(uint16_t count, uint16_t on_ms = 100, uint16_t off_ms = 100) {
        if (count == 0 || on_ms == 0) {
            mute();
            return;
        }
        _pattern = BUZZER_PATTERN_PULSE;
        _pulse_count_remaining = count;
        _pulse_on_ms = on_ms;
        _pulse_off_ms = off_ms;
        _step = 1; // ON phase
        _step_start_ms = millis();
        _setHardwarePin(true);
    }

    /**
     * @brief Non-blocking pattern state machine update. Must be called in loop().
     */
    void update() {
        update(millis());
    }

    /**
     * @brief Non-blocking pattern state machine update with explicit timestamp.
     * @param now_ms Current timestamp in milliseconds.
     */
    void update(uint32_t now_ms) {
        switch (_pattern) {
            case BUZZER_PATTERN_OFF:
                if (_pin_state) {
                    _setHardwarePin(false);
                }
                break;

            case BUZZER_PATTERN_BEEP:
                if (_step == 1 && (now_ms - _step_start_ms >= _pulse_on_ms)) {
                    _setHardwarePin(false);
                    _pattern = BUZZER_PATTERN_OFF;
                    _step = 0;
                }
                break;

            case BUZZER_PATTERN_CHIRP:
                // Step 1: 1st Pulse ON (70ms)
                // Step 2: Gap OFF (50ms)
                // Step 3: 2nd Pulse ON (70ms)
                // Step 4: Done -> OFF
                if (_step == 1 && (now_ms - _step_start_ms >= BUZZER_CHIRP_PULSE_MS)) {
                    _setHardwarePin(false);
                    _step = 2;
                    _step_start_ms = now_ms;
                } else if (_step == 2 && (now_ms - _step_start_ms >= BUZZER_CHIRP_GAP_MS)) {
                    _setHardwarePin(true);
                    _step = 3;
                    _step_start_ms = now_ms;
                } else if (_step == 3 && (now_ms - _step_start_ms >= BUZZER_CHIRP_PULSE_MS)) {
                    _setHardwarePin(false);
                    _pattern = BUZZER_PATTERN_OFF;
                    _step = 0;
                }
                break;

            case BUZZER_PATTERN_ALARM:
                // Alternates 150ms ON, 150ms OFF indefinitely until mute()
                if (_step == 1 && (now_ms - _step_start_ms >= BUZZER_ALARM_INTERVAL_MS)) {
                    _setHardwarePin(false);
                    _step = 2;
                    _step_start_ms = now_ms;
                } else if (_step == 2 && (now_ms - _step_start_ms >= BUZZER_ALARM_INTERVAL_MS)) {
                    _setHardwarePin(true);
                    _step = 1;
                    _step_start_ms = now_ms;
                }
                break;

            case BUZZER_PATTERN_PULSE:
                if (_step == 1 && (now_ms - _step_start_ms >= _pulse_on_ms)) {
                    _setHardwarePin(false);
                    _step = 2;
                    _step_start_ms = now_ms;
                } else if (_step == 2 && (now_ms - _step_start_ms >= _pulse_off_ms)) {
                    if (_pulse_count_remaining > 1) {
                        _pulse_count_remaining--;
                        _setHardwarePin(true);
                        _step = 1;
                        _step_start_ms = now_ms;
                    } else {
                        _pattern = BUZZER_PATTERN_OFF;
                        _step = 0;
                        _pulse_count_remaining = 0;
                    }
                }
                break;
        }
    }

    /**
     * @brief Check if buzzer is currently emitting sound (pin is HIGH).
     */
    bool isActive() const {
        return _pin_state;
    }

    /**
     * @brief Retrieve current active pattern enum.
     */
    BuzzerPattern getPattern() const {
        return _pattern;
    }

    /**
     * @brief Get human-readable and JSON-compliant pattern name string.
     */
    const char* getPatternName() const {
        switch (_pattern) {
            case BUZZER_PATTERN_OFF:   return "off";
            case BUZZER_PATTERN_BEEP:  return "beep";
            case BUZZER_PATTERN_CHIRP: return "chirp";
            case BUZZER_PATTERN_ALARM: return "alarm";
            case BUZZER_PATTERN_PULSE: return "pulse";
            default:                   return "off";
        }
    }

    uint8_t getPin() const {
        return _pin;
    }

private:
    uint8_t _pin;
    uint8_t _active_level;
    BuzzerPattern _pattern;
    bool _pin_state;
    uint8_t _step;
    uint32_t _step_start_ms;
    uint16_t _pulse_count_remaining;
    uint16_t _pulse_on_ms;
    uint16_t _pulse_off_ms;

    void _setHardwarePin(bool state) {
        _pin_state = state;
        digitalWrite(_pin, state ? _active_level : !_active_level);
    }
};
