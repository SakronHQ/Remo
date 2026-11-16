/**
 * @file hcsr04_driver.h
 * @brief Non-blocking, Timeout-Safe HC-SR04 Ultrasonic Distance Sensor Driver.
 *
 * Implements safe trigger pulsing, echo pulse timing with bounded timeout (30ms),
 * conversion to cm with optional temperature compensation, out-of-range rejection,
 * and a 5-sample median filter for acoustic spike suppression.
 *
 * Follows Ponytail principles: standard Arduino primitives, zero external library bloat.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"

enum SonarStatus : uint8_t {
    SONAR_STATUS_IN_RANGE = 0,
    SONAR_STATUS_OUT_OF_RANGE,
    SONAR_STATUS_TIMEOUT
};

class HCSR04Driver {
public:
    HCSR04Driver(uint8_t trig_pin = PIN_ULTRASONIC_TRIG, 
                 uint8_t echo_pin = PIN_ULTRASONIC_ECHO,
                 uint32_t sample_interval_ms = ULTRASONIC_SAMPLE_INTERVAL_MS)
        : _trig_pin(trig_pin),
          _echo_pin(echo_pin),
          _sample_interval_ms(sample_interval_ms),
          _last_distance_cm(-1.0f),
          _raw_distance_cm(-1.0f),
          _filtered_distance_cm(-1.0f),
          _last_echo_us(0),
          _last_sample_ms(0),
          _status(SONAR_STATUS_TIMEOUT),
          _valid(false),
          _sample_count(0),
          _ring_idx(0) {
        for (uint8_t i = 0; i < 5; i++) {
            _history[i] = -1.0f;
        }
    }

    /**
     * @brief Configure Trigger (OUTPUT, LOW) and Echo (INPUT) pins.
     */
    void begin() {
        pinMode(_trig_pin, OUTPUT);
        digitalWrite(_trig_pin, LOW);
        pinMode(_echo_pin, INPUT);
        _last_distance_cm = -1.0f;
        _raw_distance_cm = -1.0f;
        _filtered_distance_cm = -1.0f;
        _last_echo_us = 0;
        _status = SONAR_STATUS_TIMEOUT;
        _valid = false;
        _sample_count = 0;
        _ring_idx = 0;
    }

    /**
     * @brief Perform an immediate synchronous ultrasonic ping with bounded timeout.
     * @param temp_c Ambient temperature in Celsius (defaults to 20°C nominal room air).
     * @return Valid distance in cm [2.0, 400.0], or -1.0f on timeout / out-of-range.
     */
    float measureDistanceCm(float temp_c = DEFAULT_AMBIENT_TEMP_C) {
        // Ensure clean LOW state on trigger line
        digitalWrite(_trig_pin, LOW);
        delayMicroseconds(4);

        // Issue 10 microsecond HIGH pulse to initiate 40 kHz burst
        digitalWrite(_trig_pin, HIGH);
        delayMicroseconds(ULTRASONIC_TRIG_PULSE_US);
        digitalWrite(_trig_pin, LOW);

        // Bounded echo timing with safe timeout
        uint32_t duration_us = pulseIn(_echo_pin, HIGH, ULTRASONIC_TIMEOUT_US);
        _last_echo_us = duration_us;
        _last_sample_ms = millis();

        if (duration_us == 0 || duration_us >= ULTRASONIC_TIMEOUT_US) {
            _status = SONAR_STATUS_TIMEOUT;
            _valid = false;
            _raw_distance_cm = -1.0f;
            _last_distance_cm = -1.0f;
            return -1.0f;
        }

        // Calculate distance based on ambient temperature
        float speed_cm_us = calculateSpeedOfSoundCmPerUs(temp_c);
        float raw_dist = (duration_us * speed_cm_us) * 0.5f;
        _raw_distance_cm = raw_dist;

        // Out-of-range rejection (2.0 cm to 400.0 cm with 0.1cm rounding allowance)
        if (raw_dist < (ULTRASONIC_MIN_DISTANCE_CM - 0.1f) || raw_dist > (ULTRASONIC_MAX_DISTANCE_CM + 0.1f)) {
            _status = SONAR_STATUS_OUT_OF_RANGE;
            _valid = false;
            _last_distance_cm = -1.0f; // Conforms to protocol.md specification (-1.0f when invalid)
        } else {
            _status = SONAR_STATUS_IN_RANGE;
            _valid = true;
            _last_distance_cm = raw_dist;

            // Update rolling history for median filtering
            _history[_ring_idx] = raw_dist;
            _ring_idx = (_ring_idx + 1) % 5;
            if (_sample_count < 5) {
                _sample_count++;
            }
            _filtered_distance_cm = _calculateMedian();
        }

        return _last_distance_cm;
    }

    /**
     * @brief Non-blocking cadence controller. Pings sensor when interval has elapsed.
     * @return True if a new measurement was completed on this call.
     */
    bool update() {
        return update(millis(), DEFAULT_AMBIENT_TEMP_C);
    }

    /**
     * @brief Non-blocking cadence controller with explicit timestamp and temperature.
     * @param now_ms Current timestamp in milliseconds.
     * @param temp_c Ambient air temperature in Celsius.
     * @return True if a new measurement was completed on this call.
     */
    bool update(uint32_t now_ms, float temp_c = DEFAULT_AMBIENT_TEMP_C) {
        if (now_ms - _last_sample_ms >= _sample_interval_ms) {
            measureDistanceCm(temp_c);
            return true;
        }
        return false;
    }

    /**
     * @brief Latest instantaneous valid distance in cm (-1.0f if out-of-range/timeout).
     */
    float getDistanceCm() const {
        return _last_distance_cm;
    }

    /**
     * @brief Latest physical raw distance in cm regardless of range boundaries (-1.0f on timeout).
     */
    float getRawDistanceCm() const {
        return _raw_distance_cm;
    }

    /**
     * @brief Median-filtered distance in cm across the last 5 valid readings (-1.0f if invalid).
     */
    float getFilteredDistanceCm() const {
        return (_sample_count > 0 && _valid) ? _filtered_distance_cm : _last_distance_cm;
    }

    /**
     * @brief Whether the latest reading is within valid operating range [2.0, 400.0] cm.
     */
    bool isValid() const {
        return _valid;
    }

    /**
     * @brief Retrieve SonarStatus enum (IN_RANGE, OUT_OF_RANGE, TIMEOUT).
     */
    SonarStatus getStatus() const {
        return _status;
    }

    /**
     * @brief Formatted status string matching docs/protocol.md.
     */
    const char* getStatusString() const {
        switch (_status) {
            case SONAR_STATUS_IN_RANGE:     return "in_range";
            case SONAR_STATUS_OUT_OF_RANGE: return "out_of_range";
            case SONAR_STATUS_TIMEOUT:      return "timeout";
            default:                        return "timeout";
        }
    }

    /**
     * @brief Measured echo pulse duration in microseconds.
     */
    uint32_t getLastEchoUs() const {
        return _last_echo_us;
    }

    /**
     * @brief Timestamp (millis) when last sample was captured.
     */
    uint32_t getLastSampleMs() const {
        return _last_sample_ms;
    }

    /**
     * @brief Check if obstacle is within critical proximity limit (< 20.0 cm).
     * Defensively includes close-range reflections (< 2.0 cm) even if below sensor linear range.
     */
    bool isObstruction() const {
        if (_last_echo_us > 0 && _last_echo_us < ULTRASONIC_TIMEOUT_US) {
            float d = (_last_echo_us * calculateSpeedOfSoundCmPerUs(DEFAULT_AMBIENT_TEMP_C)) * 0.5f;
            if (d < PROXIMITY_OBSTRUCTION_CM) {
                return true;
            }
        }
        return _valid && (_last_distance_cm < PROXIMITY_OBSTRUCTION_CM);
    }

    /**
     * @brief Check if obstacle is within warning proximity zone [20.0, 40.0] cm.
     */
    bool isWarning() const {
        return _valid && (_last_distance_cm >= PROXIMITY_OBSTRUCTION_CM) && (_last_distance_cm <= PROXIMITY_WARNING_CM);
    }

    void setSampleIntervalMs(uint32_t ms) {
        _sample_interval_ms = ms;
    }

private:
    uint8_t _trig_pin;
    uint8_t _echo_pin;
    uint32_t _sample_interval_ms;
    float _last_distance_cm;
    float _raw_distance_cm;
    float _filtered_distance_cm;
    uint32_t _last_echo_us;
    uint32_t _last_sample_ms;
    SonarStatus _status;
    bool _valid;

    float _history[5];
    uint8_t _sample_count;
    uint8_t _ring_idx;

    float _calculateMedian() {
        if (_sample_count == 0) return -1.0f;
        float sorted[5];
        for (uint8_t i = 0; i < _sample_count; i++) {
            sorted[i] = _history[i];
        }
        // Simple insertion sort on small buffer
        for (uint8_t i = 1; i < _sample_count; i++) {
            float key = sorted[i];
            int j = i - 1;
            while (j >= 0 && sorted[j] > key) {
                sorted[j + 1] = sorted[j];
                j--;
            }
            sorted[j + 1] = key;
        }
        return sorted[_sample_count / 2];
    }
};
