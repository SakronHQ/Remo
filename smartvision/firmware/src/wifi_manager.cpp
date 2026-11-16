/**
 * @file wifi_manager.cpp
 * @brief Implementation of Wi-Fi Connection Manager.
 */

#include "wifi_manager.h"

WiFiManager::WiFiManager()
    : _ssid(WIFI_SSID),
      _password(WIFI_PASSWORD),
      _state(WIFI_STATE_DISCONNECTED),
      _attempt_start_ms(0),
      _last_attempt_ms(0),
      _backoff_ms(WIFI_BACKOFF_MIN_MS),
      _last_rssi(-100) {
}

void WiFiManager::begin(const char* ssid, const char* password) {
    _ssid = ssid;
    _password = password;
    _state = WIFI_STATE_DISCONNECTED;
    _backoff_ms = WIFI_BACKOFF_MIN_MS;
    _last_attempt_ms = 0;

    // Configure station mode and disable low-power sleep for deterministic Wi-Fi packet latency
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);
    WiFi.setAutoReconnect(false); // We control reconnection with exponential backoff

    Serial.printf("[WiFi] Initialized station mode for SSID: %s\n", _ssid);
    _startConnecting();
}

void WiFiManager::_startConnecting() {
    Serial.printf("[WiFi] Connecting to '%s' (backoff: %lu ms)...\n", _ssid, _backoff_ms);
    WiFi.begin(_ssid, _password);
    _state = WIFI_STATE_CONNECTING;
    _attempt_start_ms = millis();
}

bool WiFiManager::update() {
    uint32_t now = millis();
    wl_status_t status = WiFi.status();

    switch (_state) {
        case WIFI_STATE_CONNECTING:
            if (status == WL_CONNECTED) {
                _state = WIFI_STATE_CONNECTED;
                _backoff_ms = WIFI_BACKOFF_MIN_MS; // Reset backoff on success
                _last_rssi = WiFi.RSSI();
                Serial.printf("[WiFi] Connected! IP: %s | RSSI: %ld dBm\n", 
                              WiFi.localIP().toString().c_str(), (long)_last_rssi);
                return true;
            }

            // Check if connection attempt timed out
            if (now - _attempt_start_ms >= WIFI_CONNECT_TIMEOUT_MS) {
                Serial.printf("[WiFi] Connection timeout (%lu ms). Disconnecting.\n", WIFI_CONNECT_TIMEOUT_MS);
                WiFi.disconnect(true);
                _state = WIFI_STATE_DISCONNECTED;
                _last_attempt_ms = now;

                // Exponential backoff doubling up to ceiling
                _backoff_ms = min(_backoff_ms * 2UL, (uint32_t)WIFI_BACKOFF_MAX_MS);
            }
            break;

        case WIFI_STATE_CONNECTED:
            if (status != WL_CONNECTED) {
                Serial.println("[WiFi] Lost connection! Entering backoff retry state...");
                WiFi.disconnect(true);
                _state = WIFI_STATE_DISCONNECTED;
                _last_attempt_ms = now;
                _last_rssi = -100;
                return false;
            }
            // Periodically refresh RSSI
            _last_rssi = WiFi.RSSI();
            return true;

        case WIFI_STATE_DISCONNECTED:
            if (now - _last_attempt_ms >= _backoff_ms) {
                _startConnecting();
            }
            break;
    }

    return (_state == WIFI_STATE_CONNECTED);
}

bool WiFiManager::isConnected() const {
    return (_state == WIFI_STATE_CONNECTED && WiFi.status() == WL_CONNECTED);
}

int32_t WiFiManager::getRSSI() const {
    return _last_rssi;
}

String WiFiManager::getIP() const {
    if (isConnected()) {
        return WiFi.localIP().toString();
    }
    return "0.0.0.0";
}

void WiFiManager::reconnect() {
    _backoff_ms = WIFI_BACKOFF_MIN_MS;
    WiFi.disconnect(true);
    _startConnecting();
}
