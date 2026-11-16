/**
 * @file motion_engine.cpp
 * @brief Implementation of Discrete 50 Hz Motion Engine.
 */

#include "motion_engine.h"
#include <cmath>

MotionEngine::MotionEngine()
    : _driver(PCA9685_I2C_ADDR, PIN_PCA9685_OE),
      _current_pan(SERVO_PAN_CENTER_DEG),
      _current_tilt(SERVO_TILT_CENTER_DEG),
      _target_pan(SERVO_PAN_CENTER_DEG),
      _target_tilt(SERVO_TILT_CENTER_DEG),
      _slew_rate_deg_s(65.0f),
      _smooth(true),
      _is_moving(false),
      _failsafe_active(false),
      _estop_active(false),
      _obstruction_halt(false),
      _pwm_released(false) {
}

bool MotionEngine::begin() {
    Serial.println("[Motion] Initializing PCA9685 driver on I2C...");
    if (!_driver.begin(PIN_I2C_SDA, PIN_I2C_SCL, 100000)) {
        Serial.println("[Motion] ERROR: Failed to detect PCA9685 at 0x40!");
        return false;
    }

    _current_pan = SERVO_PAN_CENTER_DEG;
    _current_tilt = SERVO_TILT_CENTER_DEG;
    _target_pan = SERVO_PAN_CENTER_DEG;
    _target_tilt = SERVO_TILT_CENTER_DEG;
    _is_moving = false;
    _failsafe_active = false;
    _estop_active = false;
    _obstruction_halt = false;
    _pwm_released = false;

    _applyAnglesToHardware();
    Serial.printf("[Motion] Servos parked at center (Pan: %.1f°, Tilt: %.1f°)\n", 
                  _current_pan, _current_tilt);
    return true;
}

void MotionEngine::setTarget(float pan, float tilt, float speed_factor, bool smooth) {
    if (_estop_active || _failsafe_active || _obstruction_halt) {
        // Inhibited
        return;
    }

    // Clamp speed factor to [0.1, 1.0] and map to [10.0, 120.0] deg/s
    float speed = constrain(speed_factor, 0.1f, 1.0f);
    _slew_rate_deg_s = 10.0f + (speed * 110.0f);
    _smooth = smooth;

    // Apply Tier 2 physical limit clamps
    _target_pan = clampPanAngle(pan);
    _target_tilt = clampTiltAngle(tilt);

    if (!_smooth) {
        _current_pan = _target_pan;
        _current_tilt = _target_tilt;
        _applyAnglesToHardware();
        _is_moving = false;
    } else {
        _is_moving = (fabsf(_target_pan - _current_pan) > 0.1f) || 
                     (fabsf(_target_tilt - _current_tilt) > 0.1f);
    }
}

void MotionEngine::jog(float delta_pan, float delta_tilt, float speed_factor) {
    if (_estop_active || _failsafe_active || _obstruction_halt) return;
    setTarget(_current_pan + delta_pan, _current_tilt + delta_tilt, speed_factor, true);
}

void MotionEngine::center(float speed_factor) {
    _estop_active = false;      // Clear estop on intentional center recovery
    _obstruction_halt = false;  // Center is always a safe return
    if (_pwm_released) {
        _pwm_released = false;
        _driver.enableOutputs(true);
    }
    setTarget(SERVO_PAN_CENTER_DEG, SERVO_TILT_CENTER_DEG, speed_factor, true);
}

void MotionEngine::freeze() {
    _target_pan = _current_pan;
    _target_tilt = _current_tilt;
    _is_moving = false;
}

void MotionEngine::estop(bool release_pwm) {
    _estop_active = true;
    freeze();
    if (release_pwm) {
        releasePWM();
    }
}

void MotionEngine::enableOutputs(bool enable) {
    _driver.enableOutputs(enable);
}

void MotionEngine::releasePWM() {
    _pwm_released = true;
    _driver.turnOff(SERVO_PAN_CHANNEL);
    _driver.turnOff(SERVO_TILT_CHANNEL);
    _driver.enableOutputs(false); // OE HIGH = disable
}

void MotionEngine::setFailsafe(bool active) {
    _failsafe_active = active;
    if (active) {
        freeze();
    }
}

void MotionEngine::setObstructionHalt(bool halt) {
    _obstruction_halt = halt;
    if (halt) {
        freeze();
    }
}

void MotionEngine::resumeNormal() {
    _failsafe_active = false;
    _estop_active = false;
    _obstruction_halt = false;
    if (_pwm_released) {
        _pwm_released = false;
        _driver.enableOutputs(true);
        _applyAnglesToHardware();
    }
}

void MotionEngine::update(float dt_s) {
    if (_pwm_released) return;

    if (_failsafe_active || _estop_active || _obstruction_halt) {
        _is_moving = false;
        return;
    }

    if (!_is_moving) return;

    float max_step = _slew_rate_deg_s * dt_s;

    // Pan interpolation
    float diff_pan = _target_pan - _current_pan;
    if (fabsf(diff_pan) > 0.05f) {
        float step_pan = (diff_pan > 0.0f) ? min(diff_pan, max_step) : max(diff_pan, -max_step);
        _current_pan += step_pan;
    } else {
        _current_pan = _target_pan;
    }

    // Tilt interpolation
    float diff_tilt = _target_tilt - _current_tilt;
    if (fabsf(diff_tilt) > 0.05f) {
        float step_tilt = (diff_tilt > 0.0f) ? min(diff_tilt, max_step) : max(diff_tilt, -max_step);
        _current_tilt += step_tilt;
    } else {
        _current_tilt = _target_tilt;
    }

    _applyAnglesToHardware();

    _is_moving = (fabsf(_target_pan - _current_pan) > 0.05f) || 
                 (fabsf(_target_tilt - _current_tilt) > 0.05f);
}

void MotionEngine::_applyAnglesToHardware() {
    _driver.setPanAngle(_current_pan);
    _driver.setTiltAngle(_current_tilt);
}

void MotionEngine::getSnapshot(MotionSnapshot_t& snapshot) const {
    snapshot.current_pan = _current_pan;
    snapshot.current_tilt = _current_tilt;
    snapshot.target_pan = _target_pan;
    snapshot.target_tilt = _target_tilt;
    snapshot.is_moving = _is_moving;
    snapshot.failsafe_active = _failsafe_active;
    snapshot.estop_active = _estop_active;
    snapshot.obstruction_halt = _obstruction_halt;
}
