/**
 * @file websocket_client.h
 * @brief Full-Duplex WebSocket Client for FastAPI Backend Communication (`/ws/device`).
 *
 * Wraps Markus Sattler's WebSocketsClient library with thread-safe hooks,
 * automatic reconnect, and event callbacks.
 */

#pragma once

#include <Arduino.h>
#include <WebSocketsClient.h>
#include <functional>
#include "firmware_config.h"

typedef std::function<void(const char* payload, size_t length)> WSMessageCallback;
typedef std::function<void(bool connected)> WSConnectionCallback;

class SmartVisionWSClient {
public:
    SmartVisionWSClient();

    /**
     * @brief Configure WebSocket connection endpoints.
     * @param host Backend hostname or IP address.
     * @param port Backend HTTP/WebSocket port (e.g. 8000).
     * @param path Target WebSocket route (e.g. "/ws/device").
     */
    void begin(const char* host = BACKEND_HOST, 
               uint16_t port = BACKEND_PORT, 
               const char* path = BACKEND_WS_PATH);

    /**
     * @brief Non-blocking event pump. Must be called repeatedly in the network task.
     */
    void loop();

    /**
     * @brief Check whether WebSocket connection is actively established.
     */
    bool isConnected() const;

    /**
     * @brief Send raw null-terminated text payload to backend.
     * @param text JSON string.
     * @return true if enqueued/sent successfully.
     */
    bool sendTXT(const char* text);

    /**
     * @brief Send Arduino String object to backend.
     */
    bool sendTXT(const String& text);

    /**
     * @brief Register callback for inbound WebSocket text frames.
     */
    void onMessage(WSMessageCallback cb) { _onMessage = cb; }

    /**
     * @brief Register callback for connection state changes.
     */
    void onConnectionChange(WSConnectionCallback cb) { _onConnection = cb; }

    /**
     * @brief Disconnect and initiate reconnect.
     */
    void reconnect();

private:
    WebSocketsClient _ws;
    const char* _host;
    uint16_t _port;
    const char* _path;

    bool _connected;
    WSMessageCallback _onMessage;
    WSConnectionCallback _onConnection;

    void _handleWSEvent(WStype_t type, uint8_t* payload, size_t length);
    static void _staticWSEvent(WStype_t type, uint8_t* payload, size_t length);
    static SmartVisionWSClient* _instance;
};
