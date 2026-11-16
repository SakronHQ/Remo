"use client";

import { useEffect, useRef } from "react";

interface KeyboardControlsOptions {
  enabled?: boolean;
  stepDeg?: number;
  speed?: number;
  onJog: (deltaPan: number, deltaTilt: number, speed: number) => void;
  onCenter?: () => void;
}

export function useKeyboardControls({
  enabled = true,
  stepDeg = 5.0,
  speed = 0.5,
  onJog,
  onCenter,
}: KeyboardControlsOptions) {
  const lastPressRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore keystrokes if the user is typing in an input, textarea, or button focus
      const activeTag = document.activeElement?.tagName?.toLowerCase();
      if (activeTag === "input" || activeTag === "textarea" || activeTag === "select") {
        return;
      }

      const now = performance.now();
      // Throttle key repeat to ~15 Hz
      if (now - lastPressRef.current < 65) {
        return;
      }

      let deltaPan = 0;
      let deltaTilt = 0;

      switch (e.key) {
        case "ArrowLeft":
        case "a":
        case "A":
          deltaPan = -stepDeg;
          break;
        case "ArrowRight":
        case "d":
        case "D":
          deltaPan = stepDeg;
          break;
        case "ArrowUp":
        case "w":
        case "W":
          deltaTilt = stepDeg;
          break;
        case "ArrowDown":
        case "s":
        case "S":
          deltaTilt = -stepDeg;
          break;
        case "c":
        case "C":
          if (onCenter) {
            e.preventDefault();
            onCenter();
            return;
          }
          break;
        default:
          return;
      }

      if (deltaPan !== 0 || deltaTilt !== 0) {
        e.preventDefault();
        lastPressRef.current = now;
        onJog(deltaPan, deltaTilt, speed);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [enabled, stepDeg, speed, onJog, onCenter]);
}
