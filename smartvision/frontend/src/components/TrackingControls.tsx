"use client";

import React, { useState } from "react";
import {
  Compass,
  Crosshair,
  Lock,
  Pause,
  Play,
  RotateCcw,
  Sliders,
  Target,
  Unlock,
  UserCheck,
  Users,
} from "lucide-react";
import {
  ActiveTarget,
  DetectedPerson,
  TrackingMode,
} from "../types/protocol";

interface TrackingControlsProps {
  currentMode: TrackingMode;
  activeTarget?: ActiveTarget | null;
  allDetections?: DetectedPerson[];
  isEstopActive: boolean;
  onSetMode: (mode: TrackingMode) => void;
  onSelectTrackId: (trackId: number) => void;
  onStopTracking: () => void;
  onPatrolToggle: (enabled: boolean) => void;
  onUpdateTrackingConfig?: (config: { invert_pan?: boolean; invert_tilt?: boolean; preset?: string }) => void;
}

export function TrackingControls({
  currentMode,
  activeTarget,
  allDetections = [],
  isEstopActive,
  onSetMode,
  onSelectTrackId,
  onStopTracking,
  onPatrolToggle,
  onUpdateTrackingConfig,
}: TrackingControlsProps) {
  const [invertPan, setInvertPan] = useState(false);
  const [invertTilt, setInvertTilt] = useState(false);
  const [activePreset, setActivePreset] = useState<"smooth" | "normal" | "sports">("normal");
  const modes: { id: TrackingMode; label: string; icon: React.ReactNode; desc: string }[] = [
    {
      id: "auto_track",
      label: "Auto-Track",
      icon: <Target className="w-4 h-4" />,
      desc: "Autonomous PID closed-loop visual tracking",
    },
    {
      id: "manual",
      label: "Manual",
      icon: <Crosshair className="w-4 h-4" />,
      desc: "Operator manual joystick / D-pad actuation",
    },
    {
      id: "patrol",
      label: "Patrol",
      icon: <Compass className="w-4 h-4" />,
      desc: "Autonomous continuous azimuth sweep",
    },
    {
      id: "idle",
      label: "Idle",
      icon: <Pause className="w-4 h-4" />,
      desc: "Servos hold position; vision passive",
    },
  ];

  const isTargetLocked = Boolean(activeTarget && activeTarget.track_id !== undefined);

  return (
    <div className="w-full rounded-xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col space-y-4">
      {/* Section Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
        <div className="flex items-center space-x-2">
          <Target className="w-4 h-4 text-cyan-400" />
          <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-slate-100">
            Tracking Controller
          </h3>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-[11px] font-mono uppercase font-semibold ${
            currentMode === "auto_track"
              ? "bg-emerald-950 text-emerald-400 border border-emerald-500/40"
              : currentMode === "patrol"
              ? "bg-purple-950 text-purple-400 border border-purple-500/40"
              : currentMode === "manual"
              ? "bg-cyan-950 text-cyan-400 border border-cyan-500/40"
              : "bg-slate-800 text-slate-400"
          }`}
        >
          {currentMode}
        </span>
      </div>

      {/* Mode Selector Tabs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {modes.map((m) => {
          const isActive = currentMode === m.id;
          return (
            <button
              key={m.id}
              disabled={isEstopActive}
              onClick={() => {
                if (m.id === "patrol") {
                  onPatrolToggle(true);
                } else {
                  if (currentMode === "patrol") {
                    onPatrolToggle(false);
                  }
                  onSetMode(m.id);
                }
              }}
              className={`flex flex-col items-center justify-center p-2.5 rounded-lg border font-mono text-xs transition-all disabled:opacity-40 ${
                isActive
                  ? "bg-cyan-950/80 border-cyan-500/60 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
                  : "bg-slate-950 hover:bg-slate-800 border-slate-800 text-slate-400"
              }`}
            >
              <div className="mb-1">{m.icon}</div>
              <span className="font-semibold">{m.label}</span>
            </button>
          );
        })}
      </div>

      {/* Motion Tuning & Inversion Toggles */}
      <div className="bg-slate-950 rounded-lg border border-slate-800 p-3 space-y-2.5 font-mono text-xs">
        <div className="flex items-center justify-between text-slate-400">
          <span className="font-semibold uppercase tracking-wider flex items-center space-x-1.5 text-[11px]">
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            <span>Axis Inversion & Presets</span>
          </span>
          <span className="text-[10px] text-cyan-400 uppercase font-bold">{activePreset}</span>
        </div>

        {/* Pan / Tilt Inversion Toggles */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => {
              const next = !invertPan;
              setInvertPan(next);
              onUpdateTrackingConfig?.({ invert_pan: next });
            }}
            className={`flex items-center justify-between px-2.5 py-1.5 rounded border text-[11px] transition-colors ${
              invertPan
                ? "bg-amber-950/70 border-amber-500/60 text-amber-300 font-bold"
                : "bg-slate-900 border-slate-800 text-slate-400 hover:bg-slate-800"
            }`}
          >
            <span>Invert Pan (X)</span>
            <span className={`text-[10px] px-1 rounded ${invertPan ? "bg-amber-500/30 text-amber-300" : "text-slate-500"}`}>
              {invertPan ? "REV" : "NORM"}
            </span>
          </button>

          <button
            onClick={() => {
              const next = !invertTilt;
              setInvertTilt(next);
              onUpdateTrackingConfig?.({ invert_tilt: next });
            }}
            className={`flex items-center justify-between px-2.5 py-1.5 rounded border text-[11px] transition-colors ${
              invertTilt
                ? "bg-amber-950/70 border-amber-500/60 text-amber-300 font-bold"
                : "bg-slate-900 border-slate-800 text-slate-400 hover:bg-slate-800"
            }`}
          >
            <span>Invert Tilt (Y)</span>
            <span className={`text-[10px] px-1 rounded ${invertTilt ? "bg-amber-500/30 text-amber-300" : "text-slate-500"}`}>
              {invertTilt ? "REV" : "NORM"}
            </span>
          </button>
        </div>

        {/* Presets: Smooth / Normal / Sports */}
        <div className="grid grid-cols-3 gap-1.5 pt-0.5">
          {(["smooth", "normal", "sports"] as const).map((p) => (
            <button
              key={p}
              onClick={() => {
                setActivePreset(p);
                onUpdateTrackingConfig?.({ preset: p });
              }}
              className={`py-1 rounded text-[10px] uppercase font-bold tracking-wider border transition-colors ${
                activePreset === p
                  ? "bg-cyan-950 border-cyan-500 text-cyan-300 shadow-[0_0_8px_rgba(6,182,212,0.2)]"
                  : "bg-slate-900 border-slate-800 text-slate-500 hover:bg-slate-800 hover:text-slate-300"
              }`}
            >
              {p === "smooth" ? "Cinematic" : p === "normal" ? "Standard" : "Sports"}
            </button>
          ))}
        </div>
      </div>

      {/* Active Locked Target Card */}
      <div className="bg-slate-950 rounded-lg border border-slate-800 p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center space-x-1.5 text-xs font-mono text-slate-300">
            {isTargetLocked ? (
              <Lock className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <Unlock className="w-3.5 h-3.5 text-slate-500" />
            )}
            <span className="font-semibold uppercase">Active Target Status:</span>
          </div>

          {isTargetLocked && (
            <button
              disabled={isEstopActive}
              onClick={onStopTracking}
              className="flex items-center space-x-1 px-2 py-0.5 rounded bg-rose-950/80 hover:bg-rose-900 border border-rose-500/30 text-rose-300 font-mono text-[11px] transition-colors"
            >
              <Unlock className="w-3 h-3" />
              <span>Unlock</span>
            </button>
          )}
        </div>

        {activeTarget ? (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
            <div className="bg-slate-900/80 p-2 rounded border border-slate-800">
              <span className="text-slate-500 text-[10px] block">TRACK ID</span>
              <span className="text-emerald-400 font-bold text-sm">
                #{activeTarget.track_id}
              </span>
            </div>

            <div className="bg-slate-900/80 p-2 rounded border border-slate-800">
              <span className="text-slate-500 text-[10px] block">CONFIDENCE</span>
              <span className="text-slate-200 font-bold text-sm">
                {(activeTarget.confidence * 100).toFixed(0)}%
              </span>
            </div>

            <div className="bg-slate-900/80 p-2 rounded border border-slate-800">
              <span className="text-slate-500 text-[10px] block">CENTER ERROR</span>
              <span className="text-cyan-400 font-semibold text-xs">
                Δx: {activeTarget.error_px?.[0]?.toFixed(0) ?? 0}px
                <br />
                Δy: {activeTarget.error_px?.[1]?.toFixed(0) ?? 0}px
              </span>
            </div>

            <div className="bg-slate-900/80 p-2 rounded border border-slate-800">
              <span className="text-slate-500 text-[10px] block">STATE</span>
              <span
                className={`font-bold text-xs uppercase ${
                  activeTarget.state === "TRACKING"
                    ? "text-emerald-400"
                    : activeTarget.state === "COASTING"
                    ? "text-amber-400"
                    : activeTarget.state === "HOLDING"
                    ? "text-cyan-400"
                    : activeTarget.state === "LOST"
                    ? "text-rose-400 animate-pulse"
                    : "text-slate-400"
                }`}
              >
                {activeTarget.state || (activeTarget.in_deadband ? "DEADBAND" : "TRACKING")}
              </span>
            </div>
          </div>
        ) : (
          <div className="text-center py-3 text-xs font-mono text-slate-500">
            No person locked. Select a detected person below or click on the video stream.
          </div>
        )}
      </div>

      {/* Detected Persons List (1-Click Target Selection) */}
      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs font-mono text-slate-400">
          <span className="flex items-center space-x-1.5">
            <Users className="w-3.5 h-3.5 text-slate-400" />
            <span>Detected Persons in Scene:</span>
          </span>
          <span className="text-slate-300 font-bold">{allDetections.length}</span>
        </div>

        {allDetections.length > 0 ? (
          <div className="max-h-40 overflow-y-auto space-y-1.5 pr-1 font-mono text-xs">
            {allDetections.map((person) => {
              const isSelected = activeTarget?.track_id === person.track_id;
              const width = Math.round(person.bbox[2] - person.bbox[0]);
              const height = Math.round(person.bbox[3] - person.bbox[1]);

              return (
                <div
                  key={person.track_id}
                  className={`flex items-center justify-between p-2 rounded-lg border transition-all ${
                    isSelected
                      ? "bg-emerald-950/70 border-emerald-500/50 text-emerald-300"
                      : "bg-slate-950 hover:bg-slate-800/80 border-slate-800 text-slate-300"
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <span className="w-6 h-6 rounded flex items-center justify-center bg-slate-900 border border-slate-700 text-slate-200 font-bold text-xs">
                      #{person.track_id}
                    </span>
                    <div>
                      <div className="flex items-center space-x-2">
                        <span className="font-semibold capitalize text-slate-200">
                          {person.class_name || "Person"}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {(person.confidence * 100).toFixed(0)}% conf
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-500">
                        Box: {width}x{height}px
                      </div>
                    </div>
                  </div>

                  <button
                    disabled={isEstopActive || isSelected}
                    onClick={() => onSelectTrackId(person.track_id)}
                    className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                      isSelected
                        ? "bg-emerald-600/30 text-emerald-400 border border-emerald-500/40 cursor-default"
                        : "bg-slate-800 hover:bg-emerald-600 hover:text-white text-slate-300 border border-slate-700"
                    }`}
                  >
                    {isSelected ? "LOCKED" : "SELECT & TRACK"}
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="p-3 text-center rounded bg-slate-950 border border-dashed border-slate-800 text-slate-500 font-mono text-xs">
            Awaiting detection telemetry...
          </div>
        )}
      </div>
    </div>
  );
}
