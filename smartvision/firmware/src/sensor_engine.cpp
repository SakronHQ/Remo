/**
 * @file sensor_engine.cpp
 * @brief Implementation of Unified Sensor Acquisition Engine.
 */

#include "sensor_engine.h"
#include <cstring>

SensorEngine::SensorEngine()
    : _sonar(PIN_ULTRASONIC_TRIG, PIN_ULTRASONIC_ECHO, ULTRASONIC_SAMPLE_INTERVAL_MS),
      _pir(PIN_PIR_INPUT, PIR_WARMUP_DEFAULT_MS),
      _buzzer(PIN_BUZZER, BUZZER_ACTIVE_LEVEL),
      _last_sample_ms(0),
      _last_distance_cm(-1.0f),
      _sonar_valid(false),
      _proximity_warning(false),
      _proximity_obstruction(false),
      _prev_obstruction(false) {
    strncpy(_sonar_status, "timeout", sizeof(_sonar_status));
}

void SensorEngine::begin() {
    Serial.println("[Sensor] Initializing HC-SR04, HC-SR501, and Buzzer drivers...");
    _sonar.begin();
    _pir.begin();
    _buzzer.begin();

    _last_sample_ms = millis();
    _last_distance_cm = -1.0f;
    _sonar_valid = false;
    _proximity_warning = false;
    _proximity_obstruction = false;
    _prev_obstruction = false;
    strncpy(_sonar_status, "timeout", sizeof(_sonar_status));

    // Friendly boot chirp confirmation
    _buzzer.beep(80);
}

bool SensorEngine::update() {
    // 1. Advance non-blocking buzzer state machine on every tick
    _buzzer.update();

    // 2. Poll PIR sensor (debounced edge detection)
    _pir.update();

    // 3. Cadenced 10 Hz ultrasonic sampling
    uint32_t now = millis();
    if (now - _last_sample_ms >= ULTRASONIC_SAMPLE_INTERVAL_MS) {
        _last_sample_ms = now;
        _sampleSensors();
        return true;
    }

    return false;
}

void SensorEngine::_sampleSensors() {
    // Perform non-blocking ultrasonic distance measurement
    _sonar.measureDistanceCm(DEFAULT_AMBIENT_TEMP_C);
    _last_distance_cm = _sonar.getFilteredDistanceCm();
    _sonar_valid = _sonar.isValid();

    switch (_sonar.getStatus()) {
        case SONAR_STATUS_IN_RANGE:
            strncpy(_sonar_status, "in_range", sizeof(_sonar_status));
            break;
        case SONAR_STATUS_OUT_OF_RANGE:
            strncpy(_sonar_status, "out_of_range", sizeof(_sonar_status));
            break;
        case SONAR_STATUS_TIMEOUT:
        default:
            strncpy(_sonar_status, "timeout", sizeof(_sonar_status));
            break;
    }

    // Evaluate proximity safety thresholds
    if (_sonar_valid && _last_distance_cm > 0.0f) {
        if (_last_distance_cm < PROXIMITY_OBSTRUCTION_CM) {
            _proximity_obstruction = true;
            _proximity_warning = true;

            // Trigger alert on new obstruction transition
            if (!_prev_obstruction) {
                Serial.printf("[Sensor] CRITICAL: Obstruction detected at %.1f cm!\n", _last_distance_cm);
                _buzzer.chirp();
            }
        } else if (_last_distance_cm <= PROXIMITY_WARNING_CM) {
            _proximity_obstruction = false;
            _proximity_warning = true;
        } else {
            _proximity_obstruction = false;
            _proximity_warning = false;
        }
    } else {
        _proximity_obstruction = false;
        _proximity_warning = false;
    }

    _prev_obstruction = _proximity_obstruction;
}

void SensorEngine::commandBuzzer(const char* action, uint16_t duration_ms, uint8_t count, uint16_t interval_ms) {
    if (action == nullptr) return;

    if (strcasecmp(action, "beep") == 0) {
        _buzzer.beep(duration_ms > 0 ? duration_ms : BUZZER_DEFAULT_BEEP_MS);
    } else if (strcasecmp(action, "chirp") == 0) {
        _buzzer.chirp();
    } else if (strcasecmp(action, "alarm") == 0) {
        _buzzer.alarm(true);
    } else if (strcasecmp(action, "pulse") == 0) {
        _buzzer.pulse(count > 0 ? count : 3, 
                      duration_ms > 0 ? duration_ms : 100, 
                      interval_ms > 0 ? interval_ms : 80);
    } else if (strcasecmp(action, "mute") == 0 || strcasecmp(action, "off") == 0) {
        _buzzer.mute();
    }
}

void SensorEngine::triggerFailsafeChirp() {
    _buzzer.chirp();
}

void SensorEngine::muteBuzzer() {
    _buzzer.mute();
}

void SensorEngine::getSnapshot(SensorSnapshot_t& snapshot) const {
    snapshot.sonar_distance_cm = _last_distance_cm;
    snapshot.sonar_valid = _sonar_valid;
    strncpy(snapshot.sonar_status, _sonar_status, sizeof(snapshot.sonar_status));

    snapshot.pir_motion = _pir.isMotionDetected();
    snapshot.pir_trigger_count = _pir.getTriggerCount();
    snapshot.pir_last_trigger_ms = _pir.getLastTriggerMs();
    snapshot.pir_warmup_complete = _pir.isWarmupComplete();

    snapshot.buzzer_active = _buzzer.isActive();
    strncpy(snapshot.buzzer_pattern, _buzzer.getPatternName(), sizeof(snapshot.buzzer_pattern));

    snapshot.proximity_warning = _proximity_warning;
    snapshot.proximity_obstruction = _proximity_obstruction;
}
