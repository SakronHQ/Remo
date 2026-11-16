"""
SmartVision - ByteTrack Multi-Object Tracking Engine
High-performance, pure NumPy implementation of ByteTrack multi-person tracking.
Maintains persistent track IDs across frames and handles brief occlusions via two-stage
association (high-confidence and low-confidence detection matching).
"""

from enum import IntEnum
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from ..detection.types import PersonDetection
from .kalman import BoxKalmanFilter


class TrackState(IntEnum):
    """Lifecycle state of an individual tracking tracklet."""
    New = 0
    Tracked = 1
    Lost = 2
    Removed = 3


def bbox_ious(atlbrs: np.ndarray, btlbrs: np.ndarray) -> np.ndarray:
    """
    Computes pairwise IoU between two sets of bounding boxes.
    atlbrs: shape (N, 4) in [x1, y1, x2, y2]
    btlbrs: shape (M, 4) in [x1, y1, x2, y2]
    Returns: IoU matrix of shape (N, M)
    """
    if atlbrs.size == 0 or btlbrs.size == 0:
        return np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)

    ious = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    for i, a in enumerate(atlbrs):
        area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
        for j, b in enumerate(btlbrs):
            area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
            iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
            ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            inter = iw * ih
            union = area_a + area_b - inter
            if union > 0.0:
                ious[i, j] = inter / union
    return ious


def linear_assignment(
    cost_matrix: np.ndarray, thresh: float
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """
    Associates tracks and detections minimizing cost via greedy bipartite matching.
    Matches with cost > thresh are rejected.
    Returns: (matches, unmatched_a, unmatched_b)
    """
    if cost_matrix.size == 0:
        return [], list(range(cost_matrix.shape[0])), list(range(cost_matrix.shape[1]))

    num_a, num_b = cost_matrix.shape
    matched_a: Set[int] = set()
    matched_b: Set[int] = set()
    matches: List[Tuple[int, int]] = []

    # Flatten and sort pairs by ascending cost
    indices = np.argsort(cost_matrix, axis=None)
    for idx in indices:
        row = int(idx // num_b)
        col = int(idx % num_b)
        val = cost_matrix[row, col]
        if np.isnan(val) or val > thresh:
            break
        if row in matched_a or col in matched_b:
            continue
        matched_a.add(row)
        matched_b.add(col)
        matches.append((row, col))

    unmatched_a = [i for i in range(num_a) if i not in matched_a]
    unmatched_b = [j for j in range(num_b) if j not in matched_b]
    return matches, unmatched_a, unmatched_b


class STrack:
    """
    Single Track representation tracking an individual person across time.
    """

    _count = 0

    @classmethod
    def next_id(cls) -> int:
        cls._count += 1
        return cls._count

    @classmethod
    def reset_counter(cls) -> None:
        cls._count = 0

    def __init__(self, detection: PersonDetection, frame_id: int, track_id: Optional[int] = None):
        if track_id is not None:
            self.track_id = track_id
        else:
            self.track_id = STrack.next_id()
        self.state = TrackState.New
        self.is_activated = False

        self.kalman_filter = BoxKalmanFilter()
        tlwh = detection.to_tlwh()
        xyah = self.kalman_filter.tlwh_to_xyah(np.array(tlwh, dtype=np.float64))
        self.mean, self.covariance = self.kalman_filter.initiate(xyah)

        self.score = float(detection.confidence)
        self.frame_id = frame_id
        self.start_frame = frame_id
        self.tracklet_len = 0
        self.time_since_update = 0

        self.detection = detection
        self._current_tlwh = np.array(tlwh, dtype=np.float64)

    @property
    def tlwh(self) -> np.ndarray:
        return self._current_tlwh

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """Returns [x1, y1, x2, y2]."""
        x1 = float(self._current_tlwh[0])
        y1 = float(self._current_tlwh[1])
        x2 = float(x1 + self._current_tlwh[2])
        y2 = float(y1 + self._current_tlwh[3])
        return (x1, y1, x2, y2)

    @property
    def bbox_int(self) -> Tuple[int, int, int, int]:
        """Returns integer [x1, y1, x2, y2]."""
        b = self.bbox
        return (int(round(b[0])), int(round(b[1])), int(round(b[2])), int(round(b[3])))

    @property
    def centroid(self) -> Tuple[float, float]:
        """Returns centroid (cx, cy)."""
        b = self.bbox
        return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)

    @property
    def area(self) -> float:
        """Bounding box area in pixels."""
        return float(self._current_tlwh[2] * self._current_tlwh[3])

    def predict(self) -> None:
        """Projects state vector forward via Kalman motion model."""
        if self.state != TrackState.Tracked:
            self.mean[7] = 0.0  # zero out velocity if lost
        self.mean, self.covariance = self.kalman_filter.predict(self.mean, self.covariance)
        self._update_tlwh_from_mean()

    def update(self, new_detection: PersonDetection, frame_id: int) -> None:
        """Updates Kalman state and bounding box from new detection."""
        self.frame_id = frame_id
        self.tracklet_len += 1
        self.time_since_update = 0
        self.state = TrackState.Tracked
        self.is_activated = True
        self.score = float(new_detection.confidence)
        self.detection = new_detection

        tlwh = np.array(new_detection.to_tlwh(), dtype=np.float64)
        xyah = self.kalman_filter.tlwh_to_xyah(tlwh)
        self.mean, self.covariance = self.kalman_filter.update(self.mean, self.covariance, xyah)
        self._update_tlwh_from_mean()

    def re_activate(self, new_detection: PersonDetection, frame_id: int) -> None:
        """Re-activates a previously lost track upon re-detection."""
        self.update(new_detection, frame_id)

    def mark_lost(self) -> None:
        """Transitions track into Lost state."""
        self.state = TrackState.Lost

    def mark_removed(self) -> None:
        """Transitions track into Removed state."""
        self.state = TrackState.Removed

    def _update_tlwh_from_mean(self) -> None:
        xyah = self.mean[:4].copy()
        self._current_tlwh = self.kalman_filter.xyah_to_tlwh(xyah)


class ByteTracker:
    """
    ByteTrack Multi-Object Tracker.
    Maintains persistent IDs and handles temporary occlusions via two-stage association.
    """

    def __init__(
        self,
        track_thresh: float = 0.50,
        low_thresh: float = 0.10,
        match_thresh: float = 0.80,
        low_match_thresh: float = 0.50,
        max_lost_frames: int = 30,
        new_track_thresh: float = 0.60,
    ):
        """
        Args:
            track_thresh: Threshold for high-confidence detections (Stage 1).
            low_thresh: Threshold for low-confidence detections (Stage 2).
            match_thresh: Maximum cost (1.0 - IoU) for Stage 1 association (0.80 => IoU >= 0.20).
            low_match_thresh: Maximum cost for Stage 2 association (0.50 => IoU >= 0.50).
            max_lost_frames: Number of frames to retain lost tracks before removing.
            new_track_thresh: Minimum score to initialize a new track from unmatched detection.
        """
        self.track_thresh = track_thresh
        self.low_thresh = low_thresh
        self.match_thresh = match_thresh
        self.low_match_thresh = low_match_thresh
        self.max_lost_frames = max_lost_frames
        self.new_track_thresh = new_track_thresh

        self.frame_id = 0
        self._next_track_id = 0
        self.tracked_tracks: List[STrack] = []
        self.lost_tracks: List[STrack] = []
        self.removed_tracks: List[STrack] = []

    def _get_next_id(self) -> int:
        self._next_track_id += 1
        return self._next_track_id

    def reset(self) -> None:
        """Resets tracker state and tracklet ID counter."""
        self.frame_id = 0
        self._next_track_id = 0
        self.tracked_tracks.clear()
        self.lost_tracks.clear()
        self.removed_tracks.clear()
        STrack.reset_counter()

    def update(self, detections: List[PersonDetection]) -> List[STrack]:
        """
        Processes new frame detections and returns all active confirmed tracks.
        """
        self.frame_id += 1

        # 1. Partition detections into high-score and low-score pools
        dets_high: List[PersonDetection] = []
        dets_low: List[PersonDetection] = []

        for det in detections:
            if det.confidence >= self.track_thresh:
                dets_high.append(det)
            elif det.confidence >= self.low_thresh:
                dets_low.append(det)

        # 2. Predict next positions using Kalman Filter
        for t in self.tracked_tracks:
            t.predict()
            t.time_since_update += 1

        for t in self.lost_tracks:
            t.predict()
            t.time_since_update += 1

        # ---------------------------------------------------------------------
        # STAGE 1: First Association (Tracked tracks vs High-score detections)
        # ---------------------------------------------------------------------
        tracked_boxes = np.array([t.bbox for t in self.tracked_tracks], dtype=np.float64)
        high_boxes = np.array([d.bbox_float for d in dets_high], dtype=np.float64)

        ious_1 = bbox_ious(tracked_boxes, high_boxes)
        cost_matrix_1 = 1.0 - ious_1

        matches_1, u_tracks_1, u_dets_high_idx = linear_assignment(cost_matrix_1, self.match_thresh)

        # Update matched tracks
        for track_idx, det_idx in matches_1:
            self.tracked_tracks[track_idx].update(dets_high[det_idx], self.frame_id)

        unmatched_tracked_tracks = [self.tracked_tracks[i] for i in u_tracks_1]
        remaining_high_dets = [dets_high[j] for j in u_dets_high_idx]

        # ---------------------------------------------------------------------
        # STAGE 2: Second Association (Unmatched tracks vs Low-score detections)
        # Prevents losing tracks during occlusions, motion blur, or partial views
        # ---------------------------------------------------------------------
        u_track_boxes = np.array([t.bbox for t in unmatched_tracked_tracks], dtype=np.float64)
        low_boxes = np.array([d.bbox_float for d in dets_low], dtype=np.float64)

        ious_2 = bbox_ious(u_track_boxes, low_boxes)
        cost_matrix_2 = 1.0 - ious_2

        matches_2, u_tracks_2, _ = linear_assignment(cost_matrix_2, self.low_match_thresh)

        for track_sub_idx, det_idx in matches_2:
            unmatched_tracked_tracks[track_sub_idx].update(dets_low[det_idx], self.frame_id)

        # Tracks that failed both Stage 1 and Stage 2 become Lost
        for track_sub_idx in u_tracks_2:
            t = unmatched_tracked_tracks[track_sub_idx]
            t.mark_lost()

        # ---------------------------------------------------------------------
        # STAGE 3: Third Association (Lost tracks vs Remaining High-score detections)
        # Re-acquires tracks that temporarily disappeared and returned
        # ---------------------------------------------------------------------
        lost_boxes = np.array([t.bbox for t in self.lost_tracks], dtype=np.float64)
        rem_high_boxes = np.array([d.bbox_float for d in remaining_high_dets], dtype=np.float64)

        ious_3 = bbox_ious(lost_boxes, rem_high_boxes)
        cost_matrix_3 = 1.0 - ious_3

        matches_3, u_lost_idx, u_final_high_idx = linear_assignment(cost_matrix_3, self.match_thresh)

        for lost_idx, det_idx in matches_3:
            self.lost_tracks[lost_idx].re_activate(remaining_high_dets[det_idx], self.frame_id)

        # ---------------------------------------------------------------------
        # STAGE 4: Initialize New Tracks from Unmatched High-score Detections
        # ---------------------------------------------------------------------
        new_tracks: List[STrack] = []
        for det_idx in u_final_high_idx:
            det = remaining_high_dets[det_idx]
            if det.confidence >= self.new_track_thresh:
                new_track = STrack(det, self.frame_id, track_id=self._get_next_id())
                new_track.is_activated = True
                new_track.state = TrackState.Tracked
                new_tracks.append(new_track)

        # ---------------------------------------------------------------------
        # STAGE 5: Pool Maintenance & Pruning
        # ---------------------------------------------------------------------
        all_tracks = self.tracked_tracks + self.lost_tracks + new_tracks
        new_tracked: List[STrack] = []
        new_lost: List[STrack] = []

        seen_ids: Set[int] = set()
        for t in all_tracks:
            if t.track_id in seen_ids:
                continue
            seen_ids.add(t.track_id)

            if t.state == TrackState.Tracked:
                new_tracked.append(t)
            elif t.state == TrackState.Lost:
                if t.time_since_update <= self.max_lost_frames:
                    new_lost.append(t)
                else:
                    t.mark_removed()
                    self.removed_tracks.append(t)

        self.tracked_tracks = new_tracked
        self.lost_tracks = new_lost

        # Return only active, activated tracks
        output_tracks = [t for t in self.tracked_tracks if t.is_activated and t.state == TrackState.Tracked]
        return output_tracks
