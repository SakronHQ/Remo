"""
SmartVision - Person Tracking Subsystem
Provides ByteTrack multi-object tracking, target selection, dual-axis PID control, and HUD rendering.
"""

from .bytetrack import ByteTracker, STrack, TrackState, bbox_ious
from .hud import HUDOverlay
from .kalman import BoxKalmanFilter
from .pid_controller import (
    DualAxisTrackingController,
    EMASmoother,
    HysteresisDeadband,
    SingleAxisPID,
    TrackingControlOutput,
)
from .pipeline import TrackingPipeline, TrackingPipelineResult
from .target_selector import TargetSelectionResult, TargetSelector, TargetState

__all__ = [
    "BoxKalmanFilter",
    "TrackState",
    "STrack",
    "bbox_ious",
    "ByteTracker",
    "TargetState",
    "TargetSelectionResult",
    "TargetSelector",
    "HysteresisDeadband",
    "EMASmoother",
    "SingleAxisPID",
    "TrackingControlOutput",
    "DualAxisTrackingController",
    "HUDOverlay",
    "TrackingPipeline",
    "TrackingPipelineResult",
]
