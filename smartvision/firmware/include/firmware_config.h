/**
 * @file firmware_config.h
 * @brief SmartVision Firmware Configuration Parameters & Timing Thresholds.
 *
 * Configures Wi-Fi credentials, FastAPI backend WebSocket target, FreeRTOS
 * dual-core task allocations, watchdog timeout (800ms), and telemetry rates.
 * Follows Ponytail principles: clean, minimal, robust defaults.
 */

#pragma once

#include <Arduino.h>
#include "hardware_config.h"

// ============================================================================
// 1. Wi-Fi Configuration Template
// ============================================================================
#ifndef WIFI_SSID
#define WIFI_SSID                   "SmartVision-AP"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD               "smartvision123"
#endif

// Wi-Fi Connection & Reconnect Exponential Backoff (ms)
#define WIFI_CONNECT_TIMEOUT_MS     12000UL // 12 seconds connection attempt window
#define WIFI_BACKOFF_MIN_MS         1000UL  // 1.0 second base backoff
#define WIFI_BACKOFF_MAX_MS         10000UL // 10.0 seconds maximum backoff

// ============================================================================
// 2. FastAPI Backend WebSocket Configuration
// ============================================================================
#ifndef BACKEND_HOST
#define BACKEND_HOST                "192.168.1.100"
#endif

#ifndef BACKEND_PORT
#define BACKEND_PORT                8000
#endif

#ifndef BACKEND_WS_PATH
#define BACKEND_WS_PATH             "/ws/device"
#endif

// WebSocket Reconnect Parameters (ms)
#define WS_RECONNECT_INTERVAL_MS    1000UL  // 1 second base reconnect interval

// ============================================================================
// 3. Safety Watchdog & Fail-Safe Timing
// ============================================================================
// Communication watchdog: triggers safe-stop if no valid packet/ping within 800ms
#define WATCHDOG_TIMEOUT_MS         800UL

// Warning alert chirp recurrence period while in failsafe (ms)
#define FAILSAFE_ALERT_INTERVAL_MS  5000UL

// ============================================================================
// 4. Loop Cadences & Streaming Rates
// ============================================================================
#define TELEMETRY_INTERVAL_MS       100UL   // 10 Hz sensor telemetry streaming
#define STATUS_INTERVAL_MS          1000UL  // 1 Hz heartbeat / system status
#define MOTION_UPDATE_INTERVAL_MS   20UL    // 50 Hz discrete slew rate interpolation
#define SENSOR_SAMPLE_INTERVAL_MS   100UL   // 10 Hz HC-SR04 ping & HC-SR501 sampling
#define LED_HEARTBEAT_NORMAL_MS     1000UL  // 1 Hz normal heartbeat blink
#define LED_HEARTBEAT_FAILSAFE_MS   200UL   // 5 Hz rapid alert strobe

// ============================================================================
// 5. FreeRTOS Dual-Core Concurrency & Task Allocations
// ============================================================================
// Core 0: Wi-Fi stack, WebSocket client, 800ms Watchdog Supervisor
#define TASK_NET_STACK_SIZE         8192
#define TASK_NET_PRIORITY           1
#define TASK_NET_CORE               0

#define TASK_WATCHDOG_STACK_SIZE    4096
#define TASK_WATCHDOG_PRIORITY      4       // Highest supervisor priority
#define TASK_WATCHDOG_CORE          0

// Core 1: Motion Engine (PCA9685 Slew) & Sensor Acquisition (HC-SR04, HC-SR501, Buzzer)
#define TASK_MOTION_STACK_SIZE      4096
#define TASK_MOTION_PRIORITY        3       // Hard real-time motion control
#define TASK_MOTION_CORE            1

#define TASK_SENSOR_STACK_SIZE      4096
#define TASK_SENSOR_PRIORITY        2       // Deterministic sensor polling
#define TASK_SENSOR_CORE            1

// ============================================================================
// 6. FreeRTOS Queue Capacities
// ============================================================================
#define CMD_QUEUE_DEPTH             8       // Command queue depth for inbound motion commands
#define BUZZER_QUEUE_DEPTH          8       // Buzzer queue depth
#define OUTBOX_QUEUE_DEPTH          16      // Outbound JSON telemetry messages
#define OUTBOX_MSG_MAX_LEN          768     // Max JSON envelope character length
