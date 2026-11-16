"""
SmartVision - Computer Vision Subsystem
"""

__version__ = "1.0.0"

_EXPORTS = {
    # Camera
    "CameraBackend": "vision.camera",
    "CameraCaptureThread": "vision.camera",
    "CameraConfig": "vision.camera",
    "CameraDeviceInfo": "vision.camera",
    "CameraProbe": "vision.camera",
    "CameraService": "vision.camera",
    "FrameMetadata": "vision.camera",
    "SyntheticCamera": "vision.camera",
    "SyntheticTestPattern": "vision.camera",
    "get_mjpeg_stream": "vision.camera",
    # Detection
    "BasePersonDetector": "vision.detection",
    "PersonDetection": "vision.detection",
    "YoloPersonDetector": "vision.detection",
    "MockPersonDetector": "vision.detection",
    "DetectorUnavailableError": "vision.detection",
    "create_detector": "vision.detection",
    # Tracking & Control
    "BoxKalmanFilter": "vision.tracking",
    "ByteTracker": "vision.tracking",
    "STrack": "vision.tracking",
    "TrackState": "vision.tracking",
    "TargetSelector": "vision.tracking",
    "TargetState": "vision.tracking",
    "TargetSelectionResult": "vision.tracking",
    "HysteresisDeadband": "vision.tracking",
    "EMASmoother": "vision.tracking",
    "DualAxisTrackingController": "vision.tracking",
    "TrackingControlOutput": "vision.tracking",
    "HUDOverlay": "vision.tracking",
    "TrackingPipeline": "vision.tracking",
    "TrackingPipelineResult": "vision.tracking",
}


def __getattr__(name: str):
    if name in _EXPORTS:
        mod = __import__(_EXPORTS[name], fromlist=[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_EXPORTS.keys())
