"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Crosshair,
  Maximize2,
  Minimize2,
  RefreshCw,
  Sliders,
  Target,
  Video,
  VideoOff,
} from "lucide-react";
import {
  ActiveTarget,
  DetectedPerson,
  TrackFrameTargetPayload,
  TrackingMode,
  TrackTargetSelectPayload,
} from "../types/protocol";

interface VideoViewportProps {
  streamUrl?: string;
  frameTarget: TrackFrameTargetPayload | null;
  trackingMode: TrackingMode;
  isEstopActive: boolean;
  fps?: number;
  latencyMs?: number;
  onTargetSelect?: (payload: TrackTargetSelectPayload) => void;
  onSelectTrackId?: (trackId: number) => void;
  onClickToTrack?: (clickX: number, clickY: number) => void;
}

export function VideoViewport({
  streamUrl = "/api/v1/stream/video.mjpeg",
  frameTarget,
  trackingMode,
  isEstopActive,
  fps = 30,
  latencyMs = 0,
  onTargetSelect,
  onSelectTrackId,
  onClickToTrack,
}: VideoViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  const [streamError, setStreamError] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showOverlays, setShowOverlays] = useState(true);
  const [showDeadband, setShowDeadband] = useState(true);
  const [clickRipple, setClickRipple] = useState<{ x: number; y: number; time: number } | null>(null);

  const frameWidth = frameTarget?.frame_dimensions?.width || 640;
  const frameHeight = frameTarget?.frame_dimensions?.height || 480;

  // Render synchronized vector HUD over video
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!showOverlays) return;

    const width = canvas.width;
    const height = canvas.height;
    const scaleX = width / frameWidth;
    const scaleY = height / frameHeight;
    const centerX = width / 2;
    const centerY = height / 2;

    // 1. Subtle Center Crosshair
    ctx.strokeStyle = "rgba(0, 229, 255, 0.35)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);

    ctx.beginPath();
    ctx.moveTo(centerX - 30, centerY);
    ctx.lineTo(centerX + 30, centerY);
    ctx.moveTo(centerX, centerY - 30);
    ctx.lineTo(centerX, centerY + 30);
    ctx.stroke();
    ctx.setLineDash([]);

    // 2. Deadband Circle (Tolerance Zone)
    if (showDeadband) {
      const deadbandRadius = 25 * scaleX;
      ctx.strokeStyle = "rgba(16, 185, 129, 0.4)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(centerX, centerY, deadbandRadius, 0, 2 * Math.PI);
      ctx.stroke();

      ctx.fillStyle = "rgba(16, 185, 129, 0.05)";
      ctx.fill();
    }

    const activeTarget = frameTarget?.active_target;
    const detections = frameTarget?.all_detections || [];

    // 3. Render all detected bounding boxes
    detections.forEach((det: DetectedPerson) => {
      const isLocked = activeTarget && activeTarget.track_id === det.track_id;
      if (isLocked) return; // Rendered separately below

      const [x1, y1, x2, y2] = det.bbox;
      const rx1 = x1 * scaleX;
      const ry1 = y1 * scaleY;
      const rw = (x2 - x1) * scaleX;
      const rh = (y2 - y1) * scaleY;

      // Unlocked person box
      ctx.strokeStyle = "rgba(148, 163, 184, 0.75)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(rx1, ry1, rw, rh);

      // Label badge
      const label = `ID:${det.track_id} ${(det.confidence * 100).toFixed(0)}%`;
      ctx.font = "10px ui-monospace, monospace";
      ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
      ctx.fillRect(rx1, Math.max(0, ry1 - 18), 70, 16);

      ctx.fillStyle = "#cbd5e1";
      ctx.fillText(label, rx1 + 4, Math.max(12, ry1 - 6));
    });

    // 4. Render Active Locked Target Reticle
    if (activeTarget) {
      const [x1, y1, x2, y2] = activeTarget.bbox;
      const rx1 = x1 * scaleX;
      const ry1 = y1 * scaleY;
      const rw = (x2 - x1) * scaleX;
      const rh = (y2 - y1) * scaleY;

      const targetColor = isEstopActive
        ? "rgba(239, 68, 68, 0.9)"
        : activeTarget.in_deadband
        ? "rgba(16, 185, 129, 0.95)"
        : "rgba(0, 229, 255, 0.95)";

      // Target bounding box
      ctx.strokeStyle = targetColor;
      ctx.lineWidth = 2;
      ctx.strokeRect(rx1, ry1, rw, rh);

      // Reticle Corner Brackets
      const cornerLen = Math.min(rw * 0.25, 20);
      ctx.lineWidth = 3;
      ctx.strokeStyle = targetColor;

      // Top-Left
      ctx.beginPath();
      ctx.moveTo(rx1, ry1 + cornerLen);
      ctx.lineTo(rx1, ry1);
      ctx.lineTo(rx1 + cornerLen, ry1);
      ctx.stroke();

      // Top-Right
      ctx.beginPath();
      ctx.moveTo(rx1 + rw - cornerLen, ry1);
      ctx.lineTo(rx1 + rw, ry1);
      ctx.lineTo(rx1 + rw, ry1 + cornerLen);
      ctx.stroke();

      // Bottom-Left
      ctx.beginPath();
      ctx.moveTo(rx1, ry1 + rh - cornerLen);
      ctx.lineTo(rx1, ry1 + rh);
      ctx.lineTo(rx1 + cornerLen, ry1 + rh);
      ctx.stroke();

      // Bottom-Right
      ctx.beginPath();
      ctx.moveTo(rx1 + rw - cornerLen, ry1 + rh);
      ctx.lineTo(rx1 + rw, ry1 + rh);
      ctx.lineTo(rx1 + rw, ry1 + rh - cornerLen);
      ctx.stroke();

      // Target Center Crosshair
      const [cx, cy] = activeTarget.centroid;
      const rcx = cx * scaleX;
      const rcy = cy * scaleY;

      ctx.fillStyle = targetColor;
      ctx.beginPath();
      ctx.arc(rcx, rcy, 3, 0, 2 * Math.PI);
      ctx.fill();

      // Error line from frame center to target centroid
      ctx.strokeStyle = targetColor;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(rcx, rcy);
      ctx.stroke();
      ctx.setLineDash([]);

      // Top Header Tag
      const stateLabel = activeTarget.state || (activeTarget.in_deadband ? "LOCKED (DEADBAND)" : "TRACKING");
      const tagText = `LOCK #${activeTarget.track_id} [${stateLabel}] ${(activeTarget.confidence * 100).toFixed(0)}%`;
      ctx.font = "bold 11px ui-monospace, monospace";
      ctx.fillStyle = targetColor;
      ctx.fillRect(rx1, Math.max(0, ry1 - 22), 160, 20);

      ctx.fillStyle = "#020617";
      ctx.fillText(tagText, rx1 + 6, Math.max(14, ry1 - 8));
    }

    // 5. Click ripple indicator
    if (clickRipple && Date.now() - clickRipple.time < 800) {
      const elapsed = Date.now() - clickRipple.time;
      const progress = elapsed / 800;
      const radius = 10 + progress * 35;
      const alpha = 1.0 - progress;

      ctx.strokeStyle = `rgba(0, 229, 255, ${alpha})`;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(clickRipple.x, clickRipple.y, radius, 0, 2 * Math.PI);
      ctx.stroke();
    }
  }, [frameTarget, frameWidth, frameHeight, showOverlays, showDeadband, isEstopActive, clickRipple]);

  // Handle Click-to-Track interaction on the video canvas
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const clickClientX = e.clientX - rect.left;
      const clickClientY = e.clientY - rect.top;

      // Scale to internal frame coordinates (e.g. 640x480)
      const scaleX = frameWidth / canvas.width;
      const scaleY = frameHeight / canvas.height;
      const frameX = clickClientX * scaleX;
      const frameY = clickClientY * scaleY;

      // Normalized coordinates [0.0, 1.0]
      const normX = Number((Math.max(0, Math.min(1, clickClientX / rect.width))).toFixed(4));
      const normY = Number((Math.max(0, Math.min(1, clickClientY / rect.height))).toFixed(4));

      setClickRipple({
        x: clickClientX,
        y: clickClientY,
        time: Date.now(),
      });

      // Hit-test against detected people
      const detections = frameTarget?.all_detections || [];
      let matchedTrackId: number | null = null;

      for (const det of detections) {
        const [x1, y1, x2, y2] = det.bbox;
        if (frameX >= x1 && frameX <= x2 && frameY >= y1 && frameY <= y2) {
          matchedTrackId = det.track_id;
          break;
        }
      }

      if (matchedTrackId !== null) {
        if (onSelectTrackId) {
          onSelectTrackId(matchedTrackId);
        } else if (onTargetSelect) {
          onTargetSelect({
            track_id: matchedTrackId,
            coordinates: [normX, normY],
            click_x: Math.round(frameX),
            click_y: Math.round(frameY),
          });
        }
      } else {
        if (onClickToTrack) {
          onClickToTrack(Math.round(frameX), Math.round(frameY));
        } else if (onTargetSelect) {
          onTargetSelect({
            coordinates: [normX, normY],
            click_x: Math.round(frameX),
            click_y: Math.round(frameY),
          });
        }
      }
    },
    [frameWidth, frameHeight, frameTarget, onClickToTrack, onSelectTrackId, onTargetSelect]
  );

  // Sync canvas size with image viewport
  const handleImageLoad = () => {
    setStreamError(false);
    updateCanvasDimensions();
  };

  const updateCanvasDimensions = () => {
    if (imgRef.current && canvasRef.current) {
      canvasRef.current.width = imgRef.current.clientWidth || 640;
      canvasRef.current.height = imgRef.current.clientHeight || 480;
    }
  };

  useEffect(() => {
    updateCanvasDimensions();
    const container = containerRef.current;
    if (!container) return;

    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => {
        updateCanvasDimensions();
      });
      ro.observe(container);
      return () => ro.disconnect();
    } else {
      window.addEventListener("resize", updateCanvasDimensions);
      return () => window.removeEventListener("resize", updateCanvasDimensions);
    }
  }, []);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch((err) => console.error(err));
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch((err) => console.error(err));
      setIsFullscreen(false);
    }
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full rounded-xl overflow-hidden bg-slate-950 border border-slate-800 shadow-2xl flex flex-col group select-none"
    >
      {/* HUD Header Toolbar */}
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between px-3 py-2 bg-gradient-to-b from-slate-950/90 to-transparent pointer-events-auto">
        <div className="flex items-center space-x-2">
          <div className="flex items-center space-x-1.5 px-2 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 backdrop-blur-md">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[11px] font-mono text-slate-200 uppercase font-semibold">
              LIVE MJPEG
            </span>
          </div>

          {/* FPS Counter */}
          <div className="flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 text-[11px] font-mono text-slate-300">
            <span>FPS:</span>
            <span className="text-emerald-400 font-semibold">{fps ? fps.toFixed(0) : "30"}</span>
          </div>

          {/* Connection Latency */}
          <div className="hidden xs:flex items-center space-x-1 px-2 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 text-[11px] font-mono text-slate-300">
            <span>LAT:</span>
            <span className="text-cyan-400 font-semibold">{latencyMs}ms</span>
          </div>

          <div className="hidden sm:flex items-center space-x-1.5 px-2 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 text-[11px] font-mono text-slate-300">
            <span>RES:</span>
            <span className="text-emerald-400">{frameWidth}x{frameHeight}</span>
          </div>

          <div className="hidden md:flex items-center space-x-1.5 px-2 py-0.5 rounded bg-slate-900/80 border border-slate-700/50 text-[11px] font-mono text-slate-300">
            <span>MODE:</span>
            <span className="uppercase text-cyan-400 font-semibold">{trackingMode}</span>
          </div>
        </div>

        {/* Viewport Control Toggles */}
        <div className="flex items-center space-x-1.5">
          <button
            onClick={() => setShowOverlays(!showOverlays)}
            title="Toggle Bounding Boxes & Reticle"
            className={`p-1.5 rounded transition-colors text-xs font-mono flex items-center space-x-1 ${
              showOverlays
                ? "bg-emerald-950/80 text-emerald-400 border border-emerald-500/40"
                : "bg-slate-900/80 text-slate-400 border border-slate-700/50"
            }`}
          >
            <Crosshair className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">HUD</span>
          </button>

          <button
            onClick={() => setShowDeadband(!showDeadband)}
            title="Toggle Deadband Tolerance Ring"
            className={`p-1.5 rounded transition-colors text-xs font-mono flex items-center space-x-1 ${
              showDeadband
                ? "bg-cyan-950/80 text-cyan-400 border border-cyan-500/40"
                : "bg-slate-900/80 text-slate-400 border border-slate-700/50"
            }`}
          >
            <Target className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={toggleFullscreen}
            title={isFullscreen ? "Exit Fullscreen" : "Fullscreen View"}
            className="p-1.5 rounded bg-slate-900/80 hover:bg-slate-800 text-slate-300 border border-slate-700/50 transition-colors"
          >
            {isFullscreen ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Video Stream & HTML5 Canvas Container */}
      <div className="relative w-full aspect-[4/3] bg-black flex items-center justify-center overflow-hidden">
        {/* Real Live MJPEG Stream */}
        {!streamError ? (
          <img
            ref={imgRef}
            src={streamUrl}
            alt="SmartVision Live Stream"
            className="w-full h-full object-contain pointer-events-none"
            onLoad={handleImageLoad}
            onError={() => setStreamError(true)}
          />
        ) : (
          /* High-Tech Fallback Simulated Radar Viewport when Stream is Offline */
          <div className="relative w-full h-full flex flex-col items-center justify-center bg-slate-950 text-slate-400">
            <div className="absolute inset-0 bg-[radial-gradient(#1e293b_1px,transparent_1px)] [background-size:16px_16px] opacity-40" />
            <div className="relative z-10 flex flex-col items-center p-6 text-center space-y-3">
              <div className="p-4 rounded-full bg-slate-900 border border-slate-800 text-slate-500">
                <VideoOff className="w-10 h-10 animate-pulse" />
              </div>
              <div>
                <div className="font-mono text-sm font-semibold text-slate-300 uppercase">
                  Video Feed Standby / Connecting
                </div>
                <div className="font-mono text-xs text-slate-500 mt-1">
                  Connecting to {streamUrl}
                </div>
              </div>
              <button
                onClick={() => setStreamError(false)}
                className="mt-2 flex items-center space-x-1.5 px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-mono transition-colors border border-slate-700"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry Stream</span>
              </button>
            </div>
          </div>
        )}

        {/* Overlay Canvas for Bounding Boxes, Target Reticle, and Click-to-Track */}
        <canvas
          ref={canvasRef}
          onClick={handleCanvasClick}
          className="absolute inset-0 w-full h-full cursor-crosshair z-10"
        />

        {/* E-Stop Visual Banner Overlay if Active */}
        {isEstopActive && (
          <div className="absolute inset-0 z-30 pointer-events-none flex items-center justify-center bg-rose-950/20 border-4 border-rose-500/80 animate-pulse">
            <div className="px-6 py-2 rounded-lg bg-rose-900/90 border border-rose-400 text-white font-mono font-bold text-sm tracking-widest shadow-2xl">
              EMERGENCY STOP ENGAGED
            </div>
          </div>
        )}
      </div>

      {/* Bottom Viewport HUD Info Bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-950/95 border-t border-slate-800/80 text-[11px] font-mono text-slate-400">
        <div className="flex items-center space-x-3">
          <span>
            TARGETS:{" "}
            <span className="text-slate-200 font-semibold">
              {frameTarget?.all_detections?.length || 0}
            </span>
          </span>
          <span>
            STATUS:{" "}
            <span
              className={`font-semibold ${
                frameTarget?.target_locked
                  ? "text-emerald-400"
                  : "text-amber-400"
              }`}
            >
              {frameTarget?.target_locked
                ? `LOCKED (ID #${frameTarget.active_target?.track_id})`
                : "SEARCHING"}
            </span>
          </span>
        </div>

        <div className="flex items-center space-x-2 text-[10px] text-slate-500">
          <span>Click anywhere to target lock</span>
        </div>
      </div>
    </div>
  );
}
