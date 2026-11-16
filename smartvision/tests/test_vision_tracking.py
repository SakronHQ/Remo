"""
test_vision_tracking.py
Automated Verification Suite for SmartVision Phase 5:
Computer Vision & Person Tracking Engine.

Validates:
1. PersonDetection models, bounding box geometry, centroids, and normalized coordinates.
2. Detector implementations: MockPersonDetector, YoloPersonDetector fallback, and DetectorFactory.
3. 8-dimensional BoxKalmanFilter state prediction, covariance updates, and numerical stability.
4. ByteTrack multi-object tracking: concurrent ID assignment, persistent tracking,
   two-stage association (low-confidence handling), temporary occlusion recovery, and pruning.
5. Target selection interface: click-to-track, direct ID locking, auto-track heuristics,
   and safe timeout progression (Coasting -> Holding -> Lost) without silent target jumping.
6. Dual-axis PID controller: hysteresis deadband (+-15px / +-25px), EMA smoothing (alpha=0.35),
   anti-windup clamping, slew rate limiting (80 deg/s), 20 Hz output rate limiting,
   and physical servo boundary clamping (15°–165° Pan, 60°–135° Tilt).
7. Closed-loop optical tracking convergence to within deadband in < 1.50 seconds.
8. Visual tactical HUD overlay rendering across varied tracking states.
9. Full TrackingPipeline integration and protocol compliance with docs/protocol.md.
"""

import json
import math
import os
import sys
import time
from typing import List, Optional, Tuple
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

# Ensure smartvision root is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from vision.camera.config import CameraBackend, CameraConfig
from vision.camera.service import CameraService
from vision.camera.synthetic import SyntheticTestPattern
from vision.detection.factory import create_detector
from vision.detection.mock_detector import MockPersonDetector
from vision.detection.types import PersonDetection
from vision.detection.yolo_detector import DetectorUnavailableError, YoloPersonDetector
from vision.tracking.bytetrack import ByteTracker, STrack, TrackState, bbox_ious, linear_assignment
from vision.tracking.hud import HUDOverlay
from vision.tracking.kalman import BoxKalmanFilter
from vision.tracking.pid_controller import (
    DualAxisTrackingController,
    EMASmoother,
    HysteresisDeadband,
    SingleAxisPID,
    TrackingControlOutput,
)
from vision.tracking.pipeline import TrackingPipeline, TrackingPipelineResult
from vision.tracking.target_selector import TargetSelectionResult, TargetSelector, TargetState


# ==============================================================================
# 1. Detection Data Model & Geometry Tests
# ==============================================================================

class TestPersonDetectionModel(unittest.TestCase):
    """Validates PersonDetection data structure, bbox ordering, and calculations."""

    def test_detection_attributes_and_centroid(self):
        det = PersonDetection(x1=100.0, y1=80.0, x2=220.0, y2=320.0, confidence=0.88)
        self.assertEqual(det.width, 120.0)
        self.assertEqual(det.height, 240.0)
        self.assertEqual(det.area, 120.0 * 240.0)
        self.assertAlmostEqual(det.aspect_ratio, 0.50, places=3)
        self.assertEqual(det.centroid, (160.0, 200.0))
        self.assertEqual(det.bbox, (100, 80, 220, 320))
        self.assertEqual(det.class_id, 0)
        self.assertEqual(det.class_name, "person")

    def test_inverted_coordinate_auto_normalization(self):
        """Ensures inverted coordinates (x2 < x1 or y2 < y1) are automatically corrected."""
        det = PersonDetection(x1=250.0, y1=300.0, x2=150.0, y2=100.0, confidence=0.75)
        self.assertEqual(det.x1, 150.0)
        self.assertEqual(det.x2, 250.0)
        self.assertEqual(det.y1, 100.0)
        self.assertEqual(det.y2, 300.0)
        self.assertEqual(det.width, 100.0)
        self.assertEqual(det.height, 200.0)

    def test_normalized_coordinates(self):
        det = PersonDetection(x1=160.0, y1=120.0, x2=480.0, y2=360.0, confidence=0.90)
        norm = det.normalized(frame_w=640, frame_h=480)
        self.assertAlmostEqual(norm[0], 0.25, places=3)
        self.assertAlmostEqual(norm[1], 0.25, places=3)
        self.assertAlmostEqual(norm[2], 0.75, places=3)
        self.assertAlmostEqual(norm[3], 0.75, places=3)

    def test_to_dict_serialization(self):
        det = PersonDetection(x1=50.0, y1=50.0, x2=150.0, y2=250.0, confidence=0.9234)
        d = det.to_dict(640, 480)
        self.assertEqual(d["class_id"], 0)
        self.assertEqual(d["class_name"], "person")
        self.assertEqual(d["confidence"], 0.9234)
        self.assertEqual(d["bbox"], [50, 50, 150, 250])
        self.assertEqual(d["centroid"], [100.0, 150.0])


# ==============================================================================
# 2. Detector Implementations & Factory Tests
# ==============================================================================

class TestPersonDetectors(unittest.TestCase):
    """Validates Mock detector, YOLO fallback, and DetectorFactory."""

    def test_mock_detector_manual_injection(self):
        mock = MockPersonDetector(mode="manual")
        injected = [
            PersonDetection(100, 100, 200, 300, 0.95),
            PersonDetection(300, 150, 400, 350, 0.30),
        ]
        mock.set_detections(injected)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Default conf thresh 0.35 should filter out the 0.30 detection
        dets = mock.detect(frame, conf_thresh=0.35)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0].confidence, 0.95)

        # Lower conf thresh includes both
        dets_all = mock.detect(frame, conf_thresh=0.20)
        self.assertEqual(len(dets_all), 2)

    def test_mock_detector_procedural_multi_person(self):
        mock = MockPersonDetector(mode="multi_person")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        dets = mock.detect(frame)
        self.assertGreaterEqual(len(dets), 1)
        for d in dets:
            self.assertEqual(d.class_name, "person")
            self.assertGreater(d.width, 0)
            self.assertGreater(d.height, 0)

    def test_mock_detector_synthetic_sync(self):
        pattern = SyntheticTestPattern(width=640, height=480, pattern="moving_target")
        frame, gt = pattern.generate_frame(t=0.5)

        mock = MockPersonDetector(mode="synthetic_sync")
        dets = mock.detect(frame)
        self.assertGreaterEqual(len(dets), 1)
        det = dets[0]
        # Detected box should be near ground truth target
        gt_cx, gt_cy = gt["centroid"]
        det_cx, det_cy = det.centroid
        self.assertLess(abs(det_cx - gt_cx), 25.0)
        self.assertLess(abs(det_cy - gt_cy), 25.0)

    def test_yolo_detector_missing_dependency_raises(self):
        """When ultralytics is not installed or fails, raises DetectorUnavailableError."""
        with self.assertRaises(DetectorUnavailableError):
            YoloPersonDetector(model_path="non_existent_weights_xyz.pt")

    def test_yolo_detector_mocked_ultralytics_inference(self):
        """Validates YOLO tensor parsing, COCO Class 0 filtering, and PersonDetection creation with mocked ultralytics."""
        mock_ultralytics = MagicMock()
        mock_yolo_cls = MagicMock()
        mock_ultralytics.YOLO = mock_yolo_cls

        mock_model_instance = MagicMock()
        mock_yolo_cls.return_value = mock_model_instance

        mock_result = MagicMock()
        mock_boxes = MagicMock()

        # Class 0 (person, conf 0.92) and Class 2 (car, conf 0.85)
        mock_boxes.xyxy.cpu.return_value.numpy.return_value = np.array([
            [100.0, 80.0, 200.0, 300.0],
            [300.0, 150.0, 500.0, 400.0],
        ])
        mock_boxes.conf.cpu.return_value.numpy.return_value = np.array([0.92, 0.85])
        mock_boxes.cls.cpu.return_value.numpy.return_value = np.array([0, 2])
        mock_boxes.__len__.return_value = 2

        mock_result.boxes = mock_boxes
        mock_model_instance.predict.return_value = [mock_result]

        with patch.dict(sys.modules, {"ultralytics": mock_ultralytics}):
            detector = YoloPersonDetector(model_path="yolov8n.pt", conf_thresh=0.40)
            self.assertTrue(detector.is_ready)

            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            dets = detector.detect(frame)

            # Strictly 1 detection (person, class 0), car (class 2) filtered out
            self.assertEqual(len(dets), 1)
            det = dets[0]
            self.assertEqual(det.class_id, 0)
            self.assertEqual(det.class_name, "person")
            self.assertAlmostEqual(det.confidence, 0.92, places=2)
            self.assertEqual(det.bbox, (100, 80, 200, 300))

    def test_detector_factory_auto_fallback(self):
        """Factory in 'auto' mode must gracefully return MockPersonDetector if YOLO fails."""
        detector = create_detector(mode="auto")
        self.assertIsNotNone(detector)
        self.assertTrue(detector.is_ready)
        self.assertIn("MockPersonDetector", detector.name)

    def test_detector_factory_explicit_mock(self):
        detector = create_detector(mode="mock", mock_mode="multi_person")
        self.assertIsInstance(detector, MockPersonDetector)
        self.assertIn("multi_person", detector.name)

    def test_detector_factory_invalid_mode(self):
        with self.assertRaises(ValueError):
            create_detector(mode="unsupported_quantum_mode")


# ==============================================================================
# 3. Kalman Filter & Motion Prediction Tests
# ==============================================================================

class TestKalmanFilter(unittest.TestCase):
    """Validates 8D Kalman filter initialization, prediction, and update."""

    def test_kalman_initiate_and_predict(self):
        kf = BoxKalmanFilter()
        # [cx, cy, aspect_ratio, height]
        measurement = np.array([320.0, 240.0, 0.5, 200.0], dtype=np.float64)
        mean, cov = kf.initiate(measurement)

        self.assertEqual(len(mean), 8)
        self.assertEqual(cov.shape, (8, 8))
        self.assertAlmostEqual(mean[0], 320.0)
        self.assertAlmostEqual(mean[1], 240.0)

        # Predict one step
        next_mean, next_cov = kf.predict(mean, cov)
        self.assertEqual(len(next_mean), 8)
        # Covariance uncertainty should grow after prediction
        self.assertGreaterEqual(np.trace(next_cov), np.trace(cov))

    def test_kalman_measurement_update(self):
        kf = BoxKalmanFilter()
        measurement = np.array([320.0, 240.0, 0.5, 200.0], dtype=np.float64)
        mean, cov = kf.initiate(measurement)

        # Move target to [330.0, 245.0, 0.5, 200.0]
        new_measurement = np.array([330.0, 245.0, 0.5, 200.0], dtype=np.float64)
        pred_mean, pred_cov = kf.predict(mean, cov)
        up_mean, up_cov = kf.update(pred_mean, pred_cov, new_measurement)

        # Updated position should pull towards 330.0
        self.assertGreater(up_mean[0], 320.0)
        self.assertLessEqual(up_mean[0], 331.0)
        # Covariance uncertainty should shrink after measurement update
        self.assertLess(np.trace(up_cov), np.trace(pred_cov))

    def test_coordinate_conversions(self):
        tlwh = np.array([100.0, 50.0, 80.0, 160.0])
        xyah = BoxKalmanFilter.tlwh_to_xyah(tlwh)
        self.assertAlmostEqual(xyah[0], 140.0)  # cx
        self.assertAlmostEqual(xyah[1], 130.0)  # cy
        self.assertAlmostEqual(xyah[2], 0.5)    # a = w/h
        self.assertAlmostEqual(xyah[3], 160.0)  # h

        re_tlwh = BoxKalmanFilter.xyah_to_tlwh(xyah)
        np.testing.assert_allclose(tlwh, re_tlwh, atol=1e-5)


# ==============================================================================
# 4. ByteTrack Multi-Object Tracking Tests
# ==============================================================================

class TestByteTracker(unittest.TestCase):
    """Validates ByteTrack multi-person tracking, ID persistence, and occlusion recovery."""

    def setUp(self):
        STrack.reset_counter()
        self.tracker = ByteTracker(
            track_thresh=0.50,
            low_thresh=0.10,
            match_thresh=0.80,
            low_match_thresh=0.50,
            max_lost_frames=10,
        )

    def test_single_person_tracking_and_id_persistence(self):
        """A single person moving smoothly retains the same unique track ID."""
        for frame_idx in range(5):
            x1 = 100.0 + frame_idx * 10.0
            det = PersonDetection(x1, 100.0, x1 + 80.0, 260.0, confidence=0.92)
            tracks = self.tracker.update([det])
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0].track_id, 1)

    def test_multi_person_concurrent_id_assignment(self):
        """Multiple concurrent people receive distinct, persistent IDs."""
        # Frame 1: Person A and Person B
        det_a1 = PersonDetection(50.0, 100.0, 130.0, 260.0, confidence=0.90)
        det_b1 = PersonDetection(400.0, 120.0, 480.0, 280.0, confidence=0.88)
        tracks1 = self.tracker.update([det_a1, det_b1])

        self.assertEqual(len(tracks1), 2)
        ids1 = {t.track_id for t in tracks1}
        self.assertEqual(len(ids1), 2)

        # Frame 2: both move slightly
        det_a2 = PersonDetection(55.0, 102.0, 135.0, 262.0, confidence=0.91)
        det_b2 = PersonDetection(395.0, 122.0, 475.0, 282.0, confidence=0.89)
        tracks2 = self.tracker.update([det_a2, det_b2])

        self.assertEqual(len(tracks2), 2)
        ids2 = {t.track_id for t in tracks2}
        self.assertEqual(ids1, ids2, "Track IDs must remain persistent across frames")

    def test_temporary_occlusion_and_reacquisition(self):
        """Track survives a brief occlusion (3 frames) and retains its original ID."""
        # 1. Establish track over 3 frames
        for f in range(3):
            d = PersonDetection(200.0 + f * 5.0, 150.0, 280.0 + f * 5.0, 310.0, confidence=0.95)
            tracks = self.tracker.update([d])
            self.assertEqual(tracks[0].track_id, 1)

        # 2. Person is completely occluded for 2 frames
        tracks_lost1 = self.tracker.update([])
        self.assertEqual(len(tracks_lost1), 0)
        tracks_lost2 = self.tracker.update([])
        self.assertEqual(len(tracks_lost2), 0)

        # 3. Person emerges near predicted position
        det_reappear = PersonDetection(220.0, 150.0, 300.0, 310.0, confidence=0.93)
        tracks_reappear = self.tracker.update([det_reappear])

        self.assertEqual(len(tracks_reappear), 1)
        self.assertEqual(tracks_reappear[0].track_id, 1, "Track ID must be preserved after occlusion")

    def test_low_confidence_stage2_association(self):
        """Tests ByteTrack's key feature: associating low-score detections to prevent track loss."""
        # 1. Establish high-score track
        d_high = PersonDetection(200.0, 150.0, 280.0, 310.0, confidence=0.90)
        tracks1 = self.tracker.update([d_high])
        self.assertEqual(len(tracks1), 1)
        self.assertEqual(tracks1[0].track_id, 1)

        # 2. Subject gets partially occluded; confidence drops to 0.30 (below track_thresh=0.50)
        d_occluded = PersonDetection(204.0, 152.0, 284.0, 312.0, confidence=0.30)
        tracks2 = self.tracker.update([d_occluded])

        # Stage 2 association should successfully maintain track
        self.assertEqual(len(tracks2), 1)
        self.assertEqual(tracks2[0].track_id, 1)

    def test_lost_track_pruning_after_max_frames(self):
        """Track remaining lost beyond max_lost_frames is cleanly removed."""
        d = PersonDetection(100.0, 100.0, 180.0, 260.0, confidence=0.90)
        self.tracker.update([d])

        # Send empty frames for max_lost_frames + 2
        for _ in range(self.tracker.max_lost_frames + 2):
            self.tracker.update([])

        # Track should now be pruned into removed_tracks
        self.assertEqual(len(self.tracker.lost_tracks), 0)
        self.assertGreaterEqual(len(self.tracker.removed_tracks), 1)

    def test_bytetracker_instance_isolation(self):
        """Two ByteTracker instances maintain independent track ID counters."""
        tracker1 = ByteTracker()
        tracker2 = ByteTracker()

        det = PersonDetection(100, 100, 200, 300, 0.90)
        tracks1 = tracker1.update([det])
        tracks2 = tracker2.update([det])

        self.assertEqual(tracks1[0].track_id, 1)
        self.assertEqual(tracks2[0].track_id, 1, "Tracker 2 must start its own ID counter at 1")

    def test_linear_assignment_nan_rejection(self):
        """Cost matrices containing NaN are rejected safely without crashes or bad matches."""
        cost_mat = np.array([
            [0.1, float("nan")],
            [float("nan"), 0.2],
        ])
        matches, u_a, u_b = linear_assignment(cost_mat, thresh=0.80)
        self.assertIn((0, 0), matches)
        self.assertIn((1, 1), matches)


# ==============================================================================
# 5. Target Selection & Lost Target State Machine Tests
# ==============================================================================

class TestTargetSelector(unittest.TestCase):
    """Validates target selection heuristics, click-to-track, and safe lost-target timeout."""

    def setUp(self):
        STrack.reset_counter()
        self.selector = TargetSelector(frame_width=640, frame_height=480, reacquisition_timeout_ms=1000.0)

    def test_auto_track_first_largest_strategy(self):
        """Auto-track selects the largest subject in the frame."""
        det_small = PersonDetection(100, 100, 160, 220, 0.90)  # Area: 60 * 120 = 7,200
        det_large = PersonDetection(300, 100, 420, 340, 0.90)  # Area: 120 * 240 = 28,800

        t_small = STrack(det_small, 1)
        t_large = STrack(det_large, 1)

        selected_id = self.selector.auto_track_first([t_small, t_large], strategy="largest")
        self.assertEqual(selected_id, t_large.track_id)
        self.assertEqual(self.selector.locked_track_id, t_large.track_id)

    def test_auto_track_first_center_closest_strategy(self):
        """Auto-track center_closest selects subject closest to (320, 240)."""
        det_center = PersonDetection(300, 200, 340, 280, 0.90)  # centroid (320, 240)
        det_far = PersonDetection(50, 50, 100, 150, 0.90)        # centroid (75, 100)

        t_center = STrack(det_center, 1)
        t_far = STrack(det_far, 1)

        selected_id = self.selector.auto_track_first([t_far, t_center], strategy="center_closest")
        self.assertEqual(selected_id, t_center.track_id)

    def test_click_to_track_hit_testing(self):
        """Clicking inside bounding box locks onto that person."""
        det1 = PersonDetection(100, 100, 200, 300, 0.90)
        det2 = PersonDetection(400, 100, 500, 300, 0.90)
        t1 = STrack(det1, 1)
        t2 = STrack(det2, 1)

        # Click inside t2
        locked_id = self.selector.click_to_track(click_x=450, click_y=200, tracks=[t1, t2])
        self.assertEqual(locked_id, t2.track_id)
        self.assertEqual(self.selector.locked_track_id, t2.track_id)

    def test_direct_track_id_selection_and_unlock(self):
        """Directly selecting an ID locks onto it; stop_tracking unlocks it."""
        self.selector.select_track_id(42)
        self.assertEqual(self.selector.locked_track_id, 42)
        self.assertTrue(self.selector.is_locked)

        self.selector.stop_tracking()
        self.assertIsNone(self.selector.locked_track_id)
        self.assertEqual(self.selector.state, TargetState.IDLE)

    def test_safe_timeout_progression_without_silent_jumping(self):
        """
        Critical safety assertion:
        When active target is occluded, state progresses:
        TRACKING -> COASTING (<=400ms) -> HOLDING (400ms-1000ms) -> LOST (>1000ms).
        System NEVER silently switches to another person present in the scene!
        """
        det_target = PersonDetection(100, 100, 200, 300, 0.90)
        det_other = PersonDetection(400, 100, 500, 300, 0.90)
        t_target = STrack(det_target, 1)
        t_other = STrack(det_other, 1)

        # Lock onto t_target
        self.selector.select_track_id(t_target.track_id, [t_target, t_other])
        t0 = 10000.0

        # Frame 1: Target present -> TRACKING
        r1 = self.selector.update([t_target, t_other], timestamp_ms=t0)
        self.assertEqual(r1.state, TargetState.TRACKING)
        self.assertEqual(r1.coast_factor, 1.0)
        self.assertTrue(r1.target_locked)

        # Frame 2: Target disappears; t_other is present!
        # At +200 ms: COASTING phase
        r2 = self.selector.update([t_other], timestamp_ms=t0 + 200.0)
        self.assertEqual(r2.state, TargetState.COASTING)
        self.assertLess(r2.coast_factor, 1.0)
        self.assertGreater(r2.coast_factor, 0.0)
        self.assertEqual(r2.locked_track_id, t_target.track_id)
        self.assertNotEqual(r2.locked_track_id, t_other.track_id, "Must NOT jump to other person!")

        # Frame 3: At +600 ms: HOLDING phase (zero velocity)
        r3 = self.selector.update([t_other], timestamp_ms=t0 + 600.0)
        self.assertEqual(r3.state, TargetState.HOLDING)
        self.assertEqual(r3.coast_factor, 0.0)
        self.assertEqual(r3.locked_track_id, t_target.track_id)
        self.assertNotEqual(r3.locked_track_id, t_other.track_id, "Must NOT jump to other person!")

        # Frame 4: At +1200 ms: Exceeds timeout (1000 ms) -> LOST
        r4 = self.selector.update([t_other], timestamp_ms=t0 + 1200.0)
        self.assertEqual(r4.state, TargetState.LOST)
        self.assertFalse(r4.target_locked)
        self.assertIsNone(self.selector.locked_track_id)
        self.assertFalse(self.selector.is_locked)

    def test_auto_track_persistence_and_reacquisition_after_timeout(self):
        """
        After active target is lost and timeout expires, system remains in auto_track
        mode and re-acquires a newly appearing person without manual reset.
        """
        det1 = PersonDetection(100, 100, 200, 300, 0.90)
        t1 = STrack(det1, 1)

        self.selector.auto_track_first([t1])
        self.assertEqual(self.selector.mode, "auto_track")
        self.assertEqual(self.selector.locked_track_id, t1.track_id)

        # Target disappears, wait past timeout (1000 ms)
        t0 = 5000.0
        self.selector.update([t1], timestamp_ms=t0)
        r_lost = self.selector.update([], timestamp_ms=t0 + 1500.0)

        self.assertEqual(r_lost.state, TargetState.LOST)
        self.assertFalse(r_lost.target_locked)
        self.assertIsNone(self.selector.locked_track_id)
        # Critical assertion: Mode must still be auto_track!
        self.assertEqual(self.selector.mode, "auto_track")

        # New person enters frame
        det2 = PersonDetection(350, 150, 450, 350, 0.92)
        t2 = STrack(det2, 2)
        r_reacquired = self.selector.update([t2], timestamp_ms=t0 + 1600.0)

        self.assertEqual(r_reacquired.state, TargetState.TRACKING)
        self.assertTrue(r_reacquired.target_locked)
        self.assertEqual(r_reacquired.locked_track_id, t2.track_id)


# ==============================================================================
# 6. PID Tracking Controller, Deadband & Smoothing Tests
# ==============================================================================

class TestPIDControllerAndSmoothing(unittest.TestCase):
    """Validates hysteresis deadband, EMA filter, PID anti-windup, slew limiting, and boundaries."""

    def test_hysteresis_deadband_transitions(self):
        """
        Tests dual-threshold deadband:
        - Inner +-15px: threshold to enter deadband (settle)
        - Outer +-25px: threshold to break out of deadband (motion resumes)
        """
        db = HysteresisDeadband(inner=15.0, outer=25.0)
        self.assertTrue(db.in_deadband)

        # 1. Error within outer deadband (e.g. 20px) remains in deadband
        err, in_db = db.filter(20.0)
        self.assertTrue(in_db)
        self.assertEqual(err, 0.0)

        # 2. Error breaks outer threshold (26px) -> exits deadband
        err, in_db = db.filter(26.0)
        self.assertFalse(in_db)
        self.assertEqual(err, 26.0)

        # 3. Error drops to 20px (between inner 15 and outer 25) -> hysteresis preserves active state
        err, in_db = db.filter(20.0)
        self.assertFalse(in_db)
        self.assertEqual(err, 20.0)

        # 4. Error drops to 12px (below inner 15px) -> re-enters deadband
        err, in_db = db.filter(12.0)
        self.assertTrue(in_db)
        self.assertEqual(err, 0.0)

    def test_ema_smoother(self):
        """EMA filter output matches mathematical formula: alpha * x + (1 - alpha) * prev."""
        alpha = 0.35
        ema = EMASmoother(alpha=alpha)
        # Step input of 100.0
        val1 = ema.filter(100.0)
        self.assertAlmostEqual(val1, alpha * 100.0, places=4)
        val2 = ema.filter(100.0)
        expected2 = alpha * 100.0 + (1.0 - alpha) * val1
        self.assertAlmostEqual(val2, expected2, places=4)

    def test_pid_anti_windup_clamping(self):
        """Integral term is clamped to +-i_max under sustained error."""
        pid = SingleAxisPID(kp=0.04, ki=0.01, kd=0.0, i_max=2.0, max_step_deg=5.0)
        # Apply continuous large error for 100 steps
        for _ in range(100):
            pid.update(error=50.0, dt=0.05)
        self.assertLessEqual(abs(pid.integral), 2.0)

    def test_slew_rate_limiting(self):
        """Angular change per update does not exceed max slew rate (80 deg/s)."""
        ctrl = DualAxisTrackingController()
        # With dt = 0.01s (10 ms), max_slew = 80.0 * 0.01 = 0.8 deg
        # PID step clamp is 3.0 deg, so 0.8 deg strictly exercises the slew limiter!
        dt = 0.01
        max_allowed_delta = 80.0 * dt  # 0.80 deg

        # Displace target by huge error (x = 600, error = +280 px)
        out = ctrl.update((600.0, 240.0), dt=dt)
        self.assertLessEqual(abs(out.delta_pan), max_allowed_delta + 1e-4)
        self.assertGreater(abs(out.delta_pan), 0.5)

    def test_coasting_velocity_momentum_decay(self):
        """During coasting, commanded angular step decays from last velocity without PID error on phantom position."""
        ctrl = DualAxisTrackingController()
        dt = 0.04

        # Active tracking establishes angular motion
        out_active = ctrl.update((400.0, 240.0), dt=dt)
        initial_delta_pan = out_active.delta_pan
        self.assertGreater(initial_delta_pan, 0.0)

        # Coasting frame 1 (decay = 0.70)
        out_coast1 = ctrl.update(target_centroid=None, dt=dt, coast_factor=0.70, is_coasting=True)
        self.assertAlmostEqual(out_coast1.delta_pan, initial_delta_pan * 0.70, places=3)

        # Coasting frame 2 (decay = 0.49)
        out_coast2 = ctrl.update(target_centroid=None, dt=dt, coast_factor=0.49, is_coasting=True)
        self.assertAlmostEqual(out_coast2.delta_pan, initial_delta_pan * 0.49, places=3)

    def test_auto_centering_on_target_loss(self):
        """When target loss timeout triggers auto_center, controller slews smoothly back to (90.0, 90.0)."""
        ctrl = DualAxisTrackingController()
        ctrl.current_pan = 130.0
        ctrl.current_tilt = 70.0
        dt = 0.05  # 50 ms => max slew 4.0 deg/step

        # Step auto-centering until settled
        steps = 0
        while not (ctrl.current_pan == 90.0 and ctrl.current_tilt == 90.0) and steps < 100:
            steps += 1
            out = ctrl.update(target_centroid=None, dt=dt, auto_center=True)

        self.assertEqual(ctrl.current_pan, 90.0)
        self.assertEqual(ctrl.current_tilt, 90.0)
        # Once at center, commands stop dispatching
        out_centered = ctrl.update(target_centroid=None, dt=dt, auto_center=True)
        self.assertFalse(out_centered.should_dispatch_command)

    def test_deadband_command_suppression_and_idle_silence(self):
        """Idle mode and settled deadband state suppress command dispatching to prevent servo hum and bus saturation."""
        ctrl = DualAxisTrackingController()

        # Idle update must NOT dispatch
        out_idle = ctrl.update(target_centroid=None, dt=0.05)
        self.assertFalse(out_idle.should_dispatch_command)

        # Settle target inside deadband (e.g. error = 5 px)
        for _ in range(5):
            ctrl.update((325.0, 240.0), dt=0.05)

        # Once settled, subsequent updates suppress command dispatching
        out_settled = ctrl.update((325.0, 240.0), dt=0.06)
        self.assertTrue(out_settled.is_settled)
        self.assertFalse(out_settled.should_dispatch_command)

    def test_20hz_output_command_rate_limiting(self):
        """High-frequency updates only permit command dispatch at <= 20 Hz."""
        ctrl = DualAxisTrackingController()
        now = time.time()
        ctrl._last_command_time = now

        # Immediate follow-up update (10 ms later) must NOT dispatch command
        out_fast = ctrl.update((350.0, 240.0), dt=0.01)
        self.assertFalse(out_fast.should_dispatch_command)

        # Update 55 ms later (exceeding 50 ms / 20 Hz period) MUST dispatch command
        ctrl._last_command_time = now - 0.06
        out_ready = ctrl.update((350.0, 240.0), dt=0.05)
        self.assertTrue(out_ready.should_dispatch_command)

    def test_physical_servo_boundary_clamping(self):
        """Pan is clamped to [15.0, 165.0] and Tilt to [60.0, 135.0]."""
        ctrl = DualAxisTrackingController()

        # Force massive pan displacement to the right
        for _ in range(50):
            ctrl.update((640.0, 480.0), dt=0.05)

        self.assertLessEqual(ctrl.current_pan, 165.0)
        self.assertGreaterEqual(ctrl.current_tilt, 60.0)

        # Force massive pan displacement to the left
        for _ in range(100):
            ctrl.update((0.0, 0.0), dt=0.05)

        self.assertGreaterEqual(ctrl.current_pan, 15.0)
        self.assertLessEqual(ctrl.current_tilt, 135.0)

    def test_servo_command_payload_schema(self):
        """Validates payload matches docs/protocol.md cmd.servo.move specification."""
        ctrl = DualAxisTrackingController()
        out = ctrl.update((360.0, 230.0), dt=0.05)
        payload = out.to_servo_command_payload(speed=0.6)

        self.assertEqual(payload["mode"], "absolute")
        self.assertEqual(payload["speed"], 0.6)
        self.assertTrue(payload["smooth"])
        self.assertGreaterEqual(payload["pan"], 15.0)
        self.assertLessEqual(payload["pan"], 165.0)
        self.assertGreaterEqual(payload["tilt"], 60.0)
        self.assertLessEqual(payload["tilt"], 135.0)

    def test_relative_servo_command_payload(self):
        """to_servo_command_payload supports relative mode with inverted tilt sign for physical gimbal."""
        ctrl = DualAxisTrackingController()
        out = ctrl.update((360.0, 260.0), dt=0.05)
        payload = out.to_servo_command_payload(mode="relative", speed=0.5)

        self.assertEqual(payload["mode"], "relative")
        self.assertEqual(payload["speed"], 0.5)
        self.assertIn("pan", payload)
        self.assertIn("tilt", payload)
        self.assertEqual(payload["pan"], round(out.delta_pan, 1))
        self.assertEqual(payload["tilt"], round(-out.delta_tilt, 1))


# ==============================================================================
# 7. Closed-Loop Optical Tracking Convergence Simulation
# ==============================================================================

class TestClosedLoopConvergence(unittest.TestCase):
    """
    Simulates optical servo tracking convergence on a displaced world target.
    Asserts mathematical convergence into the inner deadband (+-15 px) within 1.50 seconds.
    """

    def test_closed_loop_tracking_convergence(self):
        ctrl = DualAxisTrackingController()
        dt = 0.04  # 25 Hz vision/control loop
        pixels_per_deg_x = 640.0 / 60.0  # ~10.67 px/deg
        pixels_per_deg_y = 480.0 / 45.0  # ~10.67 px/deg

        # Target in world space initially at (x=480, y=280) when camera is at (90°, 90°)
        target_world_x = 480.0
        target_world_y = 280.0

        sim_time = 0.0
        converged = False
        convergence_time = 0.0

        while sim_time < 2.0:
            sim_time += dt

            # Compute target sensor coordinates given current servo angles
            pan_delta = ctrl.current_pan - 90.0
            tilt_delta = ctrl.current_tilt - 90.0
            sensor_x = target_world_x - (pan_delta * pixels_per_deg_x)
            sensor_y = target_world_y + (tilt_delta * pixels_per_deg_y)

            out = ctrl.update((sensor_x, sensor_y), dt=dt)

            err_x = sensor_x - 320.0
            err_y = sensor_y - 240.0

            if abs(err_x) <= 15.0 and abs(err_y) <= 15.0 and not converged:
                converged = True
                convergence_time = sim_time

        self.assertTrue(converged, "PID tracking loop failed to converge target within +-15px deadband")
        self.assertLess(
            convergence_time,
            1.50,
            f"Convergence took {convergence_time:.2f}s, exceeding 1.50s requirement",
        )


# ==============================================================================
# 8. Visual HUD Overlay Rendering Tests
# ==============================================================================

class TestHUDOverlay(unittest.TestCase):
    """Validates visual HUD overlay rendering across multiple tracking scenarios."""

    def setUp(self):
        self.hud = HUDOverlay(frame_width=640, frame_height=480)
        self.base_frame = np.full((480, 640, 3), 40, dtype=np.uint8)

    def test_hud_rendering_idle_state(self):
        """Renders cleanly in IDLE state with no detections."""
        rendered = self.hud.render(
            frame=self.base_frame,
            tracks=[],
            target_result=None,
            control_output=None,
            fps=30.0,
            inference_ms=12.5,
        )
        self.assertEqual(rendered.shape, (480, 640, 3))
        self.assertEqual(rendered.dtype, np.uint8)

    def test_hud_rendering_active_target_state(self):
        """Renders accented lock reticle, corner brackets, and vector line for active target."""
        det = PersonDetection(200, 150, 320, 350, 0.94)
        track = STrack(det, 1)
        track.is_activated = True

        target_res = TargetSelectionResult(
            state=TargetState.TRACKING,
            active_track=track,
            locked_track_id=track.track_id,
            centroid=track.centroid,
            coast_factor=1.0,
            time_lost_ms=0.0,
            target_locked=True,
        )

        ctrl = DualAxisTrackingController()
        control_output = ctrl.update(track.centroid, dt=0.033)

        rendered = self.hud.render(
            frame=self.base_frame,
            tracks=[track],
            target_result=target_res,
            control_output=control_output,
            fps=29.8,
            inference_ms=14.2,
        )
        self.assertEqual(rendered.shape, (480, 640, 3))
        # Ensure frame was modified (rendered HUD text/lines)
        self.assertFalse(np.array_equal(rendered, self.base_frame))


# ==============================================================================
# 9. Tracking Pipeline & Protocol Conformance Tests
# ==============================================================================

class TestTrackingPipeline(unittest.TestCase):
    """Validates full end-to-end TrackingPipeline and protocol message serialization."""

    def test_pipeline_process_frame_and_protocol_message(self):
        """Validates track.frame_target schema compliance according to docs/protocol.md."""
        detector = MockPersonDetector(mode="manual")
        det = PersonDetection(280.0, 180.0, 360.0, 320.0, confidence=0.91)
        detector.set_detections([det])

        pipeline = TrackingPipeline(detector=detector)
        # Lock onto detected person
        pipeline.auto_track_first(strategy="largest")

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = pipeline.process_frame(frame, timestamp_captured_ms=1731657115160.0)

        self.assertIsInstance(result, TrackingPipelineResult)
        self.assertEqual(result.frame_annotated.shape, (480, 640, 3))
        self.assertEqual(len(result.tracks), 1)

        # Validate telemetry message envelope
        msg = result.telemetry_message
        self.assertEqual(msg["type"], "track.frame_target")
        self.assertEqual(msg["sender"], "backend")
        self.assertIn("timestamp", msg)
        self.assertIn("seq", msg)

        # Validate payload fields conforming to docs/protocol.md
        payload = msg["payload"]
        self.assertEqual(payload["frame_dimensions"]["width"], 640)
        self.assertEqual(payload["frame_dimensions"]["height"], 480)
        self.assertTrue(payload["target_locked"])
        self.assertIsNotNone(payload["active_target"])

        active = payload["active_target"]
        self.assertEqual(active["class_name"], "person")
        self.assertAlmostEqual(active["confidence"], 0.91, places=2)
        self.assertEqual(len(active["bbox"]), 4)
        self.assertEqual(len(active["bbox_normalized"]), 4)
        self.assertEqual(len(active["centroid"]), 2)
        self.assertIn("error_px", active)
        self.assertIn("commanded_delta_deg", active)

    def test_pipeline_integration_with_camera_service(self):
        """Verifies clean integration between CameraService and TrackingPipeline."""
        cam_cfg = CameraConfig(width=640, height=480, fps=30.0, backend=CameraBackend.SYNTHETIC)
        detector = MockPersonDetector(mode="synthetic_sync")
        pipeline = TrackingPipeline(detector=detector)

        with CameraService(cam_cfg) as cam:
            for _ in range(5):
                success, frame, metadata = cam.get_frame(timeout=1.0)
                self.assertTrue(success)
                self.assertIsNotNone(frame)

                result = pipeline.process_frame(frame, timestamp_captured_ms=metadata.timestamp_utc * 1000.0)
                self.assertIsNotNone(result.frame_annotated)
                self.assertGreater(result.fps, 0.0)


if __name__ == "__main__":
    unittest.main()
