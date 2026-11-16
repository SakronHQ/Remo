"use client";

import React, { useState } from "react";
import {
  Activity,
  AlertOctagon,
  Camera,
  Cpu,
  Power,
  Radio,
  RefreshCw,
  RotateCcw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { ESP32Status, CameraStatus, SafeStopAction } from "../types/protocol";
import { WsConnectionStatus } from "../hooks/useSmartVisionWebSocket";

interface HeaderStatusProps {
  wsStatus: WsConnectionStatus;
  latencyMs: number;
  esp32Status?: ESP32Status | null;
  esp32Rssi?: number | null;
  esp32UptimeMs?: number | null;
  cameraStatus?: CameraStatus | null;
  uptimeSeconds?: number;
  isEstopActive: boolean;
  onTriggerEstop: (action?: SafeStopAction, reason?: string) => void;
  onResetEstop: () => void;
  onReconnect: () => void;
}

export function HeaderStatus({
  wsStatus,
  latencyMs,
  esp32Status,
  esp32Rssi,
  esp32UptimeMs,
  cameraStatus,
  uptimeSeconds = 0,
  isEstopActive,
  onTriggerEstop,
  onResetEstop,
  onReconnect,
}: HeaderStatusProps) {
  const [showConfirmModal, setShowConfirmModal] = useState(false);

  const formatUptime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const isEspOnline = esp32Status?.connected ?? false;
  const isWsConnected = wsStatus === "connected";

  return (
    <header className="w-full bg-slate-950 border-b border-slate-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 text-sm select-none">
      {/* Brand & Title */}
      <div className="flex items-center space-x-3">
        <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-emerald-950 border border-emerald-500/30 text-emerald-400">
          <Activity className="w-5 h-5 animate-pulse" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <span className="font-bold tracking-wider text-slate-100 uppercase text-base">
              SmartVision
            </span>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-emerald-950/80 text-emerald-400 border border-emerald-500/20">
              v1.0 Sentinel
            </span>
          </div>
          <div className="text-[11px] text-slate-400 font-mono">
            Autonomous Pan-Tilt Person Tracking
          </div>
        </div>
      </div>

      {/* Real-time Status Badges */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Gateway WebSocket */}
        <div className="flex items-center space-x-2 px-2.5 py-1 rounded bg-slate-900 border border-slate-800">
          <span
            className={`w-2 h-2 rounded-full ${
              wsStatus === "connected"
                ? "bg-emerald-500 shadow-[0_0_8px_#10b981]"
                : wsStatus === "reconnecting"
                ? "bg-amber-500 animate-ping"
                : "bg-rose-500"
            }`}
          />
          <span className="text-xs font-mono uppercase text-slate-300">
            Hub: {wsStatus}
          </span>
          {wsStatus === "connected" && (
            <span className="text-[11px] font-mono text-emerald-400">
              {latencyMs}ms
            </span>
          )}
          {wsStatus !== "connected" && (
            <button
              onClick={onReconnect}
              title="Manual reconnect"
              className="text-slate-400 hover:text-white transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* ESP32 Edge Device */}
        <div className="flex items-center space-x-2 px-2.5 py-1 rounded bg-slate-900 border border-slate-800">
          <Cpu className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs font-mono uppercase text-slate-300">
            ESP32:
          </span>
          <span
            className={`text-xs font-mono font-semibold ${
              isEspOnline ? "text-emerald-400" : "text-rose-400"
            }`}
          >
            {isEspOnline ? "ONLINE" : "OFFLINE"}
          </span>
          {isEspOnline && (
            <div className="flex items-center space-x-1.5 text-[10px] font-mono text-slate-400 hidden sm:flex">
              {esp32Status?.ip && <span>({esp32Status.ip})</span>}
              {(esp32Rssi !== undefined && esp32Rssi !== null) ||
              (esp32Status?.rssi_dbm !== undefined && esp32Status?.rssi_dbm !== null) ? (
                <span className="text-emerald-400/90 font-medium">
                  {esp32Rssi ?? esp32Status?.rssi_dbm} dBm
                </span>
              ) : null}
              {(esp32UptimeMs !== undefined && esp32UptimeMs !== null) ||
              (esp32Status?.uptime_ms !== undefined && esp32Status?.uptime_ms !== null) ? (
                <span className="text-slate-400">
                  [{formatUptime(Math.floor(((esp32UptimeMs ?? esp32Status?.uptime_ms) || 0) / 1000))}]
                </span>
              ) : null}
            </div>
          )}
        </div>

        {/* Camera Service */}
        <div className="flex items-center space-x-2 px-2.5 py-1 rounded bg-slate-900 border border-slate-800">
          <Camera className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-xs font-mono uppercase text-slate-300">
            Cam:
          </span>
          <span
            className={`text-xs font-mono font-semibold ${
              cameraStatus?.running ? "text-emerald-400" : "text-amber-400"
            }`}
          >
            {cameraStatus?.running
              ? `${cameraStatus.fps?.toFixed(0) || 30} FPS`
              : "READY"}
          </span>
          {cameraStatus?.synthetic && (
            <span className="text-[10px] font-mono text-amber-400/80 px-1 rounded bg-amber-950/60 border border-amber-800/40">
              SIM
            </span>
          )}
        </div>

        {/* System Uptime */}
        <div className="hidden lg:flex items-center space-x-1.5 px-2.5 py-1 rounded bg-slate-900 border border-slate-800 text-slate-400">
          <span className="text-[11px] font-mono">UP:</span>
          <span className="text-xs font-mono text-slate-200">
            {formatUptime(uptimeSeconds)}
          </span>
        </div>
      </div>

      {/* Global E-Stop Button */}
      <div className="flex items-center">
        {isEstopActive ? (
          <div className="flex items-center space-x-2">
            <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-rose-950/90 border border-rose-500/60 text-rose-300 animate-pulse">
              <AlertOctagon className="w-4 h-4 text-rose-500" />
              <span className="font-mono text-xs font-bold tracking-wider">
                E-STOP ACTIVE
              </span>
            </div>
            <button
              onClick={onResetEstop}
              className="flex items-center space-x-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-mono text-xs font-semibold shadow-lg shadow-emerald-950 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>RESUME</span>
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowConfirmModal(true)}
            className="flex items-center space-x-1.5 px-3.5 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white font-mono text-xs font-bold uppercase tracking-wider shadow-lg shadow-rose-950 border border-rose-400/30 transition-transform active:scale-95"
          >
            <Power className="w-4 h-4" />
            <span>E-STOP</span>
          </button>
        )}
      </div>

      {/* E-Stop Confirmation Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl bg-slate-900 border border-rose-500/50 p-6 shadow-2xl">
            <div className="flex items-center space-x-3 text-rose-400 mb-3">
              <AlertOctagon className="w-7 h-7" />
              <h3 className="text-lg font-bold uppercase tracking-wider text-white">
                Emergency Stop Confirmation
              </h3>
            </div>
            <p className="text-slate-300 text-sm mb-4 leading-relaxed">
              Triggering the Global E-Stop will immediately freeze servo motion,
              terminate active autonomous tracking, and sound an alert pattern.
              Are you sure?
            </p>
            <div className="flex items-center justify-end space-x-3">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-mono font-medium transition-colors"
              >
                CANCEL
              </button>
              <button
                onClick={() => {
                  setShowConfirmModal(false);
                  onTriggerEstop("freeze", "operator_manual_e_stop");
                }}
                className="px-4 py-2 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-mono font-bold tracking-wider transition-colors shadow-lg shadow-rose-950"
              >
                ENGAGE E-STOP
              </button>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
