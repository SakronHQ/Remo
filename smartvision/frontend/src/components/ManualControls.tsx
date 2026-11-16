"use client";

import React, { useCallback, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Compass,
  Gauge,
  HelpCircle,
  Move,
  RotateCcw,
  Zap,
} from "lucide-react";
import { CALIBRATED_BOUNDS, ServosTelemetry } from "../types/protocol";

interface ManualControlsProps {
  servosTelemetry?: ServosTelemetry | null;
  isEstopActive: boolean;
  onJog: (deltaPan: number, deltaTilt: number, speed: number) => void;
  onMoveAbsolute: (pan: number, tilt: number, speed: number) => void;
  onCenter: (speed: number) => void;
}

export function ManualControls({
  servosTelemetry,
  isEstopActive,
  onJog,
  onMoveAbsolute,
  onCenter,
}: ManualControlsProps) {
  const [speed, setSpeed] = useState<number>(0.5);
  const [stepDeg, setStepDeg] = useState<number>(5.0);
  const [isDraggingJoystick, setIsDraggingJoystick] = useState<boolean>(false);
  const [joystickPos, setJoystickPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const joystickRef = useRef<HTMLDivElement>(null);
  const lastJogRef = useRef<number>(0);

  const currentPan = servosTelemetry?.pan_angle ?? 90.0;
  const currentTilt = servosTelemetry?.tilt_angle ?? 90.0;

  // Safe boundaries calculation for progress bar gauges
  const panPercent = Math.min(
    100,
    Math.max(
      0,
      ((currentPan - CALIBRATED_BOUNDS.panMin) /
        (CALIBRATED_BOUNDS.panMax - CALIBRATED_BOUNDS.panMin)) *
        100
    )
  );

  const tiltPercent = Math.min(
    100,
    Math.max(
      0,
      ((currentTilt - CALIBRATED_BOUNDS.tiltMin) /
        (CALIBRATED_BOUNDS.tiltMax - CALIBRATED_BOUNDS.tiltMin)) *
        100
    )
  );

  // Virtual Joystick Pointer Handlers
  const handleJoystickPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isEstopActive) return;
    setIsDraggingJoystick(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    handleJoystickMove(e);
  };

  const handleJoystickMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!isDraggingJoystick || !joystickRef.current) return;
    const rect = joystickRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const dx = e.clientX - centerX;
    const dy = e.clientY - centerY;
    const maxRadius = rect.width / 2 - 16;
    const distance = Math.hypot(dx, dy);

    let normX = dx;
    let normY = dy;
    if (distance > maxRadius) {
      normX = (dx / distance) * maxRadius;
      normY = (dy / distance) * maxRadius;
    }

    setJoystickPos({ x: normX, y: normY });

    // Send throttled jog command (~15 Hz)
    const now = performance.now();
    if (now - lastJogRef.current > 65) {
      lastJogRef.current = now;
      const panJog = (normX / maxRadius) * stepDeg;
      const tiltJog = -(normY / maxRadius) * stepDeg; // Inverted Y for intuitive pitch up
      if (Math.abs(panJog) > 0.5 || Math.abs(tiltJog) > 0.5) {
        onJog(Number(panJog.toFixed(1)), Number(tiltJog.toFixed(1)), speed);
      }
    }
  };

  const handleJoystickPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    setIsDraggingJoystick(false);
    setJoystickPos({ x: 0, y: 0 });
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {}
  };

  return (
    <div className="w-full rounded-xl bg-slate-900 border border-slate-800 p-4 shadow-xl flex flex-col space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2.5">
        <div className="flex items-center space-x-2">
          <Move className="w-4 h-4 text-emerald-400" />
          <h3 className="font-mono text-sm font-bold uppercase tracking-wider text-slate-100">
            Manual Pan / Tilt Gimbal
          </h3>
        </div>
        <div className="flex items-center space-x-1.5 text-[11px] font-mono text-slate-400">
          <span>WASD / Arrow Keys</span>
        </div>
      </div>

      {/* Servo Angle Gauges & Boundary Limits */}
      <div className="grid grid-cols-2 gap-3 text-xs font-mono">
        {/* Pan Angle */}
        <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span>AZIMUTH (PAN)</span>
            <span className="font-bold text-emerald-400">{currentPan.toFixed(1)}°</span>
          </div>
          <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden relative">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-75"
              style={{ width: `${panPercent}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-slate-500 mt-1">
            <span>{CALIBRATED_BOUNDS.panMin}°</span>
            <span>Center (90°)</span>
            <span>{CALIBRATED_BOUNDS.panMax}°</span>
          </div>
        </div>

        {/* Tilt Angle */}
        <div className="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-1">
            <span>ELEVATION (TILT)</span>
            <span className="font-bold text-cyan-400">{currentTilt.toFixed(1)}°</span>
          </div>
          <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden relative">
            <div
              className="h-full bg-cyan-500 rounded-full transition-all duration-75"
              style={{ width: `${tiltPercent}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-slate-500 mt-1">
            <span>{CALIBRATED_BOUNDS.tiltMin}°</span>
            <span>Level (90°)</span>
            <span>{CALIBRATED_BOUNDS.tiltMax}°</span>
          </div>
        </div>
      </div>

      {/* D-Pad & Virtual Joystick Center Console */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-center">
        {/* Directional D-Pad */}
        <div className="flex flex-col items-center justify-center p-3 bg-slate-950 rounded-xl border border-slate-800/80">
          <span className="text-[11px] font-mono text-slate-400 mb-2 uppercase">
            Directional D-Pad
          </span>
          <div className="grid grid-cols-3 gap-2 w-36 h-36">
            <div />
            {/* Tilt Up */}
            <button
              disabled={isEstopActive}
              onClick={() => onJog(0, stepDeg, speed)}
              title="Tilt Up"
              className="flex items-center justify-center rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-cyan-600 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors border border-slate-700 shadow"
            >
              <ArrowUp className="w-5 h-5" />
            </button>
            <div />

            {/* Pan Left */}
            <button
              disabled={isEstopActive}
              onClick={() => onJog(-stepDeg, 0, speed)}
              title="Pan Left"
              className="flex items-center justify-center rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-emerald-600 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors border border-slate-700 shadow"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>

            {/* Center Home */}
            <button
              disabled={isEstopActive}
              onClick={() => onCenter(speed)}
              title="Return to Home Center (90°, 90°)"
              className="flex flex-col items-center justify-center rounded-lg bg-emerald-950/80 hover:bg-emerald-900 active:bg-emerald-700 disabled:opacity-40 text-emerald-400 border border-emerald-500/40 transition-colors shadow font-mono text-[10px] font-bold"
            >
              <Compass className="w-4 h-4 mb-0.5" />
              <span>HOME</span>
            </button>

            {/* Pan Right */}
            <button
              disabled={isEstopActive}
              onClick={() => onJog(stepDeg, 0, speed)}
              title="Pan Right"
              className="flex items-center justify-center rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-emerald-600 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors border border-slate-700 shadow"
            >
              <ArrowRight className="w-5 h-5" />
            </button>

            <div />
            {/* Tilt Down */}
            <button
              disabled={isEstopActive}
              onClick={() => onJog(0, -stepDeg, speed)}
              title="Tilt Down"
              className="flex items-center justify-center rounded-lg bg-slate-800 hover:bg-slate-700 active:bg-cyan-600 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors border border-slate-700 shadow"
            >
              <ArrowDown className="w-5 h-5" />
            </button>
            <div />
          </div>
        </div>

        {/* Virtual 2-Axis Joystick */}
        <div className="flex flex-col items-center justify-center p-3 bg-slate-950 rounded-xl border border-slate-800/80">
          <span className="text-[11px] font-mono text-slate-400 mb-2 uppercase">
            Proportional Joystick
          </span>
          <div
            ref={joystickRef}
            onPointerDown={handleJoystickPointerDown}
            onPointerMove={handleJoystickMove}
            onPointerUp={handleJoystickPointerUp}
            className={`relative w-36 h-36 rounded-full bg-slate-900 border-2 ${
              isDraggingJoystick
                ? "border-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
                : "border-slate-700"
            } flex items-center justify-center touch-none cursor-grab active:cursor-grabbing select-none`}
          >
            {/* Crosshair guide lines */}
            <div className="absolute inset-x-2 h-px bg-slate-800 pointer-events-none" />
            <div className="absolute inset-y-2 w-px bg-slate-800 pointer-events-none" />
            <div className="w-16 h-16 rounded-full border border-dashed border-slate-700 pointer-events-none" />

            {/* Joystick Thumb Stick */}
            <div
              className={`w-10 h-10 rounded-full transition-transform duration-75 shadow-lg flex items-center justify-center ${
                isDraggingJoystick
                  ? "bg-emerald-500 text-slate-950 scale-110"
                  : "bg-slate-700 hover:bg-slate-600 text-slate-300"
              }`}
              style={{
                transform: `translate(${joystickPos.x}px, ${joystickPos.y}px)`,
              }}
            >
              <Move className="w-4 h-4" />
            </div>
          </div>
        </div>
      </div>

      {/* Speed & Step Size Sliders */}
      <div className="space-y-3 pt-1">
        {/* Speed Adjustment Slider */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-300">
            <span className="flex items-center space-x-1.5">
              <Gauge className="w-3.5 h-3.5 text-slate-400" />
              <span>Velocity Factor:</span>
            </span>
            <span className="text-emerald-400 font-semibold">{speed.toFixed(2)}x</span>
          </div>
          <input
            type="range"
            min="0.1"
            max="1.0"
            step="0.05"
            value={speed}
            disabled={isEstopActive}
            onChange={(e) => setSpeed(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500 disabled:opacity-40"
          />
          <div className="flex justify-between text-[10px] font-mono text-slate-500">
            <span>Slow (0.1x)</span>
            <span>Default (0.5x)</span>
            <span>Fast (1.0x)</span>
          </div>
        </div>

        {/* Step Angle Adjustment */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs font-mono text-slate-300">
            <span className="flex items-center space-x-1.5">
              <Zap className="w-3.5 h-3.5 text-slate-400" />
              <span>D-Pad Jog Step:</span>
            </span>
            <span className="text-cyan-400 font-semibold">{stepDeg.toFixed(1)}°</span>
          </div>
          <div className="grid grid-cols-4 gap-2 pt-0.5">
            {[1.0, 2.5, 5.0, 10.0].map((deg) => (
              <button
                key={deg}
                disabled={isEstopActive}
                onClick={() => setStepDeg(deg)}
                className={`py-1 rounded text-xs font-mono font-medium transition-colors ${
                  stepDeg === deg
                    ? "bg-cyan-950 text-cyan-300 border border-cyan-500/50"
                    : "bg-slate-800 hover:bg-slate-700 text-slate-400 border border-slate-700"
                }`}
              >
                {deg}°
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
