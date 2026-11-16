/**
 * @file websocket_client.cpp
 * @brief Implementation of SmartVision WebSocket Client.
 */

#include "websocket_client.h"

SmartVisionWSClient* SmartVisionWSClient::_instance = nullptr;

SmartVisionWSClient::SmartVisionWSClient()
    : _host(BACKEND_HOST),
      _port(BACKEND_PORT),
      _path(BACKEND_WS_PATH),
      _connected(false),
      _onMessage(nullptr),
      _onConnection(nullptr) {
    _instance = this;
}

void SmartVisionWSClient::begin(const char* host, uint16_t port, const char* path) {
    _host = host;
    _port = port;
    _path = path;
    _connected = false;

    Serial.printf("[WebSocket] Connecting to ws://%s:%u%s\n", _host, _port, _path);
    _ws.begin(_host, _port, _path);
    _ws.onEvent(_staticWSEvent);
    _ws.setReconnectInterval(WS_RECONNECT_INTERVAL_MS);
    _ws.enableHeartbeat(5000, 3000, 2); // 5s ping, 3s timeout, 2 retries
}

void SmartVisionWSClient::loop() {
    _ws.loop();
}

bool SmartVisionWSClient::isConnected() const {
    return _connected;
}

bool SmartVisionWSClient::sendTXT(const char* text) {
    if (!_connected || text == nullptr) return false;
    return _ws.sendTXT(text);
}

bool SmartVisionWSClient::sendTXT(const String& text) {
    if (!_connected) return false;
    return _ws.sendTXT(text.c_str());
}

void SmartVisionWSClient::reconnect() {
    _connected = false;
    _ws.disconnect();
}

void SmartVisionWSClient::_staticWSEvent(WStype_t type, uint8_t* payload, size_t length) {
    if (_instance) {
        _instance->_handleWSEvent(type, payload, length);
    }
}

void SmartVisionWSClient::_handleWSEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            if (_connected) {
                _connected = false;
                Serial.println("[WebSocket] Disconnected from server.");
                if (_onConnection) _onConnection(false);
            }
            break;

        case WStype_CONNECTED:
            _connected = true;
            Serial.printf("[WebSocket] Connected to: %s\n", (payload ? (char*)payload : ""));
            if (_onConnection) _onConnection(true);
            break;

        case WStype_TEXT:
            if (_onMessage && payload && length > 0) {
                _onMessage((const char*)payload, length);
            }
            break;

        case WStype_ERROR:
            Serial.printf("[WebSocket] Error occurred: %s\n", (payload ? (char*)payload : "unknown"));
            break;

        case WStype_PING:
        case WStype_PONG:
            // Handled automatically by RFC6455 framing
            break;

        default:
            break;
    }
}
