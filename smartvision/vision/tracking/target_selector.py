"""
SmartVision - Target Selection & Reacquisition State Machine
Manages interactive click-to-track, ID-based locking, auto-track target prioritization,
and safe timeout reacquisition without silent target switching.
"""

from enum import Enum
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from .bytetrack import STrack, TrackState


class TargetState(str, Enum):
    """Tracking engagement state of the vision system."""
    IDLE = "idle"               # No target locked; camera idle/manual
    TRACKING = "tracking"       # Target actively detected and updated in current frame
    COASTING = "coasting"       # Target lost for <= 400ms; decaying velocity smoothly
    HOLDING = "holding"         # Target lost for 400ms - timeout; holding servo position
    LOST = "lost"               # Target lost for > timeout; unlocked, awaiting operator/auto command


class TargetSelectionResult:
    """Snapshot of target selector state for the current frame."""

    def __init__(
        self,
        state: TargetState,
        active_track: Optional[STrack],
        locked_track_id: Optional[int],
        centroid: Optional[Tuple[float, float]],
        coast_factor: float,
        time_lost_ms: float,
        target_locked: bool,
    ):
        self.state = state
        self.active_track = active_track
        self.locked_track_id = locked_track_id
        self.centroid = centroid
        self.coast_factor = coast_factor
        self.time_lost_ms = time_lost_ms
        self.target_locked = target_locked

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "target_locked": self.target_locked,
            "locked_track_id": self.locked_track_id,
            "centroid": [round(c, 1) for c in self.centroid] if self.centroid else None,
            "coast_factor": round(self.coast_factor, 3),
            "time_lost_ms": round(self.time_lost_ms, 1),
        }


class TargetSelector:
    """
    State machine arbitrating operator target selection and safe lost-target coasting/holding.
    Ensures the system never silently jumps to another person when the active target is occluded.
    """

    COASTING_WINDOW_MS = 400.0        # 0 - 400 ms: exponential velocity decay
    DEFAULT_TIMEOUT_MS = 3000.0       # Reacquisition timeout before abandoning lock
    COAST_DECAY_RATE = 0.70           # Decay factor per frame during coasting

    def __init__(
        self,
        frame_width: int = 640,
        frame_height: int = 480,
        reacquisition_timeout_ms: float = 3000.0,
    ):
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_center = (frame_width / 2.0, frame_height / 2.0)
        self.reacquisition_timeout_ms = reacquisition_timeout_ms

        self._locked_track_id: Optional[int] = None
        self._operating_mode = "idle"  # "idle", "auto_track", "locked_id"
        self._auto_track_strategy = "largest"
        self._state = TargetState.IDLE

        self._last_seen_time_ms: float = 0.0
        self._last_known_centroid: Optional[Tuple[float, float]] = None
        self._coasting_frames: int = 0

    @property
    def mode(self) -> str:
        """Current operating mode ('idle', 'auto_track', 'locked_id')."""
        return self._operating_mode

    def set_mode(self, mode: str) -> None:
        """Sets tracking operating mode."""
        self._operating_mode = mode
        if mode == "idle":
            self.stop_tracking()

    @property
    def locked_track_id(self) -> Optional[int]:
        """Currently locked track identifier (or None)."""
        return self._locked_track_id

    @property
    def state(self) -> TargetState:
        """Current tracking state."""
        return self._state

    @property
    def is_locked(self) -> bool:
        """True if target is currently locked (TRACKING, COASTING, or HOLDING)."""
        return self._locked_track_id is not None and self._state in (
            TargetState.TRACKING,
            TargetState.COASTING,
            TargetState.HOLDING,
        )

    def click_to_track(
        self,
        click_x: float,
        click_y: float,
        tracks: List[STrack],
        max_click_distance: float = 120.0,
    ) -> Optional[int]:
        """
        Selects target based on mouse click coordinates.
        First checks bounding box hit testing; falls back to nearest centroid within radius.
        """
        if not tracks:
            return None

        # 1. Bounding box intersection test
        containing_tracks: List[STrack] = []
        for t in tracks:
            x1, y1, x2, y2 = t.bbox
            if x1 <= click_x <= x2 and y1 <= click_y <= y2:
                containing_tracks.append(t)

        if containing_tracks:
            # If multiple overlapping bboxes, choose one whose center is closest to click
            best = min(
                containing_tracks,
                key=lambda t: math.hypot(t.centroid[0] - click_x, t.centroid[1] - click_y),
            )
            self._lock_to_track(best)
            return best.track_id

        # 2. Nearest centroid search within radius
        candidates = []
        for t in tracks:
            dist = math.hypot(t.centroid[0] - click_x, t.centroid[1] - click_y)
            if dist <= max_click_distance:
                candidates.append((dist, t))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            best_track = candidates[0][1]
            self._lock_to_track(best_track)
            return best_track.track_id

        return None

    def select_track_id(self, track_id: int, tracks: Optional[List[STrack]] = None) -> bool:
        """Locks onto a specific track ID directly."""
        self._locked_track_id = track_id
        self._operating_mode = "locked_id"
        self._state = TargetState.TRACKING
        self._coasting_frames = 0

        now_ms = time.time() * 1000.0
        self._last_seen_time_ms = now_ms

        if tracks:
            for t in tracks:
                if t.track_id == track_id:
                    self._last_known_centroid = t.centroid
                    return True
        return True

    def auto_track_first(
        self, tracks: Optional[List[STrack]] = None, strategy: str = "largest"
    ) -> Optional[int]:
        """
        Automatically selects and locks the primary subject in frame.
        Strategy: 'largest' (default - subject closest to camera),
                  'center_closest' (subject closest to frame center),
                  'highest_conf' (subject with highest detector confidence).
        """
        self._operating_mode = "auto_track"
        self._auto_track_strategy = strategy

        active_tracks = [t for t in tracks if getattr(t, 'state', None) != TrackState.Removed] if tracks else []
        if not active_tracks:
            return None

        if strategy == "largest":
            best = max(active_tracks, key=lambda t: t.area)
        elif strategy == "center_closest":
            cx, cy = self.frame_center
            best = min(active_tracks, key=lambda t: math.hypot(t.centroid[0] - cx, t.centroid[1] - cy))
        elif strategy == "highest_conf":
            best = max(active_tracks, key=lambda t: t.score)
        else:
            best = active_tracks[0]

        self._lock_to_track(best)
        return best.track_id

    def stop_tracking(self) -> None:
        """Releases active lock and transitions system to IDLE."""
        self._locked_track_id = None
        self._operating_mode = "idle"
        self._state = TargetState.IDLE
        self._last_known_centroid = None
        self._coasting_frames = 0

    def _lock_to_track(self, track: STrack) -> None:
        """Internal helper to lock onto a confirmed track."""
        self._locked_track_id = track.track_id
        if self._operating_mode != "auto_track":
            self._operating_mode = "locked_id"
        self._state = TargetState.TRACKING
        self._last_known_centroid = track.centroid
        self._last_seen_time_ms = time.time() * 1000.0
        self._coasting_frames = 0

    def update(
        self,
        tracks: List[STrack],
        timestamp_ms: Optional[float] = None,
    ) -> TargetSelectionResult:
        """
        Updates target selection state for current frame.
        Handles coasting, holding, and timeout without silently jumping to another person.
        """
        now_ms = timestamp_ms if timestamp_ms is not None else time.time() * 1000.0

        # Case 1: No target currently requested or locked
        if self._locked_track_id is None:
            if self._operating_mode == "auto_track" and tracks:
                # In auto_track mode, acquire first target if available
                self.auto_track_first(tracks, strategy=self._auto_track_strategy)
            else:
                self._state = TargetState.IDLE
                return TargetSelectionResult(
                    state=TargetState.IDLE,
                    active_track=None,
                    locked_track_id=None,
                    centroid=None,
                    coast_factor=0.0,
                    time_lost_ms=0.0,
                    target_locked=False,
                )

        # Case 2: Target is locked. Find it among current tracks
        target_track: Optional[STrack] = None
        for t in tracks:
            if t.track_id == self._locked_track_id:
                target_track = t
                break

        if target_track is not None:
            # Target is visible and updated in this frame
            self._state = TargetState.TRACKING
            self._last_seen_time_ms = now_ms
            self._last_known_centroid = target_track.centroid
            self._coasting_frames = 0

            return TargetSelectionResult(
                state=TargetState.TRACKING,
                active_track=target_track,
                locked_track_id=self._locked_track_id,
                centroid=target_track.centroid,
                coast_factor=1.0,
                time_lost_ms=0.0,
                target_locked=True,
            )

        # Case 3: Locked target is NOT present in this frame!
        # Evaluate safe coasting, holding, and timeout progression
        time_lost_ms = max(0.0, now_ms - self._last_seen_time_ms)
        self._coasting_frames += 1

        if time_lost_ms <= self.COASTING_WINDOW_MS:
            # Phase 1: Coasting (decay velocity smoothly)
            self._state = TargetState.COASTING
            coast_factor = self.COAST_DECAY_RATE ** self._coasting_frames
            return TargetSelectionResult(
                state=TargetState.COASTING,
                active_track=None,
                locked_track_id=self._locked_track_id,
                centroid=self._last_known_centroid,
                coast_factor=coast_factor,
                time_lost_ms=time_lost_ms,
                target_locked=True,
            )

        elif time_lost_ms <= self.reacquisition_timeout_ms:
            # Phase 2: Holding (servos hold position, zero velocity)
            self._state = TargetState.HOLDING
            return TargetSelectionResult(
                state=TargetState.HOLDING,
                active_track=None,
                locked_track_id=self._locked_track_id,
                centroid=self._last_known_centroid,
                coast_factor=0.0,
                time_lost_ms=time_lost_ms,
                target_locked=True,
            )

        else:
            # Phase 3: Timeout Exceeded!
            # Reset lock safely. CRITICAL: Do NOT jump to another person silently during tracking/coasting/holding!
            self._state = TargetState.LOST
            lost_id = self._locked_track_id
            self._locked_track_id = None
            if self._operating_mode == "locked_id":
                self._operating_mode = "idle"
            self._last_known_centroid = None
            self._coasting_frames = 0

            return TargetSelectionResult(
                state=TargetState.LOST,
                active_track=None,
                locked_track_id=lost_id,
                centroid=None,
                coast_factor=0.0,
                time_lost_ms=time_lost_ms,
                target_locked=False,
            )
