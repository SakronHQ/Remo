"use client";

import React from "react";
import {
  Bell,
  Cpu,
  Flame,
  Gauge,
  Radio,
  Ruler,
  Volume2,
  VolumeX,
  Wifi,
} from "lucide-react";
import { SensorTelemetryPayload } from "../types/protocol";

interface SensorMonitoringProps {
  sensorTelemetry?: SensorTelemetryPayload | null;
  onBuzzerTest: (action: "beep" | "chirp" | "alarm" | "pulse" | "off", durationMs?: number) => void;
}

export function SensorMonitoring({
  sensorTelemetry,
  onBuzzerTest,
}: SensorMonitoringProps) {
  const sonar = sensorTelemetry?.sonar;
  const pir = sensorTelemetry?.pir;
  const buzzer = sensorTelemetry?.buzzer;
  const system = sensorTelemetry?.system;

  const distanceCm = sonar?.distance_cm ?? -1;
  const isSonarValid = sonar?.valid && distanceCm >= 2.0;

  // Proximity tiering
  // Green > 40cm, Yellow 20-40cm, Red < 20cm
  let proximityColor = "text-slate-400";
  let proximityBarBg = "bg-slate-700";
  let proximityLabel = "NO ECHO / STANDBY";

  if (isSonarValid) {
    if (distanceCm < 20) {
      proximityColor = "text-rose-400";
      proximityBarBg = "bg-rose-500 shadow-[0_0_10px_#ef4444]";
      proximityLabel = "CRITICAL PROXIMITY (< 20 cm)";
    } else if (distanceCm <= 40) {
      proximityColor = "text-amber-400";
      proximityBarBg = "bg-amber-500";
      proximityLabel = "WARNING PROXIMITY (20-40 cm)";
    } else {
      proximityColor = "text-emerald-400";
      proximityBarBg = "bg-emerald-500";
      proximityLabel = "CLEAR RANGE (> 40 cm)";
    }
  }

  const distanceBarPercent = isSonarValid
    ? Math.min(100, Math.max(5, (distanceCm / 200) * 100))
    : 0;

  const isMotion = pir?.motion_detected ?? false;
  const rssi = system?.rssi_dbm ?? -99;

  // PIR 30-second thermal stabilization warm-up window
  const isPirWarmingUp =
    pir?.warmup_complete === false ||
    (pir?.warmup_complete === undefined && system?.uptime_ms !== undefined && system.uptime_ms < 30000);
  const pirWarmupRemainingS =
    pir?.warmup_remaining_s !== undefined
      ? pir.warmup_remaining_s
      : system?.uptime_ms !== undefined
      ? Math.max(1, Math.ceil((30000 - system.uptime_ms) / 1000))
      : 30;

  return (
    <div className="w-full rounded-xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col space-y-4">
      {/* Section Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
        <div className="flex items-center space-x-2">
          <Gauge className="w-4 h-4 text-emerald-400" />
          <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-slate-100">
            Sensor Telemetry & Edge I/O
          </h3>
        </div>
        <span className="text-[11px] font-mono text-slate-400">10 Hz Telemetry Link</span>
      </div>

      {/* Sensor Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* HC-SR04 Ultrasonic Sonar Card */}
        <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1.5">
              <span className="flex items-center space-x-1.5">
                <Ruler className="w-3.5 h-3.5 text-slate-400" />
                <span>HC-SR04 Ultrasonic Sonar</span>
              </span>
              <span className={`text-[10px] uppercase font-bold ${proximityColor}`}>
                {sonar?.status || "STANDBY"}
              </span>
            </div>

            <div className="flex items-baseline space-x-2 my-2">
              <span className={`font-mono text-3xl font-extrabold ${proximityColor}`}>
                {isSonarValid ? distanceCm.toFixed(1) : "--"}
              </span>
              <span className="font-mono text-xs text-slate-400">cm</span>
            </div>

            {/* Proximity Color Bar */}
            <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden relative mb-1.5">
              <div
                className={`h-full rounded-full transition-all duration-150 ${proximityBarBg}`}
                style={{ width: `${distanceBarPercent}%` }}
              />
            </div>
          </div>

          <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1">
            <span>{proximityLabel}</span>
            <span>Max 200cm</span>
          </div>
        </div>

        {/* HC-SR501 PIR Motion Detector Card */}
        <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1.5">
              <span className="flex items-center space-x-1.5">
                <Radio className="w-3.5 h-3.5 text-slate-400" />
                <span>HC-SR501 PIR Motion</span>
              </span>
              <span className="text-[10px] font-mono text-slate-500">
                Count: {pir?.trigger_count ?? 0}
              </span>
            </div>

            <div className="flex items-center space-x-3 my-2">
              <div
                className={`flex items-center justify-center px-4 py-2 rounded-lg font-mono text-xs font-bold uppercase tracking-wider border transition-all ${
                  isPirWarmingUp
                    ? "bg-amber-950/80 text-amber-300 border-amber-500/60 shadow-[0_0_12px_rgba(245,158,11,0.25)] animate-pulse"
                    : isMotion
                    ? "bg-rose-950/80 text-rose-300 border-rose-500/60 shadow-[0_0_12px_rgba(244,63,94,0.3)] animate-pulse"
                    : "bg-emerald-950/40 text-emerald-400/90 border-emerald-500/30"
                }`}
              >
                <span
                  className={`w-2.5 h-2.5 rounded-full mr-2 ${
                    isPirWarmingUp
                      ? "bg-amber-400 animate-ping"
                      : isMotion
                      ? "bg-rose-500"
                      : "bg-emerald-500"
                  }`}
                />
                {isPirWarmingUp
                  ? `WARMING UP (${pirWarmupRemainingS}s)`
                  : isMotion
                  ? "ACTIVE (MOTION DETECTED)"
                  : "CLEAR / STABILIZED"}
              </div>
            </div>
          </div>

          <div className="text-[10px] font-mono text-slate-500 pt-1">
            {isPirWarmingUp
              ? `Thermal stabilization in progress (${pirWarmupRemainingS}s countdown)`
              : pir?.last_trigger_ms
              ? `Last trigger: ${(pir.last_trigger_ms / 1000).toFixed(0)}s since boot`
              : "Sensors armed and calibrated"}
          </div>
        </div>
      </div>

      {/* Active Buzzer & Edge Diagnostics Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Active Buzzer Control */}
        <div className="bg-slate-950 p-3 rounded-lg border border-slate-800">
          <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-2">
            <span className="flex items-center space-x-1.5">
              <Volume2 className="w-3.5 h-3.5 text-slate-400" />
              <span>Acoustic Alert Buzzer</span>
            </span>
            <span
              className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                buzzer?.active
                  ? "bg-amber-950 text-amber-400 border border-amber-500/30 animate-pulse"
                  : "bg-slate-900 text-slate-500"
              }`}
            >
              {buzzer?.active ? `ACTIVE (${buzzer.pattern})` : "MUTED"}
            </span>
          </div>

          {/* Quick Trigger Buttons */}
          <div className="grid grid-cols-4 gap-1.5 font-mono text-xs">
            <button
              onClick={() => onBuzzerTest("beep", 150)}
              className="px-2 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors text-center font-medium"
            >
              Beep
            </button>
            <button
              onClick={() => onBuzzerTest("chirp", 250)}
              className="px-2 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors text-center font-medium"
            >
              Chirp
            </button>
            <button
              onClick={() => onBuzzerTest("alarm", 1500)}
              className="px-2 py-1.5 rounded bg-rose-950/70 hover:bg-rose-900 text-rose-300 border border-rose-500/30 transition-colors text-center font-medium"
            >
              Alarm
            </button>
            <button
              onClick={() => onBuzzerTest("off", 0)}
              className="px-2 py-1.5 rounded bg-slate-900 hover:bg-slate-800 text-slate-400 border border-slate-800 transition-colors text-center font-medium"
            >
              Mute
            </button>
          </div>
        </div>

        {/* ESP32 Hardware Diagnostics */}
        <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-2">
            <span className="flex items-center space-x-1.5">
              <Cpu className="w-3.5 h-3.5 text-slate-400" />
              <span>Microcontroller Diagnostics</span>
            </span>
            <span className="text-[10px] text-emerald-400">ESP32-S3</span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs font-mono">
            {/* Wi-Fi RSSI */}
            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 block">WI-FI RSSI</span>
              <span
                className={`font-bold ${
                  rssi > -65
                    ? "text-emerald-400"
                    : rssi > -80
                    ? "text-amber-400"
                    : "text-rose-400"
                }`}
              >
                {rssi} dBm
              </span>
            </div>

            {/* Free Heap */}
            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 block">FREE HEAP</span>
              <span className="text-slate-200 font-bold">
                {system?.free_heap_bytes
                  ? `${Math.round(system.free_heap_bytes / 1024)} KB`
                  : "--"}
              </span>
            </div>

            {/* Core Temp */}
            <div className="bg-slate-900/80 p-1.5 rounded border border-slate-800">
              <span className="text-[10px] text-slate-500 block">CPU TEMP</span>
              <span className="text-cyan-400 font-bold">
                {system?.cpu_temp_c ? `${system.cpu_temp_c.toFixed(1)}°C` : "42.0°C"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
