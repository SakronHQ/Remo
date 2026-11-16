"""
test_camera_system.py
Automated Verification Suite for SmartVision Phase 4: PC Camera System.

Validates:
1. Camera configuration, platform backend resolution (DirectShow / V4L2), and presets.
2. Hardware camera probe, device discovery, and capability negotiation.
3. Synthetic test pattern generator, moving targets, and OpenCV VideoCapture compatibility.
4. Double-buffered, non-blocking capture thread, buffer draining, and zero-lag delivery.
5. Real-time rolling FPS counter, dropped frame metrics, and frame metadata schema.
6. Error handling, synthetic failover, and auto-reconnect on device disconnect.
7. Low-latency MJPEG video streaming generator (multipart boundary chunking and JPEG integrity).
"""

import asyncio
import os
import sys
import threading
import time
from typing import Optional, Tuple
import unittest

import cv2
import numpy as np

# Ensure smartvision root is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from vision.camera.capture_thread import CameraCaptureThread
from vision.camera.config import (
    CameraBackend,
    CameraConfig,
    FrameMetadata,
    STANDARD_FOURCC,
    STANDARD_FPS,
    STANDARD_RESOLUTIONS,
)
from vision.camera.probe import CameraDeviceInfo, CameraProbe
from vision.camera.service import CameraService
from vision.camera.stream import async_get_mjpeg_stream, draw_hud_overlay, get_mjpeg_stream
from vision.camera.synthetic import SyntheticCamera, SyntheticTestPattern


# ==============================================================================
# 1. Configuration & Platform Resolution Tests
# ==============================================================================

class TestCameraConfig(unittest.TestCase):
    """Validates configuration models, defaults, and platform backend resolution."""

    def test_default_config_values(self):
        cfg = CameraConfig()
        self.assertEqual(cfg.device_index, 0)
        self.assertEqual(cfg.width, 640)
        self.assertEqual(cfg.height, 480)
        self.assertEqual(cfg.fps, 30.0)
        self.assertEqual(cfg.fourcc, "MJPG")
        self.assertEqual(cfg.backend, CameraBackend.AUTO)
        self.assertEqual(cfg.buffer_size, 1)
        self.assertTrue(cfg.auto_reconnect)
        self.assertTrue(cfg.enable_synthetic_fallback)

    def test_fourcc_int_conversion(self):
        cfg = CameraConfig(fourcc="MJPG")
        expected = cv2.VideoWriter_fourcc(*"MJPG")
        self.assertEqual(cfg.get_fourcc_int(), expected)

        cfg_invalid = CameraConfig(fourcc="ABC")
        self.assertEqual(cfg_invalid.get_fourcc_int(), 0)

    def test_config_serialization(self):
        cfg = CameraConfig(device_index=2, width=1280, height=720, backend=CameraBackend.DSHOW)
        d = cfg.to_dict()
        self.assertEqual(d["device_index"], 2)
        self.assertEqual(d["width"], 1280)
        self.assertEqual(d["height"], 720)
        self.assertEqual(d["backend"], "dshow")

    def test_platform_backend_resolution(self):
        # Specific overrides
        self.assertEqual(CameraBackend.resolve_cv_backend(CameraBackend.ANY), cv2.CAP_ANY)
        self.assertEqual(
            CameraBackend.resolve_cv_backend(CameraBackend.DSHOW),
            getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY),
        )
        self.assertEqual(
            CameraBackend.resolve_cv_backend(CameraBackend.V4L2),
            getattr(cv2, "CAP_V4L2", cv2.CAP_ANY),
        )

        # AUTO resolution depends on OS
        auto_backend = CameraBackend.resolve_cv_backend(CameraBackend.AUTO)
        if sys.platform.startswith("win"):
            self.assertEqual(auto_backend, getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY))
        elif sys.platform.startswith("linux"):
            self.assertEqual(auto_backend, getattr(cv2, "CAP_V4L2", cv2.CAP_ANY))

    def test_frame_metadata_serialization(self):
        meta = FrameMetadata(
            frame_id=42,
            timestamp_utc=1700000000.0,
            monotonic_time=12345.67,
            width=640,
            height=480,
            fps_measured=29.8,
            dropped_frames=3,
            is_synthetic=True,
            source="synthetic",
        )
        d = meta.to_dict()
        self.assertEqual(d["frame_id"], 42)
        self.assertEqual(d["fps_measured"], 29.8)
        self.assertTrue(d["is_synthetic"])


# ==============================================================================
# 2. Camera Probe & Device Discovery Tests
# ==============================================================================

class TestCameraProbe(unittest.TestCase):
    """Validates camera scanning, capability probing, and non-existent device handling."""

    def test_probe_available_indices_returns_list(self):
        indices = CameraProbe.probe_available_indices(max_index=3)
        self.assertIsInstance(indices, list)
        for idx in indices:
            self.assertIsInstance(idx, int)
            self.assertGreaterEqual(idx, 0)

    def test_probe_invalid_device_returns_unavailable(self):
        # Index 999 should not exist on any physical machine
        info = CameraProbe.probe_device_capabilities(index=999)
        self.assertIsInstance(info, CameraDeviceInfo)
        self.assertEqual(info.index, 999)
        self.assertFalse(info.is_available)
        self.assertIsNotNone(info.error_message)

    def test_directshow_fourcc_decoding(self):
        from vision.camera.probe import DSHOW_FOURCC_MAP
        self.assertEqual(DSHOW_FOURCC_MAP[0xE436EB7D], "RGB24")
        self.assertEqual(DSHOW_FOURCC_MAP[0xE436EB7E], "RGB32")

    def test_probe_device_capabilities_structure(self):
        indices = CameraProbe.probe_available_indices(max_index=2)
        if not indices:
            self.skipTest("No physical camera detected to test real hardware capabilities.")

        target_idx = indices[0]
        info = CameraProbe.probe_device_capabilities(
            index=target_idx,
            candidate_resolutions=[(640, 480)],
            candidate_fourccs=["MJPG"],
            candidate_fps=[30.0],
        )
        self.assertTrue(info.is_available)
        self.assertEqual(info.index, target_idx)
        self.assertIsInstance(info.supported_resolutions, list)
        self.assertIsInstance(info.supported_fourccs, list)


# ==============================================================================
# 3. Synthetic Test Pattern & Virtual Camera Tests
# ==============================================================================

class TestSyntheticPatternAndCamera(unittest.TestCase):
    """Validates the synthetic test card generator and OpenCV compatibility."""

    def test_pattern_generator_frame_shape_and_dtype(self):
        gen = SyntheticTestPattern(width=640, height=480, fps=30.0)
        frame, gt = gen.generate_frame(t=0.0)

        self.assertEqual(frame.shape, (480, 640, 3))
        self.assertEqual(frame.dtype, np.uint8)
        self.assertTrue(gt["target_detected"])
        self.assertIn("centroid", gt)
        self.assertIn("bbox", gt)
        self.assertEqual(gt["frame_id"], 1)

    def test_pattern_moving_target_trajectory(self):
        gen = SyntheticTestPattern(width=640, height=480, fps=30.0, pattern="moving_target")
        _, gt_0 = gen.generate_frame(t=0.0)
        _, gt_1 = gen.generate_frame(t=1.0)

        # Centroid coordinates should change as time evolves
        cx_0, cy_0 = gt_0["centroid"]
        cx_1, cy_1 = gt_1["centroid"]
        self.assertNotEqual((cx_0, cy_0), (cx_1, cy_1))

    def test_synthetic_camera_opencv_interface(self):
        cam = SyntheticCamera(width=320, height=240, fps=30.0, realtime_pacing=False)
        self.assertTrue(cam.isOpened())

        # Test cv2.VideoCapture get() properties
        self.assertEqual(cam.get(getattr(cv2, "CAP_PROP_FRAME_WIDTH", 3)), 320.0)
        self.assertEqual(cam.get(getattr(cv2, "CAP_PROP_FRAME_HEIGHT", 4)), 240.0)
        self.assertEqual(cam.get(getattr(cv2, "CAP_PROP_FPS", 5)), 30.0)

        # Test frame reading
        ret, frame = cam.read()
        self.assertTrue(ret)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (240, 320, 3))

        # Test grab and retrieve
        self.assertTrue(cam.grab())
        ret, frame = cam.retrieve()
        self.assertTrue(ret)

        # Test release
        cam.release()
        self.assertFalse(cam.isOpened())
        ret, frame = cam.read()
        self.assertFalse(ret)
        self.assertIsNone(frame)


# ==============================================================================
# 4. Decoupled Capture Thread & Buffer Draining Tests
# ==============================================================================

class TestCameraCaptureThread(unittest.TestCase):
    """Validates double-buffering, zero-lag queue draining, and FPS metrics."""

    def setUp(self):
        self.config = CameraConfig(width=320, height=240, fps=60.0)
        self.synthetic_cam = SyntheticCamera(
            width=320, height=240, fps=60.0, realtime_pacing=False
        )
        self.capture_thread = CameraCaptureThread(
            cap=self.synthetic_cam,
            config=self.config,
            source_name="test_synthetic",
        )

    def tearDown(self):
        if self.capture_thread.is_running:
            self.capture_thread.stop(timeout=1.0)

    def test_thread_lifecycle_and_frame_retrieval(self):
        self.assertFalse(self.capture_thread.is_running)
        self.capture_thread.start()
        self.assertTrue(self.capture_thread.is_running)

        # Wait for frame
        success, frame, metadata = self.capture_thread.get_latest_frame(timeout=1.0)
        self.assertTrue(success)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (240, 320, 3))
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.width, 320)
        self.assertEqual(metadata.height, 240)
        self.assertTrue(metadata.is_synthetic)

        # Non-blocking read
        success_nb, frame_nb, meta_nb = self.capture_thread.get_latest_frame_nowait()
        self.assertTrue(success_nb)
        self.assertIsNotNone(frame_nb)

        self.capture_thread.stop()
        self.assertFalse(self.capture_thread.is_running)

    def test_buffer_draining_and_dropped_frame_metrics(self):
        self.capture_thread.start()
        # Allow thread to capture multiple frames without consumer reading
        time.sleep(0.1)

        stats = self.capture_thread.get_stats()
        self.assertGreater(stats["frame_id"], 1)
        # Because the consumer was idle, frames should have been marked as dropped
        self.assertGreaterEqual(stats["dropped_frames"], 1)

    def test_source_hot_swap(self):
        self.capture_thread.start()
        time.sleep(0.05)

        new_cam = SyntheticCamera(width=640, height=480, fps=30.0, realtime_pacing=False)
        self.capture_thread.update_capture_source(new_cam, "new_source")

        time.sleep(0.05)
        success, frame, metadata = self.capture_thread.get_latest_frame(timeout=1.0)
        self.assertTrue(success)
        self.assertEqual(frame.shape, (480, 640, 3))
        self.assertEqual(metadata.source, "new_source")

    def test_concurrent_multi_client_consumption(self):
        self.capture_thread.start()
        frames_c1 = []
        frames_c2 = []

        def reader1():
            last_id = None
            for _ in range(15):
                ret, frame, meta = self.capture_thread.get_latest_frame(timeout=1.0, last_frame_id=last_id)
                if ret and meta:
                    last_id = meta.frame_id
                    frames_c1.append(meta.frame_id)

        def reader2():
            last_id = None
            for _ in range(15):
                ret, frame, meta = self.capture_thread.get_latest_frame(timeout=1.0, last_frame_id=last_id)
                if ret and meta:
                    last_id = meta.frame_id
                    frames_c2.append(meta.frame_id)

        t1 = threading.Thread(target=reader1)
        t2 = threading.Thread(target=reader2)
        t1.start()
        t2.start()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

        self.assertEqual(len(frames_c1), 15)
        self.assertEqual(len(frames_c2), 15)
        # Frames should overlap since both readers subscribe to the stream concurrently
        overlap = set(frames_c1).intersection(set(frames_c2))
        self.assertGreaterEqual(len(overlap), 10)


# ==============================================================================
# 5. Camera Service Lifecycle & Auto-Reconnect Tests
# ==============================================================================

class FlakyMockCamera:
    """Mock video source that fails after N successful frames to test error recovery."""

    def __init__(self, fail_after_frames: int = 5):
        self.fail_after_frames = fail_after_frames
        self.frame_count = 0
        self.is_opened = True

    def isOpened(self) -> bool:
        return self.is_opened

    def release(self) -> None:
        self.is_opened = False

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.is_opened:
            return False, None
        self.frame_count += 1
        if self.frame_count > self.fail_after_frames:
            return False, None
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        return True, frame


class TestCameraService(unittest.TestCase):
    """Validates CameraService start/stop, synthetic fallback, and auto-reconnect."""

    def test_synthetic_forced_start(self):
        cfg = CameraConfig(backend=CameraBackend.SYNTHETIC, width=640, height=480)
        with CameraService(cfg) as service:
            self.assertTrue(service.is_running)
            self.assertTrue(service.is_synthetic)

            success, frame, meta = service.get_frame(timeout=1.0)
            self.assertTrue(success)
            self.assertEqual(frame.shape, (480, 640, 3))

            stats = service.get_stats()
            self.assertTrue(stats["is_running"])
            self.assertTrue(stats["is_synthetic"])
            self.assertEqual(stats["configured_resolution"], [640, 480])

        self.assertFalse(service.is_running)

    def test_fallback_on_invalid_device_index(self):
        # Index 999 cannot exist, service should fall back to synthetic seamlessly
        cfg = CameraConfig(
            device_index=999,
            enable_synthetic_fallback=True,
            width=320,
            height=240,
        )
        service = CameraService(cfg)
        service.start()
        try:
            self.assertTrue(service.is_running)
            self.assertTrue(service.is_synthetic)

            success, frame, meta = service.get_frame(timeout=1.0)
            self.assertTrue(success)
            self.assertEqual(frame.shape, (240, 320, 3))
        finally:
            service.stop()

    def test_error_recovery_failover_to_synthetic(self):
        # Test error callback and failover using FlakyMockCamera
        cfg = CameraConfig(
            max_consecutive_errors=3,
            enable_synthetic_fallback=True,
            auto_reconnect=False,
            width=320,
            height=240,
        )
        service = CameraService(cfg)
        flaky_cam = FlakyMockCamera(fail_after_frames=3)

        # Manually wire flaky camera as active source
        service._active_cap = flaky_cam
        service._is_synthetic = False
        service._capture_thread = CameraCaptureThread(
            cap=flaky_cam,
            config=cfg,
            on_error_callback=service._on_capture_error,
            source_name="flaky_cam",
        )
        service._capture_thread.start()
        service._is_running = True

        try:
            # First few frames succeed
            success, _, _ = service.get_frame(timeout=1.0)
            self.assertTrue(success)

            # Wait for failures to trigger failover
            time.sleep(0.3)
            self.assertTrue(service.is_synthetic)

            # Frames should continue streaming seamlessly via synthetic fallback!
            success_post_fail, frame_post, meta_post = service.get_frame(timeout=1.0)
            self.assertTrue(success_post_fail)
            self.assertIsNotNone(frame_post)
            self.assertTrue(meta_post.is_synthetic)

        finally:
            service.stop()

    def test_auto_reconnect_hardware_restoration(self):
        # Service starts in synthetic mode
        cfg = CameraConfig(
            device_index=0,
            enable_synthetic_fallback=True,
            auto_reconnect=True,
            reconnect_interval_s=0.1,
            width=320,
            height=240,
        )
        service = CameraService(cfg)
        service.set_forced_synthetic(True)
        service.start()
        try:
            self.assertTrue(service.is_synthetic)
            # Simulate hardware reconnection by overriding _open_hardware_device to return a mock camera
            mock_reconnected_cam = SyntheticCamera(width=320, height=240, fps=60.0, realtime_pacing=False)
            service._open_hardware_device = lambda: mock_reconnected_cam
            # Release forced synthetic
            service.set_forced_synthetic(False)
            time.sleep(0.2)
            # Service should have automatically restored physical camera stream!
            self.assertFalse(service.is_synthetic)
            self.assertEqual(service._active_cap, mock_reconnected_cam)
        finally:
            service.stop()

    def test_runtime_error_with_synthetic_fallback_disabled(self):
        cfg = CameraConfig(
            max_consecutive_errors=2,
            enable_synthetic_fallback=False,
            auto_reconnect=False,
            width=320,
            height=240,
        )
        service = CameraService(cfg)
        flaky_cam = FlakyMockCamera(fail_after_frames=2)
        service._active_cap = flaky_cam
        service._is_synthetic = False
        service._capture_thread = CameraCaptureThread(
            cap=flaky_cam,
            config=cfg,
            on_error_callback=service._on_capture_error,
            source_name="flaky_cam",
        )
        service._capture_thread.start()
        service._is_running = True
        try:
            time.sleep(0.2)
            # Synthetic fallback was disabled, so it should NOT switch to synthetic
            self.assertFalse(service.is_synthetic)
        finally:
            service.stop()


# ==============================================================================
# 6. Low-Latency MJPEG Streaming Generator Tests
# ==============================================================================

class TestMJPEGStreaming(unittest.TestCase):
    """Validates multipart boundary HTTP chunk formatting and JPEG validity."""

    def test_sync_mjpeg_stream_generation(self):
        cfg = CameraConfig(backend=CameraBackend.SYNTHETIC, width=320, height=240, fps=30.0)
        with CameraService(cfg) as service:
            gen = get_mjpeg_stream(service, quality=75, overlay_hud=True)

            # Read 5 consecutive chunks
            for i in range(5):
                chunk = next(gen)
                self.assertIsInstance(chunk, bytes)

                # Validate multipart headers
                self.assertTrue(chunk.startswith(b"--frame\r\n"))
                self.assertIn(b"Content-Type: image/jpeg\r\n", chunk)
                self.assertIn(b"Content-Length: ", chunk)
                self.assertTrue(chunk.endswith(b"\r\n"))

                # Validate JPEG magic bytes: \xff\xd8\xff
                self.assertIn(b"\xff\xd8\xff", chunk)

                # Validate Content-Length accurately reflects payload
                header_part, body_part = chunk.split(b"\r\n\r\n", 1)
                jpeg_data = body_part[:-2]  # strip trailing \r\n
                for line in header_part.split(b"\r\n"):
                    if line.startswith(b"Content-Length: "):
                        declared_len = int(line.split(b": ")[1])
                        self.assertEqual(declared_len, len(jpeg_data))

    def test_hud_overlay_rendering(self):
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        stats = {
            "fps_actual": 29.8,
            "source": "cam_0",
            "is_synthetic": False,
            "dropped_frames": 2,
        }
        hud_img = draw_hud_overlay(img, stats)
        self.assertEqual(hud_img.shape, img.shape)
        # Check that top bar has drawn pixels (not all zeros)
        self.assertGreater(np.count_nonzero(hud_img[:30, :]), 0)

    def test_async_mjpeg_stream_generation(self):
        cfg = CameraConfig(backend=CameraBackend.SYNTHETIC, width=320, height=240, fps=30.0)

        async def _run_async_stream():
            with CameraService(cfg) as service:
                gen = async_get_mjpeg_stream(service, quality=70)
                chunks = []
                async for chunk in gen:
                    chunks.append(chunk)
                    if len(chunks) >= 3:
                        break
                return chunks

        chunks = asyncio.run(_run_async_stream())
        self.assertEqual(len(chunks), 3)
        for chunk in chunks:
            self.assertTrue(chunk.startswith(b"--frame\r\n"))
            self.assertIn(b"\xff\xd8\xff", chunk)

    def test_async_multi_client_mjpeg_stream(self):
        cfg = CameraConfig(backend=CameraBackend.SYNTHETIC, width=320, height=240, fps=30.0)

        async def _run_multi_async():
            with CameraService(cfg) as service:
                c1_chunks = []
                c2_chunks = []

                async def client1():
                    async for chunk in async_get_mjpeg_stream(service):
                        c1_chunks.append(chunk)
                        if len(c1_chunks) >= 5:
                            break

                async def client2():
                    async for chunk in async_get_mjpeg_stream(service):
                        c2_chunks.append(chunk)
                        if len(c2_chunks) >= 5:
                            break

                await asyncio.gather(client1(), client2())
                return len(c1_chunks), len(c2_chunks)

        n1, n2 = asyncio.run(_run_multi_async())
        self.assertEqual(n1, 5)
        self.assertEqual(n2, 5)

    def test_mjpeg_stream_fps_limiting(self):
        cfg = CameraConfig(backend=CameraBackend.SYNTHETIC, width=320, height=240, fps=60.0)
        with CameraService(cfg) as service:
            gen = get_mjpeg_stream(service, fps_limit=10.0)
            t0 = time.time()
            for _ in range(4):
                next(gen)
            elapsed = time.time() - t0
            # 4 chunks throttled to 10 FPS requires at least 0.20s
            self.assertGreaterEqual(elapsed, 0.20)


# ==============================================================================
# Main Verification Runner
# ==============================================================================

def run_tests() -> bool:
    """Executes the test suite with formatted console summary."""
    print("=" * 80)
    print("      SMARTVISION PHASE 4: PC CAMERA SYSTEM AUTOMATED TEST SUITE        ")
    print("=" * 80)

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestCameraConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestCameraProbe))
    suite.addTests(loader.loadTestsFromTestCase(TestSyntheticPatternAndCamera))
    suite.addTests(loader.loadTestsFromTestCase(TestCameraCaptureThread))
    suite.addTests(loader.loadTestsFromTestCase(TestCameraService))
    suite.addTests(loader.loadTestsFromTestCase(TestMJPEGStreaming))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("=" * 80)
    if result.wasSuccessful():
        print(" [PASS] All camera subsystem test suites passed with ZERO errors! ")
    else:
        print(f" [FAIL] Camera test suite failed with {len(result.errors)} errors, {len(result.failures)} failures.")
    print("=" * 80)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
