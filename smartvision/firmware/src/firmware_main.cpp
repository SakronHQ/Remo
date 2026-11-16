/**
 * @file firmware_main.cpp
 * @brief SmartVision Modular Dual-Core ESP32-S3 Firmware Entrypoint.
 *
 * Implements complete Phase 3 firmware specification:
 * - FreeRTOS Dual-Core concurrency:
 *   - Core 0: Wi-Fi stack, WebSocket client, 800ms Watchdog Supervisor.
 *   - Core 1: Sensor acquisition (HC-SR04, HC-SR501), Buzzer state machine, PCA9685 motion engine.
 * - 800ms Communication Watchdog with Safe-Stop Failsafe (FAILSAFE_ACTIVE).
 * - Full JSON Protocol framing matching `docs/protocol.md` (10 Hz telem.sensors, 1 Hz telem.status).
 * - Inbound command dispatching (cmd.servo.move, cmd.move, cmd.jog, cmd.servo.center, cmd.center, cmd.estop, sys.safestop, cmd.buzzer, sys.ping).
 */

#include <Arduino.h>
#include "hardware_config.h"
#include "firmware_config.h"
#include "firmware_types.h"
#include "wifi_manager.h"
#include "websocket_client.h"
#include "protocol_handler.h"
#include "motion_engine.h"
#include "sensor_engine.h"

// ============================================================================
// Global Subsystem Instances
// ============================================================================
static WiFiManager         g_wifiManager;
static SmartVisionWSClient g_wsClient;
static ProtocolHandler     g_protocolHandler;
static MotionEngine        g_motionEngine;
static SensorEngine        g_sensorEngine;

// ============================================================================
// FreeRTOS Synchronization Primitives & Queues
// ============================================================================
static QueueHandle_t       g_servoCmdQueue  = nullptr;
static QueueHandle_t       g_buzzerCmdQueue = nullptr;
static QueueHandle_t       g_outboxQueue    = nullptr;
static SemaphoreHandle_t   g_stateMutex     = nullptr;

// Watchdog and Communication State
static volatile uint32_t   g_last_rx_ms          = 0;
static volatile bool       g_failsafe_active     = false;
static volatile bool       g_ws_was_connected    = false;
static uint32_t            g_last_failsafe_alert = 0;

// ============================================================================
// Helper: Enqueue Outgoing JSON Message
// ============================================================================
static void enqueueOutboxMessage(const String& json_str) {
    if (g_outboxQueue == nullptr) return;

    // Discard routine outbound telemetry when disconnected to prevent stale queue accumulation
    if (!g_wsClient.isConnected()) {
        return;
    }

    OutboxMessage_t msg;
    size_t len = min(json_str.length(), (unsigned int)(sizeof(msg.json) - 1));
    memcpy(msg.json, json_str.c_str(), len);
    msg.json[len] = '\0';

    // Non-blocking queue send; drops message if outbox is full
    xQueueSend(g_outboxQueue, &msg, 0);
}

// ============================================================================
// CORE 0: Network Management Task (Wi-Fi + WebSocket)
// ============================================================================
static void Task_Network(void* pvParameters) {
    Serial.printf("[Task_Net] Running on Core %d, Priority %d\n", xPortGetCoreID(), uxTaskPriorityGet(NULL));

    // Initialize Wi-Fi
    g_wifiManager.begin(WIFI_SSID, WIFI_PASSWORD);

    // Initialize WebSocket
    g_wsClient.begin(BACKEND_HOST, BACKEND_PORT, BACKEND_WS_PATH);

    // Bind WebSocket text frame callback to ProtocolHandler
    g_wsClient.onMessage([](const char* payload, size_t length) {
        g_protocolHandler.handleInboundPayload(payload, length);
    });

    g_wsClient.onConnectionChange([](bool connected) {
        if (connected) {
            Serial.println("[Task_Net] WebSocket link established with backend!");
        } else {
            Serial.println("[Task_Net] WebSocket link dropped.");
        }
    });

    for (;;) {
        // 1. Maintain Wi-Fi station link with auto-reconnect
        bool wifi_ok = g_wifiManager.update();

        // 2. Pump WebSocket frames if network is alive
        if (wifi_ok) {
            g_wsClient.loop();

            // 3. Drain and transmit queued outbound telemetry messages
            if (g_wsClient.isConnected()) {
                OutboxMessage_t out_msg;
                while (xQueueReceive(g_outboxQueue, &out_msg, 0) == pdPASS) {
                    g_wsClient.sendTXT(out_msg.json);
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(5)); // Yield 5ms
    }
}

// ============================================================================
// CORE 0: Watchdog & Safe-Stop Supervisor Task (800ms Watchdog)
// ============================================================================
static void Task_WatchdogSupervisor(void* pvParameters) {
    Serial.printf("[Task_Watchdog] Running on Core %d, Priority %d (Watchdog: %lu ms)\n", 
                  xPortGetCoreID(), uxTaskPriorityGet(NULL), (unsigned long)WATCHDOG_TIMEOUT_MS);

    for (;;) {
        uint32_t now = millis();
        bool ws_now_connected = g_wsClient.isConnected();

        if (ws_now_connected) {
            if (!g_ws_was_connected) {
                // Connection just transitioned to active
                g_ws_was_connected = true;
                g_last_rx_ms = now;
                g_failsafe_active = false;
                MotionCommand_t resCmd = { MOTION_CMD_RESUME, 0.0f, 0.0f, 0.0f, false, false };
                xQueueSend(g_servoCmdQueue, &resCmd, 0);
                Serial.println("[Watchdog] Connected. Watchdog armed.");
            }

            // Check communication freshness
            uint32_t elapsed = now - g_last_rx_ms;
            if (elapsed > WATCHDOG_TIMEOUT_MS) {
                if (!g_failsafe_active) {
                    g_failsafe_active = true;
                    g_last_failsafe_alert = now;
                    Serial.printf("[Watchdog] FAILSAFE ENGAGED! Elapsed: %lu ms (> %lu ms threshold). Servos frozen.\n", 
                                  (unsigned long)elapsed, (unsigned long)WATCHDOG_TIMEOUT_MS);

                    // 1. Post freeze command to Core 1 motion task (queue-based, thread-safe across cores)
                    MotionCommand_t freezeCmd = { MOTION_CMD_FREEZE, 0.0f, 0.0f, 0.0f, false, false };
                    xQueueSend(g_servoCmdQueue, &freezeCmd, 0);

                    // 2. Post alert chirp to Core 1 buzzer queue
                    BuzzerCommand_t bcmd = { BUZZER_ACT_CHIRP, 70, 2, 50 };
                    xQueueSend(g_buzzerCmdQueue, &bcmd, 0);

                    // 3. Thread-safe snapshot & alert notification
                    SensorSnapshot_t s_snap;
                    MotionSnapshot_t m_snap;
                    if (xSemaphoreTake(g_stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                        g_sensorEngine.getSnapshot(s_snap);
                        g_motionEngine.getSnapshot(m_snap);
                        xSemaphoreGive(g_stateMutex);
                    }
                    String alert_json;
                    g_protocolHandler.serializeAlert("ws_disconnect", "critical", 
                        "800ms communication watchdog timeout elapsed without heartbeat.", 
                        s_snap, m_snap, alert_json);
                    enqueueOutboxMessage(alert_json);
                } else {
                    // Periodic reminder chirp while failsafe remains active
                    if (now - g_last_failsafe_alert >= FAILSAFE_ALERT_INTERVAL_MS) {
                        g_last_failsafe_alert = now;
                        BuzzerCommand_t bcmd = { BUZZER_ACT_CHIRP, 70, 2, 50 };
                        xQueueSend(g_buzzerCmdQueue, &bcmd, 0);
                    }
                }
            }
        } else {
            // Disconnected
            if (g_ws_was_connected) {
                g_ws_was_connected = false;
                g_failsafe_active = true;
                MotionCommand_t freezeCmd = { MOTION_CMD_FREEZE, 0.0f, 0.0f, 0.0f, false, false };
                xQueueSend(g_servoCmdQueue, &freezeCmd, 0);
                BuzzerCommand_t bcmd = { BUZZER_ACT_CHIRP, 70, 2, 50 };
                xQueueSend(g_buzzerCmdQueue, &bcmd, 0);
                Serial.println("[Watchdog] WebSocket dropped. Servos frozen in safe-stop.");
            }
        }

        vTaskDelay(pdMS_TO_TICKS(50)); // Check every 50 ms
    }
}

// ============================================================================
// CORE 1: Hard Real-Time Motion Control Task (50 Hz Discrete Slew)
// ============================================================================
static void Task_Motion(void* pvParameters) {
    Serial.printf("[Task_Motion] Running on Core %d, Priority %d (50 Hz / 20ms)\n", 
                  xPortGetCoreID(), uxTaskPriorityGet(NULL));

    // Initialize PCA9685 driver and set servos to home position
    if (!g_motionEngine.begin()) {
        Serial.println("[Task_Motion] FATAL: PCA9685 driver initialization failed!");
    }

    const float dt_s = (float)MOTION_UPDATE_INTERVAL_MS / 1000.0f; // 0.020s
    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(MOTION_UPDATE_INTERVAL_MS);

    for (;;) {
        // 1. Process any pending inbound servo commands from Core 0
        MotionCommand_t cmd;
        while (xQueueReceive(g_servoCmdQueue, &cmd, 0) == pdPASS) {
            switch (cmd.type) {
                case MOTION_CMD_ABSOLUTE:
                    g_motionEngine.setTarget(cmd.pan, cmd.tilt, cmd.speed, cmd.smooth);
                    break;
                case MOTION_CMD_RELATIVE:
                    g_motionEngine.jog(cmd.pan, cmd.tilt, cmd.speed);
                    break;
                case MOTION_CMD_CENTER:
                    g_motionEngine.center(cmd.speed);
                    break;
                case MOTION_CMD_FREEZE:
                    g_motionEngine.setFailsafe(true);
                    g_motionEngine.freeze();
                    if (cmd.release_pwm) {
                        g_motionEngine.releasePWM();
                    }
                    break;
                case MOTION_CMD_ESTOP:
                    g_motionEngine.estop(cmd.release_pwm);
                    break;
                case MOTION_CMD_RELEASE_PWM:
                    g_motionEngine.releasePWM();
                    break;
                case MOTION_CMD_RESUME:
                    g_motionEngine.setFailsafe(false);
                    g_motionEngine.resumeNormal();
                    break;
            }
        }

        // 2. Check ultrasonic proximity safety interlock (< 20 cm halts motion)
        g_motionEngine.setObstructionHalt(g_sensorEngine.isProximityObstruction());

        // 3. Step discrete-time slew interpolation and apply PCA9685 12-bit register ticks
        g_motionEngine.update(dt_s);

        vTaskDelayUntil(&xLastWakeTime, xFrequency); // Deterministic 20 ms (50 Hz)
    }
}

// ============================================================================
// CORE 1: Sensor Polling & Telemetry Generation Task (10 Hz telem.sensors)
// ============================================================================
static void Task_Sensors(void* pvParameters) {
    Serial.printf("[Task_Sensors] Running on Core %d, Priority %d (10 Hz Sensor / Buzzer)\n", 
                  xPortGetCoreID(), uxTaskPriorityGet(NULL));

    g_sensorEngine.begin();

    // Heartbeat LED on GPIO 10 setup
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    uint32_t last_status_telem_ms = 0;
    uint32_t last_led_toggle_ms = 0;
    bool led_state = false;

    TickType_t xLastWakeTime = xTaskGetTickCount();
    const TickType_t xFrequency = pdMS_TO_TICKS(10); // Deterministic 10 ms inner loop

    for (;;) {
        uint32_t now = millis();

        // 1. Process any inbound buzzer commands from Core 0
        BuzzerCommand_t bcmd;
        while (xQueueReceive(g_buzzerCmdQueue, &bcmd, 0) == pdPASS) {
            const char* act_str = "beep";
            switch (bcmd.action) {
                case BUZZER_ACT_CHIRP: act_str = "chirp"; break;
                case BUZZER_ACT_ALARM: act_str = "alarm"; break;
                case BUZZER_ACT_PULSE: act_str = "pulse"; break;
                case BUZZER_ACT_MUTE:  act_str = "mute";  break;
                case BUZZER_ACT_BEEP:
                default: act_str = "beep"; break;
            }
            g_sensorEngine.commandBuzzer(act_str, bcmd.duration_ms, bcmd.count, bcmd.interval_ms);
        }

        // 2. Update sensor acquisition (Buzzer state machine + 10 Hz ultrasonic ping)
        bool new_sample = g_sensorEngine.update();

        // 3. If new 10 Hz sample ready, serialize telem.sensors and enqueue to outbox
        if (new_sample) {
            SensorSnapshot_t s_snap;
            MotionSnapshot_t m_snap;
            SystemSnapshot_t sys_snap;

            if (xSemaphoreTake(g_stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                g_sensorEngine.getSnapshot(s_snap);
                g_motionEngine.getSnapshot(m_snap);
                xSemaphoreGive(g_stateMutex);
            }

            // Populate system health snapshot
            sys_snap.uptime_ms = now;
            sys_snap.rssi_dbm = g_wifiManager.getRSSI();
            sys_snap.free_heap_bytes = ESP.getFreeHeap();
            sys_snap.psram_free_bytes = ESP.getFreePsram();
            sys_snap.cpu_temp_c = temperatureRead();
            sys_snap.wifi_connected = g_wifiManager.isConnected();
            sys_snap.ws_connected = g_wsClient.isConnected();
            sys_snap.failsafe_active = g_failsafe_active;
            sys_snap.estop_active = m_snap.estop_active;
            strncpy(sys_snap.ip_addr, g_wifiManager.getIP().c_str(), sizeof(sys_snap.ip_addr));

            String telem_json;
            g_protocolHandler.serializeSensorsTelemetry(s_snap, m_snap, sys_snap, telem_json);
            enqueueOutboxMessage(telem_json);
        }

        // 4. Cadenced 1 Hz telem.status serialization
        if (now - last_status_telem_ms >= STATUS_INTERVAL_MS) {
            last_status_telem_ms = now;

            MotionSnapshot_t m_snap;
            SystemSnapshot_t sys_snap;
            if (xSemaphoreTake(g_stateMutex, pdMS_TO_TICKS(10)) == pdTRUE) {
                g_motionEngine.getSnapshot(m_snap);
                xSemaphoreGive(g_stateMutex);
            }

            sys_snap.uptime_ms = now;
            sys_snap.rssi_dbm = g_wifiManager.getRSSI();
            sys_snap.free_heap_bytes = ESP.getFreeHeap();
            sys_snap.psram_free_bytes = ESP.getFreePsram();
            sys_snap.cpu_temp_c = temperatureRead();
            sys_snap.wifi_connected = g_wifiManager.isConnected();
            sys_snap.ws_connected = g_wsClient.isConnected();
            sys_snap.failsafe_active = g_failsafe_active;
            sys_snap.estop_active = m_snap.estop_active;
            strncpy(sys_snap.ip_addr, g_wifiManager.getIP().c_str(), sizeof(sys_snap.ip_addr));

            String status_json;
            g_protocolHandler.serializeStatusTelemetry(m_snap, sys_snap, status_json);
            enqueueOutboxMessage(status_json);
        }

        // 5. System Status LED Blink Pattern (GPIO 10)
        uint32_t led_interval = g_failsafe_active ? LED_HEARTBEAT_FAILSAFE_MS : LED_HEARTBEAT_NORMAL_MS;
        if (now - last_led_toggle_ms >= led_interval) {
            last_led_toggle_ms = now;
            led_state = !led_state;
            digitalWrite(PIN_STATUS_LED, led_state ? HIGH : LOW);
        }

        vTaskDelayUntil(&xLastWakeTime, xFrequency); // Deterministic 10 ms inner loop
    }
}

// ============================================================================
// Setup Entrypoint
// ============================================================================
void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println("\n=======================================================");
    Serial.println("  SmartVision Dual-Core ESP32-S3 Firmware (Phase 3)");
    Serial.println("=======================================================");
    Serial.printf("Chip Model: %s | Rev: %d | Cores: %d | Freq: %lu MHz\n",
                  ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores(), (unsigned long)ESP.getCpuFreqMHz());
    Serial.printf("Free SRAM: %lu bytes | Free PSRAM: %lu bytes\n",
                  (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getFreePsram());
    Serial.println("=======================================================\n");

    // 1. Create FreeRTOS Queues & Mutexes
    g_servoCmdQueue  = xQueueCreate(CMD_QUEUE_DEPTH, sizeof(MotionCommand_t));
    g_buzzerCmdQueue = xQueueCreate(BUZZER_QUEUE_DEPTH, sizeof(BuzzerCommand_t));
    g_outboxQueue    = xQueueCreate(OUTBOX_QUEUE_DEPTH, sizeof(OutboxMessage_t));
    g_stateMutex     = xSemaphoreCreateMutex();

    if (!g_servoCmdQueue || !g_buzzerCmdQueue || !g_outboxQueue || !g_stateMutex) {
        Serial.println("[FATAL] Failed to allocate FreeRTOS synchronization primitives!");
        while (1) delay(1000);
    }

    // 2. Wire ProtocolHandler callbacks
    g_protocolHandler.onWatchdogFeed([]() {
        g_last_rx_ms = millis();
        if (g_failsafe_active) {
            g_failsafe_active = false;
            MotionCommand_t resumeCmd = { MOTION_CMD_RESUME, 0.0f, 0.0f, 0.0f, false, false };
            xQueueSend(g_servoCmdQueue, &resumeCmd, 0);
            Serial.println("[Protocol] Valid message received. Failsafe cleared -> NORMAL operation.");
        }
    });

    g_protocolHandler.onMotionCommand([](const MotionCommand_t& cmd) {
        xQueueSend(g_servoCmdQueue, &cmd, 0);
    });

    g_protocolHandler.onBuzzerCommand([](const BuzzerCommand_t& cmd) {
        xQueueSend(g_buzzerCmdQueue, &cmd, 0);
    });

    g_protocolHandler.onPingReceived([](uint64_t echo_ts, const char* corr_id) {
        String pong_json;
        g_protocolHandler.serializePong(echo_ts, corr_id, pong_json);
        enqueueOutboxMessage(pong_json);
    });

    // 3. Spawn Dual-Core FreeRTOS Tasks
    // CORE 0: Networking & Watchdog
    xTaskCreatePinnedToCore(Task_Network, "Net_Task", 
                            TASK_NET_STACK_SIZE, NULL, TASK_NET_PRIORITY, NULL, TASK_NET_CORE);

    xTaskCreatePinnedToCore(Task_WatchdogSupervisor, "Watchdog_Task", 
                            TASK_WATCHDOG_STACK_SIZE, NULL, TASK_WATCHDOG_PRIORITY, NULL, TASK_WATCHDOG_CORE);

    // CORE 1: Hard Real-Time Motion Control & Sensor Acquisition
    xTaskCreatePinnedToCore(Task_Motion, "Motion_Task", 
                            TASK_MOTION_STACK_SIZE, NULL, TASK_MOTION_PRIORITY, NULL, TASK_MOTION_CORE);

    xTaskCreatePinnedToCore(Task_Sensors, "Sensors_Task", 
                            TASK_SENSOR_STACK_SIZE, NULL, TASK_SENSOR_PRIORITY, NULL, TASK_SENSOR_CORE);

    Serial.println("[Setup] All 4 FreeRTOS tasks initialized and pinned to dual cores successfully.\n");
}

void loop() {
    // Arduino loop() yields; all logic is dispatched by FreeRTOS tasks pinned to Core 0 and Core 1
    vTaskDelay(pdMS_TO_TICKS(1000));
}
