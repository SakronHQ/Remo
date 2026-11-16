/**
 * @file pca9685_driver.h
 * @brief Lightweight, zero-dependency PCA9685 I2C driver using standard Arduino Wire.
 *
 * Designed according to Ponytail principles: no external bloat, direct 12-bit PWM
 * register control, built-in safety clamps, and hardware OE pin management.
 */

#pragma once

#include <Arduino.h>
#include <Wire.h>
#include "hardware_config.h"

class PCA9685Driver {
public:
    PCA9685Driver(uint8_t addr = PCA9685_I2C_ADDR, uint8_t oe_pin = PIN_PCA9685_OE)
        : _addr(addr), _oe_pin(oe_pin), _initialized(false) {}

    /**
     * @brief Initialize I2C bus, probe PCA9685, configure 50 Hz PWM and setup OE pin.
     * @return true if PCA9685 acknowledged and configured successfully.
     */
    bool begin(int sda = PIN_I2C_SDA, int scl = PIN_I2C_SCL, uint32_t freq = 100000) {
        // Setup hardware Output Enable (OE) pin: default HIGH (disabled for safety during boot)
        if (_oe_pin != 255) {
            pinMode(_oe_pin, OUTPUT);
            digitalWrite(_oe_pin, HIGH); // Disabled
        }

        // Initialize Wire on designated ESP32-S3 pins
        Wire.begin(sda, scl, freq);
        delay(20);

        // Probe address
        if (!probe()) {
            _initialized = false;
            return false;
        }

        // Reset PCA9685 Mode 1 register (all call, normal mode)
        writeRegister(PCA9685_MODE1, 0x00);
        delay(10);

        // Set PWM frequency to 50 Hz (Servo standard)
        // Oscillator = 25 MHz; Prescale = round(25MHz / (4096 * 50)) - 1 = 121
        setPWMFrequency50Hz();

        // Set Mode 2: Totem-pole (push-pull) outputs (OUTDRV = bit 2 = 0x04)
        writeRegister(PCA9685_MODE2, 0x04);
        delay(10);

        // Turn all PWM channels completely off before enabling outputs
        turnOffAll();

        // Enable outputs via hardware OE pin (active LOW)
        enableOutputs(true);

        _initialized = true;
        return true;
    }

    /**
     * @brief Check whether PCA9685 responds on the I2C bus.
     */
    bool probe() {
        Wire.beginTransmission(_addr);
        return (Wire.endTransmission() == 0);
    }

    /**
     * @brief Set hardware Output Enable (OE).
     * @param enable true = enable outputs (OE LOW); false = high-Z disable (OE HIGH)
     */
    void enableOutputs(bool enable) {
        if (_oe_pin != 255) {
            digitalWrite(_oe_pin, enable ? LOW : HIGH);
        }
    }

    /**
     * @brief Set raw 12-bit PWM on/off tick counts for a channel (0-15).
     * Masks high bytes with 0x1F to allow bit 4 (Full ON / Full OFF per PCA9685 datasheet)
     * while keeping reserved bits 7-5 cleared.
     */
    bool setPWM(uint8_t channel, uint16_t on, uint16_t off) {
        if (channel > 15) return false;

        Wire.beginTransmission(_addr);
        Wire.write(PCA9685_LED0_ON_L + 4 * channel);
        Wire.write((uint8_t)(on & 0xFF));
        Wire.write((uint8_t)((on >> 8) & 0x1F));
        Wire.write((uint8_t)(off & 0xFF));
        Wire.write((uint8_t)((off >> 8) & 0x1F));
        return (Wire.endTransmission() == 0);
    }

    /**
     * @brief Turn off PWM output for a specific channel (0% duty cycle, line held LOW).
     * Sets bit 4 of LEDn_OFF_H (value 4096 / 0x1000) per PCA9685 NXP hardware specification.
     */
    void turnOff(uint8_t channel) {
        setPWM(channel, 0, 4096);
    }

    /**
     * @brief Silence all 16 channels in a single broadcast transaction using ALL_LED registers.
     * Sets bit 4 of ALL_LED_OFF_H (0xFD) to 1.
     */
    void turnOffAll() {
        Wire.beginTransmission(_addr);
        Wire.write(0xFA); // ALL_LED_ON_L
        Wire.write(0x00); // ALL_LED_ON_L
        Wire.write(0x00); // ALL_LED_ON_H
        Wire.write(0x00); // ALL_LED_OFF_L
        Wire.write(0x10); // ALL_LED_OFF_H (Bit 4 = 1: Full OFF)
        Wire.endTransmission();
    }

    /**
     * @brief Set Pan servo angle (Channel 0, MG996R) with certified conservative bounds.
     * @param degrees Desired angle (clamped to 15.0 - 165.0 deg).
     * @return Applied clamped tick count.
     */
    uint16_t setPanAngle(float degrees) {
        float clamped = clampPanAngle(degrees);
        uint16_t ticks = panAngleToTicks(clamped);
        setPWM(SERVO_PAN_CHANNEL, 0, ticks);
        return ticks;
    }

    /**
     * @brief Set Tilt servo angle (Channel 1, MG90S) with certified conservative bounds.
     * @param degrees Desired angle (clamped to 60.0 - 135.0 deg).
     * @return Applied clamped tick count.
     */
    uint16_t setTiltAngle(float degrees) {
        float clamped = clampTiltAngle(degrees);
        uint16_t ticks = tiltAngleToTicks(clamped);
        setPWM(SERVO_TILT_CHANNEL, 0, ticks);
        return ticks;
    }

    /**
     * @brief Park both servos safely at home / neutral position (90.0 degrees).
     */
    void parkHome() {
        setPanAngle(SERVO_PAN_CENTER_DEG);
        setTiltAngle(SERVO_TILT_CENTER_DEG);
    }

    /**
     * @brief Read single 8-bit register from PCA9685 using repeated start.
     */
    uint8_t readRegister(uint8_t reg) {
        Wire.beginTransmission(_addr);
        Wire.write(reg);
        uint8_t err = Wire.endTransmission(false); // Repeated start
        if (err != 0) return 0xFF;
        Wire.requestFrom(_addr, (uint8_t)1);
        if (Wire.available()) {
            return Wire.read();
        }
        return 0xFF;
    }

    /**
     * @brief Write single 8-bit register to PCA9685.
     */
    void writeRegister(uint8_t reg, uint8_t val) {
        Wire.beginTransmission(_addr);
        Wire.write(reg);
        Wire.write(val);
        Wire.endTransmission();
    }

    bool isInitialized() const { return _initialized; }

private:
    uint8_t _addr;
    uint8_t _oe_pin;
    bool _initialized;

    /**
     * @brief Internal helper to set 50 Hz PWM prescaler.
     * PCA9685 requires SLEEP bit set in MODE1 before writing PRESCALE register.
     */
    void setPWMFrequency50Hz() {
        uint8_t oldmode = readRegister(PCA9685_MODE1);
        if (oldmode == 0xFF) oldmode = 0x00;
        uint8_t sleepmode = (oldmode & 0x7F) | 0x10; // set SLEEP bit (bit 4)
        writeRegister(PCA9685_MODE1, sleepmode);
        delayMicroseconds(500);
        writeRegister(PCA9685_PRESCALE, PCA9685_PRESCALE_VAL); // 121
        writeRegister(PCA9685_MODE1, oldmode & ~0x10); // clear SLEEP bit
        delay(5); // Wait 5ms for oscillator stabilization
        writeRegister(PCA9685_MODE1, (oldmode & ~0x10) | 0xA1); // Restart, auto-increment (bit 5), all-call (bit 0)
    }
};
