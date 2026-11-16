"""
SmartVision - Local Live Camera Preview Utility
Interactive preview CLI displaying live camera feed, real-time FPS & latency HUD,
snapshot capture, and keyboard controls. Supports headless CI operation.
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys
import time
from typing import Optional

import cv2
import numpy as np

from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.camera.stream import draw_hud_overlay


def run_preview(
    config: CameraConfig,
    headless: bool = False,
    duration: Optional[float] = None,
    snapshot_dir: str = "captures",
) -> None:
    """
    Runs the live preview loop with HUD overlay and keyboard interaction.
    """
    os.makedirs(snapshot_dir, exist_ok=True)
    window_name = "SmartVision Camera Preview - [Q: Quit | S: Snapshot | F: Toggle Fallback | H: HUD]"

    show_hud = True
    snapshot_notice_time = 0.0
    snapshot_notice_text = ""
    is_gui_available = not headless

    start_time = time.time()

    print("=" * 78)
    print("                SMARTVISION CAMERA PREVIEW RUNTIME")
    print("=" * 78)
    print(f"  Target Device Index : {config.device_index}")
    print(f"  Target Resolution   : {config.width}x{config.height}")
    print(f"  Target FPS          : {config.fps}")
    print(f"  FourCC Format       : {config.fourcc}")
    print(f"  Synthetic Fallback  : {config.enable_synthetic_fallback}")
    print(f"  Headless Mode       : {headless}")
    print("=" * 78)
    print("  Controls: [Q/ESC] Quit | [S] Snapshot | [F] Fallback | [H] HUD Toggle")
    print("=" * 78)

    service = CameraService(config)
    service.start()

    try:
        frame_count = 0
        last_frame_id: Optional[int] = None
        while service.is_running:
            now = time.time()
            if duration is not None and (now - start_time) >= duration:
                print(f"\n[Preview] Reached duration limit ({duration}s). Stopping cleanly.")
                break

            # Fetch freshest frame without starving concurrent consumers
            success, frame, metadata = service.get_frame(
                timeout=0.5,
                last_frame_id=last_frame_id,
            )
            if not success or frame is None:
                time.sleep(0.01)
                continue

            if metadata:
                last_frame_id = metadata.frame_id

            frame_count += 1
            stats = service.get_stats()

            # Headless console logging mode
            if not is_gui_available:
                if frame_count % 30 == 0 or frame_count == 1:
                    src = stats.get("source", "unknown")
                    fps = stats.get("fps_actual", 0.0)
                    drops = stats.get("dropped_frames", 0)
                    total = stats.get("total_frames", 0)
                    uptime = stats.get("uptime_seconds", 0.0)
                    print(
                        f"  [FRAME {total:05d}] FPS: {fps:4.1f} | Drops: {drops} | "
                        f"Source: {src} | Uptime: {uptime:.1f}s",
                        end="\r",
                        flush=True,
                    )
                time.sleep(0.005)
                continue

            # Interactive GUI mode
            display_frame = frame.copy()
            if show_hud:
                display_frame = draw_hud_overlay(display_frame, stats)

            # Draw snapshot notification if recently triggered
            if (now - snapshot_notice_time) < 2.0:
                cv2.putText(
                    display_frame,
                    snapshot_notice_text,
                    (20, config.height - 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.60,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )

            # Display window
            try:
                cv2.imshow(window_name, display_frame)
                key = cv2.waitKey(1) & 0xFF
            except cv2.error as e:
                print(f"\n[WARN] OpenCV GUI unavailable ({e}). Switching to headless mode.")
                is_gui_available = False
                continue

            # Keybindings
            if key in (ord("q"), ord("Q"), 27):  # 'q' or ESC
                print("\n[Preview] Quit requested by operator.")
                break
            elif key in (ord("s"), ord("S")):  # Snapshot
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                snap_path = Path(snapshot_dir) / f"snapshot_{timestamp_str}.jpg"
                cv2.imwrite(str(snap_path), frame)
                snapshot_notice_time = now
                snapshot_notice_text = f"SNAPSHOT SAVED: {snap_path.name}"
                print(f"\n[Snapshot] Saved frame to {snap_path}")
            elif key in (ord("f"), ord("F")):  # Toggle forced synthetic fallback
                new_state = not service._is_forced_synthetic
                service.set_forced_synthetic(new_state)
                mode_label = "FORCED SYNTHETIC" if new_state else "AUTO HARDWARE"
                print(f"\n[Fallback] Toggled mode -> {mode_label}")
            elif key in (ord("h"), ord("H")):  # Toggle HUD
                show_hud = not show_hud

    except KeyboardInterrupt:
        print("\n[Preview] Interrupted by Ctrl+C.")
    finally:
        service.stop()
        if is_gui_available:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        print("\n[Preview] Preview utility shutdown complete.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartVision Local PC Camera Preview Utility")
    parser.add_argument("--index", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument("--width", type=int, default=640, help="Frame width in pixels (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Frame height in pixels (default: 480)")
    parser.add_argument("--fps", type=float, default=30.0, help="Target capture FPS (default: 30.0)")
    parser.add_argument("--fourcc", type=str, default="MJPG", help="FourCC codec (default: MJPG)")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic test pattern fallback")
    parser.add_argument("--headless", action="store_true", help="Run without graphical display window")
    parser.add_argument("--duration", type=float, default=None, help="Automatically exit after N seconds")
    parser.add_argument("--snapshot-dir", type=str, default="captures", help="Directory to save snapshots")

    args = parser.parse_args()

    backend = CameraBackend.SYNTHETIC if args.synthetic else CameraBackend.AUTO
    config = CameraConfig(
        device_index=args.index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        fourcc=args.fourcc,
        backend=backend,
        enable_synthetic_fallback=True,
    )

    run_preview(
        config=config,
        headless=args.headless,
        duration=args.duration,
        snapshot_dir=args.snapshot_dir,
    )


if __name__ == "__main__":
    main()
