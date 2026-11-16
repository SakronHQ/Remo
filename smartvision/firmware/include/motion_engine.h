/**
 * @file motion_engine.h
 * @brief Discrete 50 Hz Motion Engine with Slew Interpolation & Safe Physical Boundaries.
 *
 * Implements smooth dual-axis servo positioning for MG996R (Pan, Ch 0) and MG90S (Tilt, Ch 1)
 * with mechanical clamping [15°-165° Pan, 60°-135° Tilt], speed factor scaling,
 * emergency freeze/safe-stop, and proximity collision interlocks.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"
#include "pca9685_driver.h"
#include "firmware_types.h"

class MotionEngine {
public:
    MotionEngine();

    /**
     * @brief Initialize I2C bus and PCA9685 driver; parks servos at home position.
     * @return true if PCA9685 responded and initialized successfully.
     */
    bool begin();

    /**
     * @brief Discrete-time slew interpolation loop step. Call at 50 Hz.
     * @param dt_s Delta time in seconds since previous update (~0.020s for 50 Hz).
     */
    void update(float dt_s);

    /**
     * @brief Command absolute target pan and tilt angles with physical boundary clamping.
     * @param pan Desired pan angle in degrees [15.0, 165.0].
     * @param tilt Desired tilt angle in degrees [60.0, 135.0].
     * @param speed_factor Normalized velocity factor [0.1, 1.0] -> 10 to 120 deg/s.
     * @param smooth Enable discrete slew rate interpolation.
     */
    void setTarget(float pan, float tilt, float speed_factor = 0.5f, bool smooth = true);

    /**
     * @brief Command relative jog adjustment.
     * @param delta_pan Relative pan change in degrees.
     * @param delta_tilt Relative tilt change in degrees.
     * @param speed_factor Normalized velocity factor [0.1, 1.0].
     */
    void jog(float delta_pan, float delta_tilt, float speed_factor = 0.5f);

    /**
     * @brief Smoothly slew both servos to calibrated neutral center (90.0°, 90.0°).
     * @param speed_factor Normalized velocity factor.
     */
    void center(float speed_factor = 0.4f);

    /**
     * @brief Instantly freeze servos at current positions with active holding torque.
     */
    void freeze();

    /**
     * @brief Emergency stop: instantly freeze and optionally depower servo coils.
     * @param release_pwm True to silence PWM pulses / disable output enable (OE).
     */
    void estop(bool release_pwm = false);

    /**
     * @brief Enable or disable PCA9685 hardware output enable (OE).
     */
    void enableOutputs(bool enable);

    /**
     * @brief Depower both servo channels (0% duty cycle, high-Z / no torque).
     */
    void releasePWM();

    /**
     * @brief Engage or disengage failsafe mode.
     */
    void setFailsafe(bool active);

    /**
     * @brief Engage or disengage proximity obstruction halt.
     */
    void setObstructionHalt(bool halt);

    /**
     * @brief Resume normal operation after failsafe or estop is cleared.
     */
    void resumeNormal();

    /**
     * @brief Populate a thread-safe snapshot of current servo angles and state.
     */
    void getSnapshot(MotionSnapshot_t& snapshot) const;

    float getCurrentPan() const { return _current_pan; }
    float getCurrentTilt() const { return _current_tilt; }
    float getTargetPan() const { return _target_pan; }
    float getTargetTilt() const { return _target_tilt; }
    bool  isMoving() const { return _is_moving; }
    bool  isFailsafeActive() const { return _failsafe_active; }
    bool  isEstopActive() const { return _estop_active; }

private:
    PCA9685Driver _driver;

    float _current_pan;
    float _current_tilt;
    float _target_pan;
    float _target_tilt;

    float _slew_rate_deg_s;
    bool  _smooth;
    bool  _is_moving;

    bool  _failsafe_active;
    bool  _estop_active;
    bool  _obstruction_halt;
    bool  _pwm_released;

    void _applyAnglesToHardware();
};
