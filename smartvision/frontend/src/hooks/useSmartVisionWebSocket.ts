"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActiveTarget,
  AlertEventPayload,
  BuzzerControlPayload,
  ClickToTrackPayload,
  DetectedPerson,
  SafeStopAction,
  SafeStopPayload,
  SensorTelemetryPayload,
  ServoCenterPayload,
  ServoJogPayload,
  ServoMovePayload,
  ServoPatrolPayload,
  SmartVisionEnvelope,
  SystemStatusPayload,
  TrackFrameTargetPayload,
  TrackingMode,
  TrackModeSetPayload,
  TrackSelectIdPayload,
  TrackTargetSelectPayload,
} from "../types/protocol";

export type WsConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

interface UseSmartVisionWebSocketOptions {
  url?: string;
  autoConnect?: boolean;
  maxReconnectDelayMs?: number;
  heartbeatIntervalMs?: number;
}

export function useSmartVisionWebSocket(options: UseSmartVisionWebSocketOptions = {}) {
  const {
    url,
    autoConnect = true,
    maxReconnectDelayMs = 10000,
    heartbeatIntervalMs = 5000,
  } = options;

  const [connectionStatus, setConnectionStatus] = useState<WsConnectionStatus>("disconnected");
  const [latencyMs, setLatencyMs] = useState<number>(0);
  const [systemStatus, setSystemStatus] = useState<SystemStatusPayload | null>(null);
  const [sensorTelemetry, setSensorTelemetry] = useState<SensorTelemetryPayload | null>(null);
  const [frameTarget, setFrameTarget] = useState<TrackFrameTargetPayload | null>(null);
  const [alerts, setAlerts] = useState<AlertEventPayload[]>([]);
  const [activeMode, setActiveMode] = useState<TrackingMode>("idle");
  const [isEstopActive, setIsEstopActive] = useState<boolean>(false);

  const wsRef = useRef<WebSocket | null>(null);
  const seqRef = useRef<number>(1);
  const reconnectAttemptRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const heartbeatTimerRef = useRef<NodeJS.Timeout | null>(null);
  const lastSendTimeRef = useRef<number>(0);
  const isMountedRef = useRef<boolean>(true);

  // Determine WebSocket endpoint
  const getWebSocketUrl = useCallback(() => {
    if (url) return url;
    if (typeof window !== "undefined") {
      const envUrl = process.env.NEXT_PUBLIC_WS_URL;
      if (envUrl) return envUrl;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.hostname || "localhost";
      return `${protocol}//${host}:8000/ws/client`;
    }
    return "ws://localhost:8000/ws/client";
  }, [url]);

  // Clean, monotonic sequence generation
  const getNextSeq = useCallback(() => {
    const s = seqRef.current;
    seqRef.current = (s + 1) >>> 0;
    return s;
  }, []);

  // Low-level send with 20 Hz outbound throttling protection
  const sendEnvelope = useCallback(
    <T,>(type: string, payload: T, corrId?: string): boolean => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        return false;
      }

      const now = performance.now();
      // Ensure at least 45ms between non-critical jog/move commands to prevent 20Hz boundary tripping
      if (type.startsWith("cmd.servo") || type === "cmd.jog") {
        if (now - lastSendTimeRef.current < 45) {
          return false;
        }
      }
      lastSendTimeRef.current = now;

      const envelope: SmartVisionEnvelope<T> = {
        type,
        timestamp: Date.now(),
        sender: "frontend",
        seq: getNextSeq(),
        corr_id: corrId || null,
        payload,
      };

      try {
        ws.send(JSON.stringify(envelope));
        return true;
      } catch (err) {
        console.error("Failed to send WebSocket message:", err);
        return false;
      }
    },
    [getNextSeq]
  );

  // Command Dispatches
  const sendServoMove = useCallback(
    (pan: number, tilt: number, speed = 0.5, mode: "absolute" | "relative" = "absolute", smooth = true) => {
      return sendEnvelope<ServoMovePayload>("cmd.servo.move", {
        mode,
        pan,
        tilt,
        speed,
        smooth,
      });
    },
    [sendEnvelope]
  );

  const sendServoJog = useCallback(
    (deltaPan: number, deltaTilt: number, speed = 0.5) => {
      return sendEnvelope<ServoJogPayload>("cmd.jog", {
        delta_pan: deltaPan,
        delta_tilt: deltaTilt,
        speed,
      });
    },
    [sendEnvelope]
  );

  const sendServoCenter = useCallback(
    (speed = 0.4) => {
      return sendEnvelope<ServoCenterPayload>("cmd.servo.center", { speed });
    },
    [sendEnvelope]
  );

  const sendServoPatrol = useCallback(
    (enabled: boolean, panMin = 30.0, panMax = 150.0, tiltAngle = 90.0, speedDegS = 20.0) => {
      return sendEnvelope<ServoPatrolPayload>("cmd.servo.patrol", {
        enabled,
        pan_min: panMin,
        pan_max: panMax,
        tilt_angle: tiltAngle,
        speed_deg_s: speedDegS,
      });
    },
    [sendEnvelope]
  );

  const sendEStop = useCallback(
    (action: SafeStopAction = "freeze", reason = "operator_e_stop", releasePwm = false) => {
      const success = sendEnvelope<SafeStopPayload>("cmd.estop", {
        action,
        reason,
        release_pwm: releasePwm,
      });
      if (action === "resume" || action === "reset") {
        setIsEstopActive(false);
      } else {
        setIsEstopActive(true);
      }
      return success;
    },
    [sendEnvelope]
  );

  const sendTrackMode = useCallback(
    (mode: TrackingMode) => {
      setActiveMode(mode);
      return sendEnvelope<TrackModeSetPayload>("track.mode_set", {
        mode,
        target_selection: "primary",
      });
    },
    [sendEnvelope]
  );

  const sendTargetSelect = useCallback(
    (
      target:
        | { track_id?: number; coordinates?: [number, number]; click_x?: number; click_y?: number }
        | number
        | [number, number]
    ) => {
      let payload: TrackTargetSelectPayload;
      if (typeof target === "number") {
        payload = { track_id: target };
      } else if (Array.isArray(target)) {
        payload = { coordinates: target };
      } else {
        payload = target;
      }
      return sendEnvelope<TrackTargetSelectPayload>("track.target_select", payload);
    },
    [sendEnvelope]
  );

  const sendSelectTrackId = useCallback(
    (trackId: number) => {
      // Dispatches track.select_id and track.target_select for unified compatibility
      sendTargetSelect({ track_id: trackId });
      return sendEnvelope<TrackSelectIdPayload>("track.select_id", {
        track_id: trackId,
      });
    },
    [sendEnvelope, sendTargetSelect]
  );

  const sendClickToTrack = useCallback(
    (clickX: number, clickY: number) => {
      sendTargetSelect({ click_x: clickX, click_y: clickY });
      return sendEnvelope<ClickToTrackPayload>("track.click_to_track", {
        click_x: clickX,
        click_y: clickY,
      });
    },
    [sendEnvelope, sendTargetSelect]
  );

  const sendBuzzer = useCallback(
    (action: "beep" | "chirp" | "alarm" | "pulse" | "off", durationMs = 150) => {
      return sendEnvelope<BuzzerControlPayload>("cmd.buzzer", {
        action,
        duration_ms: durationMs,
      });
    },
    [sendEnvelope]
  );

  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);

  // Connect & Event Loop
  const connect = useCallback(() => {
    if (!isMountedRef.current) return;
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const endpoint = getWebSocketUrl();
    setConnectionStatus(reconnectAttemptRef.current > 0 ? "reconnecting" : "connecting");

    try {
      const ws = new WebSocket(endpoint);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMountedRef.current) return;
        setConnectionStatus("connected");
        reconnectAttemptRef.current = 0;

        // Start heartbeat ping
        if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            const now = Date.now();
            ws.send(
              JSON.stringify({
                type: "sys.ping",
                timestamp: now,
                sender: "frontend",
                seq: getNextSeq(),
                payload: {},
              })
            );
          }
        }, heartbeatIntervalMs);
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          const envelope: SmartVisionEnvelope = JSON.parse(event.data);
          const { type, payload } = envelope;

          if (type === "sys.pong") {
            const sentTs = payload?.echo_timestamp || envelope.timestamp;
            const rtt = Math.max(1, Date.now() - sentTs);
            setLatencyMs(rtt);
          } else if (type === "sys.status") {
            const st = payload as SystemStatusPayload;
            setSystemStatus(st);
            setIsEstopActive(st.estop_active || false);
            if (st.tracking?.mode) {
              setActiveMode(st.tracking.mode);
            }
            if (st.sensors) {
              setSensorTelemetry((prev) => ({ ...(prev || {}), ...st.sensors } as SensorTelemetryPayload));
            }
          } else if (type === "telem.sensors") {
            setSensorTelemetry(payload as SensorTelemetryPayload);
          } else if (type === "track.frame_target") {
            const ft = payload as TrackFrameTargetPayload;
            setFrameTarget(ft);
            if (ft.latency_ms !== undefined) {
              setLatencyMs(Math.round(ft.latency_ms));
            }
          } else if (type === "track.mode_set") {
            if (payload?.mode) {
              setActiveMode(payload.mode);
            }
          } else if (type === "alert.event") {
            const alert = payload as AlertEventPayload;
            alert.timestamp = alert.timestamp || envelope.timestamp || Date.now();
            setAlerts((prev) => [alert, ...prev.slice(0, 199)]);

            if (alert.event_type === "estop_engaged" || alert.severity === "critical") {
              if (alert.event_type?.includes("estop")) {
                setIsEstopActive(true);
              }
            } else if (alert.event_type === "estop_cleared") {
              setIsEstopActive(false);
            }
          }
        } catch (err) {
          console.warn("Failed to parse incoming WS message:", err);
        }
      };

      ws.onerror = (err) => {
        console.warn("WebSocket transport error:", err);
      };

      ws.onclose = () => {
        if (!isMountedRef.current) return;
        setConnectionStatus("disconnected");
        wsRef.current = null;
        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current);
          heartbeatTimerRef.current = null;
        }

        // Schedule exponential backoff reconnect
        if (autoConnect) {
          const attempt = reconnectAttemptRef.current;
          const delay = Math.min(1000 * Math.pow(1.5, attempt), maxReconnectDelayMs);
          reconnectAttemptRef.current += 1;
          setConnectionStatus("reconnecting");
          reconnectTimeoutRef.current = setTimeout(connect, delay);
        }
      };
    } catch (err) {
      console.error("Could not construct WebSocket instance:", err);
      setConnectionStatus("disconnected");
    }
  }, [autoConnect, getNextSeq, getWebSocketUrl, heartbeatIntervalMs, maxReconnectDelayMs]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnectionStatus("disconnected");
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    if (autoConnect) {
      connect();
    }
    return () => {
      isMountedRef.current = false;
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    connectionStatus,
    latencyMs,
    systemStatus,
    sensorTelemetry,
    frameTarget,
    alerts,
    activeMode,
    isEstopActive,
    // Operations
    connect,
    disconnect,
    sendEnvelope,
    sendServoMove,
    sendServoJog,
    sendServoCenter,
    sendServoPatrol,
    sendEStop,
    sendTrackMode,
    sendTargetSelect,
    sendSelectTrackId,
    sendClickToTrack,
    sendBuzzer,
    clearAlerts,
  };
}
