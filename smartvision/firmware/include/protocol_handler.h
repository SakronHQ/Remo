/**
 * @file protocol_handler.h
 * @brief SmartVision Protocol Ingestion, Command Dispatcher, and Telemetry Serializer.
 *
 * Implements strict schema validation and serialization matching `docs/protocol.md`.
 * Handles inbound commands (`cmd.servo.move`, `cmd.move`, `cmd.jog`, `cmd.servo.center`,
 * `cmd.center`, `cmd.estop`, `sys.safestop`, `cmd.buzzer`, `sys.ping`) and serializes
 * 10 Hz `telem.sensors`, `telem.status`, `sys.pong`, and `alert.event` envelopes.
 */

#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <functional>
#include "firmware_types.h"
#include "hardware_config.h"

// Callback type definitions
typedef std::function<void(const MotionCommand_t& cmd)> MotionCmdCallback;
typedef std::function<void(const BuzzerCommand_t& cmd)> BuzzerCmdCallback;
typedef std::function<void(uint64_t echo_timestamp, const char* corr_id)> PingCallback;
typedef std::function<void()> WatchdogFeedCallback;

class ProtocolHandler {
public:
    ProtocolHandler();

    /**
     * @brief Parse incoming JSON payload and dispatch validated commands.
     * @param json_str Inbound WebSocket text payload.
     * @param length Payload length in bytes.
     * @return true if payload conforms to schema and command was dispatched.
     */
    bool handleInboundPayload(const char* json_str, size_t length);

    // Command dispatch callback setters
    void onMotionCommand(MotionCmdCallback cb) { _onMotion = cb; }
    void onBuzzerCommand(BuzzerCmdCallback cb) { _onBuzzer = cb; }
    void onPingReceived(PingCallback cb) { _onPing = cb; }
    void onWatchdogFeed(WatchdogFeedCallback cb) { _onFeed = cb; }

    /**
     * @brief Serialize 10 Hz `telem.sensors` message conforming to docs/protocol.md.
     */
    bool serializeSensorsTelemetry(const SensorSnapshot_t& sensors, 
                                   const MotionSnapshot_t& motion, 
                                   const SystemSnapshot_t& system, 
                                   String& out_json);

    /**
     * @brief Serialize 1 Hz `telem.status` / `sys.status` system health message.
     */
    bool serializeStatusTelemetry(const MotionSnapshot_t& motion, 
                                  const SystemSnapshot_t& system, 
                                  String& out_json);

    /**
     * @brief Serialize `sys.pong` response to a received `sys.ping`.
     */
    bool serializePong(uint64_t echo_timestamp, const char* corr_id, String& out_json);

    /**
     * @brief Serialize emergency `alert.event` message.
     */
    bool serializeAlert(const char* event_type, 
                        const char* severity, 
                        const char* message, 
                        const SensorSnapshot_t& sensors, 
                        const MotionSnapshot_t& motion, 
                        String& out_json);

    uint32_t getRxSequence() const { return _rx_seq; }
    uint32_t getTxSequence() const { return _tx_seq; }
    uint64_t nowEpochMs() const {
        return _epoch_synced ? ((uint64_t)millis() + _epoch_offset_ms) : (uint64_t)millis();
    }

private:
    uint32_t _rx_seq;
    uint32_t _tx_seq;
    uint64_t _epoch_offset_ms;
    bool     _epoch_synced;

    MotionCmdCallback    _onMotion;
    BuzzerCmdCallback    _onBuzzer;
    PingCallback         _onPing;
    WatchdogFeedCallback _onFeed;

    void _dispatchServoMove(JsonObject& payload, const char* corr_id);
    void _dispatchJog(JsonObject& payload, const char* corr_id);
    void _dispatchCenter(JsonObject& payload, const char* corr_id);
    void _dispatchPatrol(JsonObject& payload, const char* corr_id);
    void _dispatchEstop(JsonObject& payload, const char* corr_id);
    void _dispatchBuzzer(JsonObject& payload, const char* corr_id);
    void _dispatchPing(JsonObject& payload, const char* corr_id, uint64_t timestamp);
};
