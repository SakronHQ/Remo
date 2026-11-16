/**
 * @file wifi_manager.h
 * @brief Wi-Fi Connection Manager with Auto-Reconnection & Exponential Backoff.
 *
 * Implements non-blocking station connection management for ESP32-S3,
 * dynamic RSSI tracking, and progressive backoff reconnection to prevent network flooding.
 */

#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include "firmware_config.h"

enum WiFiState : uint8_t {
    WIFI_STATE_DISCONNECTED = 0,
    WIFI_STATE_CONNECTING,
    WIFI_STATE_CONNECTED
};

class WiFiManager {
public:
    WiFiManager();

    /**
     * @brief Initialize Wi-Fi subsystem with target credentials.
     * @param ssid Target Access Point SSID.
     * @param password WPA2/WPA3 preshared key.
     */
    void begin(const char* ssid = WIFI_SSID, const char* password = WIFI_PASSWORD);

    /**
     * @brief Non-blocking state machine update. Call in network task loop.
     * @return true if currently connected with a valid IP address.
     */
    bool update();

    /**
     * @brief Check whether Wi-Fi station is actively connected.
     */
    bool isConnected() const;

    /**
     * @brief Get active received signal strength indicator (dBm).
     */
    int32_t getRSSI() const;

    /**
     * @brief Get local assigned IPv4 address string.
     */
    String getIP() const;

    /**
     * @brief Get configured SSID.
     */
    const char* getSSID() const { return _ssid; }

    /**
     * @brief Force an immediate reconnection attempt, resetting backoff timer.
     */
    void reconnect();

private:
    const char* _ssid;
    const char* _password;

    WiFiState _state;
    uint32_t _attempt_start_ms;
    uint32_t _last_attempt_ms;
    uint32_t _backoff_ms;
    int32_t  _last_rssi;

    void _startConnecting();
};
