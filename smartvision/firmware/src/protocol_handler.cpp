/**
 * @file protocol_handler.cpp
 * @brief Implementation of SmartVision Protocol Handler.
 */

#include "protocol_handler.h"
#include <cmath>

ProtocolHandler::ProtocolHandler()
    : _rx_seq(0),
      _tx_seq(1),
      _epoch_offset_ms(0),
      _epoch_synced(false),
      _onMotion(nullptr),
      _onBuzzer(nullptr),
      _onPing(nullptr),
      _onFeed(nullptr) {
}

bool ProtocolHandler::handleInboundPayload(const char* json_str, size_t length) {
    if (json_str == nullptr || length == 0) return false;

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, json_str, length);
    if (err) {
        Serial.printf("[Protocol] Deserialization error: %s\n", err.c_str());
        return false;
    }

    // Outer envelope validation
    const char* type = doc["type"];
    if (type == nullptr) {
        Serial.println("[Protocol] Rejected: missing 'type' field.");
        return false;
    }

    JsonObject payload;
    if (doc["payload"].is<JsonObject>()) {
        payload = doc["payload"].as<JsonObject>();
    } else {
        payload = doc["payload"].to<JsonObject>();
    }

    const char* corr_id = doc["corr_id"];
    uint64_t timestamp = doc["timestamp"] | 0ULL;
    if (timestamp > 1000000000000ULL) {
        _epoch_offset_ms = timestamp - (uint64_t)millis();
        _epoch_synced = true;
    }

    _rx_seq = doc["seq"] | (_rx_seq + 1);

    // Feed the 800ms communication watchdog on any valid envelope
    if (_onFeed) {
        _onFeed();
    }

    // Command Dispatching
    if (strcmp(type, "cmd.servo.move") == 0 || strcmp(type, "cmd.move") == 0) {
        _dispatchServoMove(payload, corr_id);
        return true;
    } 
    else if (strcmp(type, "cmd.jog") == 0 || strcmp(type, "cmd.servo.jog") == 0) {
        _dispatchJog(payload, corr_id);
        return true;
    } 
    else if (strcmp(type, "cmd.servo.center") == 0 || strcmp(type, "cmd.center") == 0) {
        _dispatchCenter(payload, corr_id);
        return true;
    } 
    else if (strcmp(type, "cmd.estop") == 0) {
        // cmd.estop defaults to immediate hardware safe-stop and PCA9685 output disable
        if (!_onMotion) return true;
        MotionCommand_t cmd;
        const char* action = payload["action"] | "";
        if (strcmp(action, "resume") == 0 || strcmp(action, "clear") == 0 || strcmp(action, "reset") == 0) {
            cmd.type = MOTION_CMD_RESUME;
            cmd.release_pwm = false;
        } else {
            cmd.type = MOTION_CMD_ESTOP;
            cmd.release_pwm = true;
        }
        _onMotion(cmd);
        return true;
    }
    else if (strcmp(type, "sys.safestop") == 0) {
        _dispatchEstop(payload, corr_id);
        return true;
    } 
    else if (strcmp(type, "cmd.buzzer") == 0) {
        _dispatchBuzzer(payload, corr_id);
        return true;
    } 
    else if (strcmp(type, "sys.ping") == 0 || strcmp(type, "ping") == 0) {
        _dispatchPing(payload, corr_id, timestamp);
        return true;
    }

    Serial.printf("[Protocol] Unhandled message type: %s\n", type);
    return false;
}

void ProtocolHandler::_dispatchServoMove(JsonObject& payload, const char* corr_id) {
    if (!_onMotion) return;

    MotionCommand_t cmd;
    const char* mode = payload["mode"] | "absolute";

    if (strcmp(mode, "relative") == 0) {
        cmd.type = MOTION_CMD_RELATIVE;
    } else {
        cmd.type = MOTION_CMD_ABSOLUTE;
    }

    cmd.pan = !payload["pan"].isNull() ? payload["pan"].as<float>() : (float)SERVO_PAN_CENTER_DEG;
    cmd.tilt = !payload["tilt"].isNull() ? payload["tilt"].as<float>() : (float)SERVO_TILT_CENTER_DEG;
    cmd.speed = !payload["speed"].isNull() ? payload["speed"].as<float>() : 0.5f;
    cmd.smooth = payload["smooth"] | true;
    cmd.release_pwm = false;

    _onMotion(cmd);
}

void ProtocolHandler::_dispatchJog(JsonObject& payload, const char* corr_id) {
    if (!_onMotion) return;

    MotionCommand_t cmd;
    cmd.type = MOTION_CMD_RELATIVE;
    if (!payload["delta_pan"].isNull()) {
        cmd.pan = payload["delta_pan"].as<float>();
    } else if (!payload["pan"].isNull()) {
        cmd.pan = payload["pan"].as<float>();
    } else {
        cmd.pan = 0.0f;
    }

    if (!payload["delta_tilt"].isNull()) {
        cmd.tilt = payload["delta_tilt"].as<float>();
    } else if (!payload["tilt"].isNull()) {
        cmd.tilt = payload["tilt"].as<float>();
    } else {
        cmd.tilt = 0.0f;
    }

    cmd.speed = !payload["speed"].isNull() ? payload["speed"].as<float>() : 0.5f;
    cmd.smooth = true;
    cmd.release_pwm = false;

    _onMotion(cmd);
}

void ProtocolHandler::_dispatchCenter(JsonObject& payload, const char* corr_id) {
    if (!_onMotion) return;

    MotionCommand_t cmd;
    cmd.type = MOTION_CMD_CENTER;
    cmd.pan = SERVO_PAN_CENTER_DEG;
    cmd.tilt = SERVO_TILT_CENTER_DEG;
    cmd.speed = !payload["speed"].isNull() ? payload["speed"].as<float>() : 0.4f;
    cmd.smooth = true;
    cmd.release_pwm = false;

    _onMotion(cmd);
}

void ProtocolHandler::_dispatchEstop(JsonObject& payload, const char* corr_id) {
    if (!_onMotion) return;

    MotionCommand_t cmd;
    const char* action = payload["action"] | "freeze";

    if (strcmp(action, "resume") == 0 || strcmp(action, "clear") == 0 || strcmp(action, "reset") == 0) {
        cmd.type = MOTION_CMD_RESUME;
        cmd.release_pwm = false;
    } else if (strcmp(action, "center") == 0) {
        cmd.type = MOTION_CMD_CENTER;
        cmd.pan = SERVO_PAN_CENTER_DEG;
        cmd.tilt = SERVO_TILT_CENTER_DEG;
        cmd.speed = 0.4f;
        cmd.smooth = true;
        cmd.release_pwm = false;
    } else if (strcmp(action, "release_pwm") == 0 || (payload["release_pwm"] | false)) {
        cmd.type = MOTION_CMD_ESTOP;
        cmd.release_pwm = true;
    } else {
        cmd.type = MOTION_CMD_FREEZE;
        cmd.release_pwm = false;
    }

    _onMotion(cmd);
}

void ProtocolHandler::_dispatchBuzzer(JsonObject& payload, const char* corr_id) {
    if (!_onBuzzer) return;

    BuzzerCommand_t cmd;
    const char* act = payload["action"] | "beep";

    if (strcasecmp(act, "chirp") == 0) cmd.action = BUZZER_ACT_CHIRP;
    else if (strcasecmp(act, "alarm") == 0) cmd.action = BUZZER_ACT_ALARM;
    else if (strcasecmp(act, "pulse") == 0) cmd.action = BUZZER_ACT_PULSE;
    else if (strcasecmp(act, "mute") == 0 || strcasecmp(act, "off") == 0) cmd.action = BUZZER_ACT_MUTE;
    else cmd.action = BUZZER_ACT_BEEP;

    cmd.duration_ms = payload["duration_ms"] | (uint16_t)BUZZER_DEFAULT_BEEP_MS;
    cmd.count = payload["count"] | (uint8_t)3;
    cmd.interval_ms = payload["interval_ms"] | (uint16_t)100;

    _onBuzzer(cmd);
}

void ProtocolHandler::_dispatchPing(JsonObject& payload, const char* corr_id, uint64_t timestamp) {
    if (_onPing) {
        _onPing(timestamp, corr_id);
    }
}

bool ProtocolHandler::serializeSensorsTelemetry(const SensorSnapshot_t& sensors, 
                                               const MotionSnapshot_t& motion, 
                                               const SystemSnapshot_t& system, 
                                               String& out_json) {
    JsonDocument doc;

    doc["type"] = "telem.sensors";
    doc["timestamp"] = nowEpochMs();
    doc["sender"] = "esp32";
    doc["seq"] = _tx_seq++;
    doc["corr_id"] = nullptr;

    JsonObject payload = doc["payload"].to<JsonObject>();

    // 1. Sonar
    JsonObject sonar = payload["sonar"].to<JsonObject>();
    sonar["distance_cm"] = serialized(String(sensors.sonar_distance_cm, 1));
    sonar["valid"] = sensors.sonar_valid;
    sonar["status"] = sensors.sonar_status;

    // 2. PIR
    JsonObject pir = payload["pir"].to<JsonObject>();
    pir["motion_detected"] = sensors.pir_motion;
    pir["trigger_count"] = sensors.pir_trigger_count;
    pir["last_trigger_ms"] = sensors.pir_last_trigger_ms;

    // 3. Servos
    JsonObject servos = payload["servos"].to<JsonObject>();
    servos["pan_angle"] = serialized(String(motion.current_pan, 1));
    servos["tilt_angle"] = serialized(String(motion.current_tilt, 1));
    servos["pan_target"] = serialized(String(motion.target_pan, 1));
    servos["tilt_target"] = serialized(String(motion.target_tilt, 1));
    servos["is_moving"] = motion.is_moving;

    // 4. Buzzer
    JsonObject buzzer = payload["buzzer"].to<JsonObject>();
    buzzer["active"] = sensors.buzzer_active;
    buzzer["pattern"] = sensors.buzzer_pattern;

    // 5. System
    JsonObject sys = payload["system"].to<JsonObject>();
    sys["uptime_ms"] = system.uptime_ms;
    sys["rssi_dbm"] = system.rssi_dbm;
    sys["free_heap_bytes"] = system.free_heap_bytes;
    sys["psram_free_bytes"] = system.psram_free_bytes;
    sys["cpu_temp_c"] = serialized(String(system.cpu_temp_c, 1));
    sys["failsafe_active"] = system.failsafe_active;

    out_json = "";
    serializeJson(doc, out_json);
    return true;
}

bool ProtocolHandler::serializeStatusTelemetry(const MotionSnapshot_t& motion, 
                                              const SystemSnapshot_t& system, 
                                              String& out_json) {
    JsonDocument doc;

    doc["type"] = "telem.status";
    doc["timestamp"] = nowEpochMs();
    doc["sender"] = "esp32";
    doc["seq"] = _tx_seq++;
    doc["corr_id"] = nullptr;

    JsonObject payload = doc["payload"].to<JsonObject>();
    payload["node"] = "esp32";
    payload["wifi_connected"] = system.wifi_connected;
    payload["ws_connected"] = system.ws_connected;
    payload["ip"] = system.ip_addr;
    payload["rssi_dbm"] = system.rssi_dbm;
    payload["failsafe_active"] = system.failsafe_active;
    payload["estop_active"] = system.estop_active;

    JsonObject servos = payload["servos"].to<JsonObject>();
    servos["pan_angle"] = serialized(String(motion.current_pan, 1));
    servos["tilt_angle"] = serialized(String(motion.current_tilt, 1));

    payload["uptime_ms"] = system.uptime_ms;

    out_json = "";
    serializeJson(doc, out_json);
    return true;
}

bool ProtocolHandler::serializePong(uint64_t echo_timestamp, const char* corr_id, String& out_json) {
    JsonDocument doc;

    uint64_t now_ms = nowEpochMs();
    doc["type"] = "sys.pong";
    doc["timestamp"] = now_ms;
    doc["sender"] = "esp32";
    doc["seq"] = _tx_seq++;
    if (corr_id && strlen(corr_id) > 0) {
        doc["corr_id"] = corr_id;
    } else {
        doc["corr_id"] = nullptr;
    }

    JsonObject payload = doc["payload"].to<JsonObject>();
    payload["echo_timestamp"] = echo_timestamp;
    payload["rtt_ms"] = (now_ms >= echo_timestamp && echo_timestamp > 0) ? (uint32_t)(now_ms - echo_timestamp) : 0;

    out_json = "";
    serializeJson(doc, out_json);
    return true;
}

bool ProtocolHandler::serializeAlert(const char* event_type, 
                                    const char* severity, 
                                    const char* message, 
                                    const SensorSnapshot_t& sensors, 
                                    const MotionSnapshot_t& motion, 
                                    String& out_json) {
    JsonDocument doc;

    doc["type"] = "alert.event";
    doc["timestamp"] = nowEpochMs();
    doc["sender"] = "esp32";
    doc["seq"] = _tx_seq++;
    doc["corr_id"] = nullptr;

    JsonObject payload = doc["payload"].to<JsonObject>();
    char event_id[32];
    snprintf(event_id, sizeof(event_id), "evt_%lu", millis());
    payload["event_id"] = event_id;
    payload["event_type"] = event_type ? event_type : "generic_alert";
    payload["severity"] = severity ? severity : "warning";
    payload["source"] = "esp32";
    payload["message"] = message ? message : "Alert event triggered";

    JsonObject snapshot = payload["telemetry_snapshot"].to<JsonObject>();
    snapshot["distance_cm"] = serialized(String(sensors.sonar_distance_cm, 1));
    snapshot["threshold_cm"] = serialized(String(PROXIMITY_OBSTRUCTION_CM, 1));
    snapshot["pan_angle"] = serialized(String(motion.current_pan, 1));
    snapshot["tilt_angle"] = serialized(String(motion.current_tilt, 1));

    payload["action_taken"] = motion.failsafe_active ? "failsafe_freeze" : "monitored";
    payload["buzzer_activated"] = sensors.buzzer_active;

    out_json = "";
    serializeJson(doc, out_json);
    return true;
}
