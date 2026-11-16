"""
Unit tests for SmartVision Face Re-Identification and Persistent Target Memory.
"""

import os
import tempfile
import unittest
import numpy as np

from smartvision.vision.detection.types import PersonDetection
from smartvision.vision.tracking.bytetrack import STrack
from smartvision.vision.tracking.face_reid import FaceMemory, FaceReID
from smartvision.vision.tracking.target_selector import TargetSelector, TargetState


class TestFaceReID(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_face_memory.db")
        self.memory = FaceMemory(db_path=self.db_path)
        self.open_memories = [self.memory]

    def tearDown(self):
        for m in self.open_memories:
            try:
                m.close()
            except Exception:
                pass
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_face_memory_persistence(self):
        # Initial state should be empty
        self.assertFalse(self.memory.has_target())
        self.assertIsNone(self.memory.get_target())

        # Save an embedding (128-d float32)
        feat1 = np.random.randn(1, 128).astype(np.float32)
        feat1 /= np.linalg.norm(feat1)
        self.memory.save_target(feat1)

        self.assertTrue(self.memory.has_target())
        loaded = self.memory.get_target()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.shape, (1, 128))
        np.testing.assert_allclose(loaded, feat1, atol=1e-5)

        # Reopen DB to verify disk persistence
        reopened = FaceMemory(db_path=self.db_path)
        self.open_memories.append(reopened)
        self.assertTrue(reopened.has_target())
        np.testing.assert_allclose(reopened.get_target(), feat1, atol=1e-5)

        # Clear memory
        reopened.clear()
        self.assertFalse(reopened.has_target())
        self.assertIsNone(reopened.get_target())

    def test_reid_matching(self):
        reid = FaceReID(db_path=self.db_path)
        self.open_memories.append(reid.memory)

        feat_a = np.random.randn(1, 128).astype(np.float32)
        feat_a /= np.linalg.norm(feat_a)

        # Same person with minor noise
        feat_same = feat_a + 0.05 * np.random.randn(1, 128).astype(np.float32)
        feat_same /= np.linalg.norm(feat_same)

        # Different person
        feat_diff = np.random.randn(1, 128).astype(np.float32)
        feat_diff /= np.linalg.norm(feat_diff)

        sim_same = reid.match(feat_a, feat_same)
        sim_diff = reid.match(feat_a, feat_diff)

        self.assertGreater(sim_same, 0.70)
        self.assertLess(sim_diff, 0.50)
        self.assertTrue(reid.is_match(feat_a, feat_same))

    def test_target_selector_facial_reacquisition(self):
        # Create a mock FaceReID that returns predictable embeddings based on raw_face tag
        class MockReID:
            def __init__(self, db_path):
                self.memory = FaceMemory(db_path=db_path)
                self.match_thresh = 0.50

            def extract_embedding(self, frame, raw_face):
                if raw_face == "person_alice":
                    return np.ones((1, 128), dtype=np.float32)
                elif raw_face == "person_bob":
                    return -np.ones((1, 128), dtype=np.float32)
                return None

            def match(self, f1, f2):
                if f1 is None or f2 is None:
                    return -1.0
                return float(np.dot(f1.flatten(), f2.flatten()) / (np.linalg.norm(f1) * np.linalg.norm(f2)))

            def is_match(self, f1, f2):
                return self.match(f1, f2) >= self.match_thresh

            def close(self):
                self.memory.close()

        mock_reid = MockReID(db_path=self.db_path)
        self.open_memories.append(mock_reid.memory)
        selector = TargetSelector(face_reid=mock_reid)

        # 1. Person Alice appears in frame as Track 10
        det_alice = PersonDetection(x1=100, y1=100, x2=200, y2=200, confidence=0.9, raw_face="person_alice")
        track_alice = STrack(det_alice, frame_id=1, track_id=10)
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Operator clicks Alice to lock at t=1000.0 ms
        selector.click_to_track(click_x=150, click_y=150, tracks=[track_alice], frame=dummy_frame)
        selector._last_seen_time_ms = 1000.0
        self.assertEqual(selector.locked_track_id, 10)
        self.assertTrue(mock_reid.memory.has_target())

        # 2. Alice leaves camera frame completely (frame has only Bob or empty)
        det_bob = PersonDetection(x1=400, y1=100, x2=500, y2=200, confidence=0.85, raw_face="person_bob")
        track_bob = STrack(det_bob, frame_id=2, track_id=20)

        # Alice is gone; after timeout (t=5000.0 ms, elapsed 4000 ms > 3000 ms), track is LOST
        result = selector.update([track_bob], timestamp_ms=5000.0, frame=dummy_frame)
        self.assertEqual(result.state, TargetState.LOST)
        self.assertIsNone(selector.locked_track_id)
        # But SQLite memory still remembers Alice!
        self.assertTrue(mock_reid.memory.has_target())

        # 3. Alice re-enters the room! Tracker gives her a NEW track ID (Track 35)
        track_alice_new = STrack(det_alice, frame_id=30, track_id=35)
        tracks_now = [track_bob, track_alice_new]

        # TargetSelector should recognize Alice's face and automatically re-lock Track 35!
        result2 = selector.update(tracks_now, timestamp_ms=6000.0, frame=dummy_frame)
        self.assertEqual(result2.state, TargetState.TRACKING)
        self.assertEqual(selector.locked_track_id, 35)
        self.assertEqual(result2.locked_track_id, 35)


if __name__ == "__main__":
    unittest.main()
