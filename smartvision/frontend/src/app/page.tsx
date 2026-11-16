"use client";

import React, { useCallback, useState } from "react";
import { HeaderStatus } from "../components/HeaderStatus";
import { VideoViewport } from "../components/VideoViewport";
import { ManualControls } from "../components/ManualControls";
import { TrackingControls } from "../components/TrackingControls";
import { SensorMonitoring } from "../components/SensorMonitoring";
import { EventLogFeed } from "../components/EventLogFeed";
import { useSmartVisionWebSocket } from "../hooks/useSmartVisionWebSocket";
import { useKeyboardControls } from "../hooks/useKeyboardControls";
import { SafeStopAction, TrackingMode, TrackTargetSelectPayload } from "../types/protocol";

export default function SmartVisionDashboard() {
  const {
    connectionStatus,
    latencyMs,
    systemStatus,
    sensorTelemetry,
    frameTarget,
    alerts,
    activeMode,
    isEstopActive,
    connect,
    sendServoMove,
    sendServoJog,
    sendServoCenter,
    sendServoPatrol,
    sendEStop,
    sendTrackMode,
    sendTrackingConfig,
    sendTargetSelect,
    sendSelectTrackId,
    sendClickToTrack,
    sendBuzzer,
    clearAlerts,
  } = useSmartVisionWebSocket();

  // Manual override wrappers
  const handleJog = useCallback(
    (deltaPan: number, deltaTilt: number, speed: number) => {
      sendServoJog(deltaPan, deltaTilt, speed);
    },
    [sendServoJog]
  );

  const handleMoveAbsolute = useCallback(
    (pan: number, tilt: number, speed: number) => {
      sendServoMove(pan, tilt, speed);
    },
    [sendServoMove]
  );

  const handleCenter = useCallback(
    (speed = 0.4) => {
      sendServoCenter(speed);
    },
    [sendServoCenter]
  );

  // Keyboard shortcut support (WASD, Arrows, C to Center)
  useKeyboardControls({
    enabled: connectionStatus === "connected" && !isEstopActive,
    stepDeg: 3.0,
    speed: 0.35,
    onJog: handleJog,
    onCenter: () => handleCenter(0.4),
  });

  // Target Selection Handlers
  const handleTargetSelect = useCallback(
    (payload: TrackTargetSelectPayload) => {
      sendTargetSelect(payload);
    },
    [sendTargetSelect]
  );

  const handleSelectTrackId = useCallback(
    (trackId: number) => {
      sendSelectTrackId(trackId);
    },
    [sendSelectTrackId]
  );

  const handleClickToTrack = useCallback(
    (clickX: number, clickY: number) => {
      sendClickToTrack(clickX, clickY);
    },
    [sendClickToTrack]
  );

  const handleStopTracking = useCallback(() => {
    sendTrackMode("manual");
  }, [sendTrackMode]);

  const handlePatrolToggle = useCallback(
    (enabled: boolean) => {
      sendServoPatrol(enabled);
    },
    [sendServoPatrol]
  );

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col font-sans text-slate-100">
      {/* 1. Global Surveillance Header */}
      <HeaderStatus
        wsStatus={connectionStatus}
        latencyMs={latencyMs}
        esp32Status={systemStatus?.esp32}
        esp32Rssi={sensorTelemetry?.system?.rssi_dbm ?? systemStatus?.esp32?.rssi_dbm}
        esp32UptimeMs={sensorTelemetry?.system?.uptime_ms ?? systemStatus?.esp32?.uptime_ms}
        cameraStatus={systemStatus?.camera}
        uptimeSeconds={systemStatus?.uptime_s || 0}
        isEstopActive={isEstopActive}
        onTriggerEstop={(action?: SafeStopAction, reason?: string) => {
          sendEStop(action || "freeze", reason || "operator_manual_e_stop");
        }}
        onResetEstop={() => {
          sendEStop("resume", "operator_cleared_e_stop");
        }}
        onReconnect={connect}
      />

      {/* 2. Main Surveillance Grid Workspace */}
      <main className="flex-1 p-3 md:p-4 max-w-[1920px] w-full mx-auto grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column: Primary Video Viewport & Sensor Monitoring (7 Cols) */}
        <section className="lg:col-span-7 flex flex-col space-y-4">
          {/* Live Camera Viewport with Canvas Vector Reticle */}
          <VideoViewport
            streamUrl="/api/v1/stream/video.mjpeg"
            frameTarget={frameTarget}
            trackingMode={activeMode}
            isEstopActive={isEstopActive}
            fps={systemStatus?.camera?.fps || systemStatus?.tracking?.fps || 30}
            latencyMs={latencyMs}
            onTargetSelect={handleTargetSelect}
            onSelectTrackId={handleSelectTrackId}
            onClickToTrack={handleClickToTrack}
          />

          {/* Sensor Monitoring & Hardware Diagnostics */}
          <SensorMonitoring
            sensorTelemetry={sensorTelemetry}
            onBuzzerTest={(action, duration) => sendBuzzer(action, duration)}
          />
        </section>

        {/* Right Column: Tracking Controls, Manual Pan/Tilt & Event Log (5 Cols) */}
        <section className="lg:col-span-5 flex flex-col space-y-4">
          {/* Autonomous Tracking Control Card */}
          <TrackingControls
            currentMode={activeMode}
            activeTarget={frameTarget?.active_target}
            allDetections={frameTarget?.all_detections}
            isEstopActive={isEstopActive}
            onSetMode={(m: TrackingMode) => sendTrackMode(m)}
            onSelectTrackId={handleSelectTrackId}
            onStopTracking={handleStopTracking}
            onPatrolToggle={handlePatrolToggle}
            onUpdateTrackingConfig={sendTrackingConfig}
          />

          {/* Manual Pan/Tilt Gimbal Controls */}
          <ManualControls
            servosTelemetry={sensorTelemetry?.servos}
            isEstopActive={isEstopActive}
            onJog={handleJog}
            onMoveAbsolute={handleMoveAbsolute}
            onCenter={handleCenter}
          />

          {/* Event Logs & Alert Stream */}
          <EventLogFeed
            alerts={alerts}
            onClearLogs={clearAlerts}
          />
        </section>
      </main>

      {/* Footer bar */}
      <footer className="w-full bg-slate-950 border-t border-slate-900 px-4 py-2 text-[11px] font-mono text-slate-500 flex flex-wrap items-center justify-between">
        <div>SmartVision Project — Master Edge Surveillance Hub</div>
        <div className="flex items-center space-x-3">
          <span>Targeting Model: YOLOv8n / ByteTrack</span>
          <span>PID: Anti-Windup 20Hz</span>
          <span>Protocol: JSON WS Envelope v1.0</span>
        </div>
      </footer>
    </div>
  );
}
