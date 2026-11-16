# SmartVision Next.js Operator Dashboard

## Overview
The SmartVision operator frontend is built with **Next.js 14+ (App Router)**, **React**, **TypeScript**, and **Tailwind CSS**. It provides an intuitive, real-time command interface for operators to monitor live video, review detections, select targets via click-to-lock, jog servos manually, and monitor system telemetry.

## Key Dashboard Capabilities
1. **Live Video with Synchronized HTML5 Canvas Overlay:**
   - Plays HTTP multipart MJPEG video from `/api/v1/stream/video.mjpeg`.
   - Renders synchronized HTML5 Canvas overlays with bounding boxes, track IDs, target lock reticle, and central deadband indicators.
2. **Interactive Click-to-Lock Target Selection:**
   - Operators can click on any detected person bounding box directly on the video viewport. The hit-test maps canvas coordinates to the detected `track_id` and dispatches `track.select_id` to lock tracking onto that target.
3. **Manual Pan/Tilt Controls:**
   - 4-way directional D-pad, virtual joystick, and discrete angle sliders.
   - Speed adjustment slider mapping normalized speed to servo angular velocities.
   - Quick "Center" home button ($90.0^\circ, 90.0^\circ$).
   - 20 Hz input throttling via `useThrottledCallback` hook to avoid network queue flooding.
4. **Telemetry Gauges & Status Indicators:**
   - HC-SR04 ultrasonic distance bar with dynamic color grading (Green $> 40\text{ cm}$, Yellow $20-40\text{ cm}$, Red $< 20\text{ cm}$).
   - HC-SR501 PIR motion indicator with animated pulse badge.
   - Real-time servo angle dials and Wi-Fi RSSI indicator.
5. **Emergency Stop (E-Stop):**
   - Prominent red kill-switch dispatching `sys.safestop` to immediately halt all motion.

## Upcoming Phase 5 Implementation Structure
```
frontend/
├── package.json               # Next.js 14, React 18, Tailwind, Lucide icons
├── tsconfig.json
├── tailwind.config.ts
└── src/
    ├── app/
    │   ├── layout.tsx         # Root layout & global header
    │   ├── page.tsx           # Main split-screen dashboard view
    │   └── globals.css        # Tailwind styles & theme variables
    ├── components/
    │   ├── VideoPlayer.tsx    # Live MJPEG stream display
    │   ├── CanvasOverlay.tsx  # HTML5 Canvas vector overlay & click-to-lock
    │   ├── PanTiltControls.tsx# Virtual D-pad, joystick & manual sliders
    │   ├── TelemetryPanel.tsx # Ultrasonic distance & PIR cards
    │   ├── ModeSelector.tsx   # Manual / Auto-Track / Patrol tabs
    │   ├── EventLog.tsx       # Real-time event audit log
    │   └── StatusHeader.tsx   # Connection indicators & E-Stop button
    ├── hooks/
    │   ├── useWebSocket.ts    # Resilient WebSocket hook with auto-reconnect
    │   └── useKeyboardControls.ts # Arrow/WASD keyboard bindings
    └── types/
        └── protocol.ts        # TypeScript interfaces matching backend schemas
```
