"""
SmartVision - Interactive CLI Person Tracking Demonstration
Supports real-time mouse-click target locking, auto-track heuristics, and keyboard controls.
Usage:
    python -m vision.tracking.demo
    python -m vision.tracking.demo --synthetic
    python -m vision.tracking.demo --headless --duration 3.0
"""

import argparse
import logging
import os
from pathlib import Path
import sys
import time
from typing import Optional

# Ensure smartvision root is on sys.path
_current_dir = Path(__file__).resolve().parent
_smartvision_root = _current_dir.parent.parent
if str(_smartvision_root) not in sys.path:
    sys.path.insert(0, str(_smartvision_root))

import cv2
import numpy as np

from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.detection.factory import create_detector
from vision.tracking.pipeline import TrackingPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SmartVision.TrackingDemo")


def run_demo(args: argparse.Namespace) -> int:
    """Runs the interactive tracking preview demonstration."""
    print("======================================================================")
    print("      SmartVision - Person Detection & Autonomous Tracking Demo       ")
    print("======================================================================")
    print("Controls:")
    print("  [Mouse Click] : Select & lock onto person target at coordinates")
    print("  [A]           : Auto-track primary person (largest bounding box)")
    print("  [M]           : Manual / Idle mode (unlock and stop tracking)")
    print("  [C]           : Center servos to (90.0°, 90.0°)")
    print("  [S]           : Save snapshot image to 'captures/'")
    print("  [H]           : Toggle tactical HUD overlay")
    print("  [1 - 9]       : Directly select & lock track ID 1 through 9")
    print("  [Q] or [ESC]  : Quit cleanly")
    print("======================================================================")

    # 1. Setup Camera Configuration & Service
    backend = CameraBackend.SYNTHETIC if args.synthetic else CameraBackend.AUTO
    cam_config = CameraConfig(
        device_index=args.camera,
        width=args.width,
        height=args.height,
        fps=args.fps,
        backend=backend,
    )
    cam_service = CameraService(cam_config)

    # 2. Setup Detector
    detector_mode = "yolo" if args.yolo else ("mock" if args.mock else "auto")
    detector = create_detector(
        mode=detector_mode,
        model_path=args.model,
        conf_thresh=args.conf,
        mock_mode=args.mock_mode,
    )
    logger.info("Using Detector: %s", detector.name)

    # 3. Setup Tracking Pipeline
    pipeline = TrackingPipeline(
        detector=detector,
        frame_width=args.width,
        frame_height=args.height,
        enable_hud=True,
    )

    # 4. Start Camera Service
    cam_service.start()
    logger.info("Camera service active. Video source: %s (Synthetic=%s)", cam_service.config.device_index, cam_service.is_synthetic)

    window_name = "SmartVision Person Tracking Engine"
    mouse_click_coords = [None]

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            mouse_click_coords[0] = (x, y)

    if not args.headless:
        cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(window_name, on_mouse)

    start_time = time.time()
    frames_processed = 0
    captures_dir = Path("captures")
    captures_dir.mkdir(exist_ok=True)

    try:
        while True:
            # Check duration limit (for tests/CI)
            elapsed = time.time() - start_time
            if args.duration and elapsed >= args.duration:
                logger.info("Duration limit reached (%.1fs). Exiting cleanly.", elapsed)
                break

            # Handle mouse click target selection
            if mouse_click_coords[0] is not None:
                mx, my = mouse_click_coords[0]
                mouse_click_coords[0] = None
                locked_id = pipeline.click_to_track(mx, my)
                if locked_id is not None:
                    logger.info("Mouse locked onto Track ID: %d", locked_id)
                else:
                    logger.info("No person detected near click (%d, %d)", mx, my)

            # Ingest video frame
            success, frame, metadata = cam_service.get_frame(timeout=0.5)
            if not success or frame is None:
                time.sleep(0.01)
                continue

            frames_processed += 1

            # Process frame through vision & tracking pipeline
            ts_cap = metadata.timestamp_utc * 1000.0 if hasattr(metadata, "timestamp_utc") else time.time() * 1000.0
            result = pipeline.process_frame(frame, timestamp_captured_ms=ts_cap)

            # If movement command eligible to dispatch, log or transmit
            if result.control_output.should_dispatch_command:
                servo_cmd = result.control_output.to_servo_command_payload()
                if frames_processed % 30 == 0:
                    logger.info(
                        "Command [20Hz]: Pan=%.1f°, Tilt=%.1f° (Err: X=%+.1f, Y=%+.1f px)",
                        servo_cmd["pan"],
                        servo_cmd["tilt"],
                        result.control_output.raw_error_x,
                        result.control_output.raw_error_y,
                    )

            if args.headless:
                # In headless mode, sleep slightly to emulate frame rate
                time.sleep(1.0 / max(1.0, args.fps))
                continue

            # Display frame in OpenCV window
            cv2.imshow(window_name, result.frame_annotated)
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):  # ESC or Q
                logger.info("Quit command received.")
                break
            elif key in (ord("a"), ord("A")):
                sel_id = pipeline.auto_track_first(strategy="largest")
                logger.info("Auto-track engaged on primary target: ID %s", sel_id)
            elif key in (ord("m"), ord("M")):
                pipeline.stop_tracking()
                logger.info("Switched to Manual / Idle mode.")
            elif key in (ord("c"), ord("C")):
                pipeline.center_servos()
                logger.info("Centered servos to (90.0°, 90.0°).")
            elif key in (ord("h"), ord("H")):
                pipeline.set_hud_enabled(not pipeline.enable_hud)
                logger.info("Toggled HUD overlay: %s", pipeline.enable_hud)
            elif key in (ord("s"), ord("S")):
                snap_path = captures_dir / f"track_snapshot_{int(time.time())}.jpg"
                cv2.imwrite(str(snap_path), result.frame_annotated)
                logger.info("Snapshot saved to %s", snap_path)
            elif ord("1") <= key <= ord("9"):
                target_num = key - ord("0")
                pipeline.select_track_id(target_num)
                logger.info("Selected Track ID: %d", target_num)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        cam_service.stop()
        if not args.headless:
            cv2.destroyAllWindows()
        logger.info("Tracking demo terminated. Processed %d frames.", frames_processed)

    return 0


def main():
    parser = argparse.ArgumentParser(description="SmartVision Interactive Person Tracking Demo")
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index (default: 0)")
    parser.add_argument("--width", type=int, default=640, help="Frame width (default: 640)")
    parser.add_argument("--height", type=int, default=480, help="Frame height (default: 480)")
    parser.add_argument("--fps", type=float, default=30.0, help="Camera FPS (default: 30.0)")
    parser.add_argument("--synthetic", action="store_true", help="Force synthetic test pattern fallback")
    parser.add_argument("--mock", action="store_true", help="Force mock person detector")
    parser.add_argument("--yolo", action="store_true", help="Require YOLO person detector")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Path to YOLO weights")
    parser.add_argument("--conf", type=float, default=0.35, help="Detection confidence threshold")
    parser.add_argument("--mock-mode", type=str, default="synthetic_sync", help="Mock pattern: synthetic_sync, multi_person, single_bounce")
    parser.add_argument("--headless", action="store_true", help="Run without opening GUI window (for SSH/CI)")
    parser.add_argument("--duration", type=float, default=None, help="Exit after N seconds")
    args = parser.parse_args()

    sys.exit(run_demo(args))


if __name__ == "__main__":
    main()
