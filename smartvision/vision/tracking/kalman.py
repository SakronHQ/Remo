"""
SmartVision - Kalman Filter for Bounding Box State Estimation
8-dimensional constant-velocity Kalman Filter implemented in pure NumPy.
State vector: [cx, cy, a, h, v_cx, v_cy, v_a, v_h]
Measurement vector: [cx, cy, a, h]
"""

from typing import Tuple

import numpy as np


class BoxKalmanFilter:
    """
    Kalman filter tracking the 8-dimensional state vector of a bounding box:
    [center_x, center_y, aspect_ratio (w/h), height, v_cx, v_cy, v_a, v_h].
    """

    def __init__(self):
        ndim = 4
        dt = 1.0

        # Motion model state transition matrix F
        self._motion_mat = np.eye(2 * ndim, 2 * ndim, dtype=np.float64)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt

        # Measurement matrix H
        self._update_mat = np.eye(ndim, 2 * ndim, dtype=np.float64)

        # Motion and measurement uncertainty weights
        self._std_weight_position = 1.0 / 20.0
        self._std_weight_velocity = 1.0 / 160.0

    def initiate(self, measurement: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Initializes track state mean and covariance from an initial bounding box measurement [cx, cy, a, h].
        """
        mean_pos = measurement.astype(np.float64)
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]
        h = max(1.0, float(measurement[3]))

        std = [
            2 * self._std_weight_position * h,
            2 * self._std_weight_position * h,
            1e-2,
            2 * self._std_weight_position * h,
            10 * self._std_weight_velocity * h,
            10 * self._std_weight_velocity * h,
            1e-5,
            10 * self._std_weight_velocity * h,
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Projects state distribution forward by one time step.
        """
        h = max(1.0, float(mean[3]))
        std_pos = [
            self._std_weight_position * h,
            self._std_weight_position * h,
            1e-2,
            self._std_weight_position * h,
        ]
        std_vel = [
            self._std_weight_velocity * h,
            self._std_weight_velocity * h,
            1e-5,
            self._std_weight_velocity * h,
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))

        mean = np.dot(self._motion_mat, mean)
        covariance = np.linalg.multi_dot((self._motion_mat, covariance, self._motion_mat.T)) + motion_cov
        return mean, covariance

    def project(self, mean: np.ndarray, covariance: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Projects state distribution into measurement space [cx, cy, a, h].
        """
        h = max(1.0, float(mean[3]))
        std = [
            self._std_weight_position * h,
            self._std_weight_position * h,
            1e-1,
            self._std_weight_position * h,
        ]
        innovation_cov = np.diag(np.square(std))

        mean = np.dot(self._update_mat, mean)
        covariance = np.linalg.multi_dot((self._update_mat, covariance, self._update_mat.T)) + innovation_cov
        return mean, covariance

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Performs Kalman measurement update using new bounding box [cx, cy, a, h].
        """
        projected_mean, projected_cov = self.project(mean, covariance)

        # Kalman gain K = P H^T (H P H^T + R)^-1
        chol_factor, lower = self._safe_cholesky(projected_cov)
        b = np.dot(covariance, self._update_mat.T).T
        kalman_gain = self._solve_cholesky(chol_factor, lower, b).T

        innovation = measurement - projected_mean
        new_mean = mean + np.dot(innovation, kalman_gain.T)
        new_covariance = covariance - np.linalg.multi_dot((kalman_gain, projected_cov, kalman_gain.T))
        return new_mean, new_covariance

    @staticmethod
    def _safe_cholesky(matrix: np.ndarray) -> Tuple[np.ndarray, bool]:
        """Cholesky decomposition with diagonal regularization for numerical stability."""
        try:
            return np.linalg.cholesky(matrix), True
        except np.linalg.LinAlgError:
            try:
                reg = matrix + np.eye(matrix.shape[0]) * 1e-4
                return np.linalg.cholesky(reg), True
            except np.linalg.LinAlgError:
                reg = matrix + np.eye(matrix.shape[0]) * 1e-2
                return np.linalg.cholesky(reg), True

    @staticmethod
    def _solve_cholesky(chol: np.ndarray, lower: bool, b: np.ndarray) -> np.ndarray:
        """Solves linear system A x = b using Cholesky factor."""
        # A = L L^T => L y = b, L^T x = y
        y = np.linalg.solve(chol, b)
        x = np.linalg.solve(chol.T, y)
        return x

    @staticmethod
    def tlwh_to_xyah(tlwh: np.ndarray) -> np.ndarray:
        """Converts [top-left-x, top-left-y, width, height] to [cx, cy, aspect_ratio, height]."""
        ret = np.asarray(tlwh, dtype=np.float64).copy()
        ret[:2] += ret[2:] / 2.0
        ret[2] /= max(1e-6, ret[3])
        return ret

    @staticmethod
    def xyah_to_tlwh(xyah: np.ndarray) -> np.ndarray:
        """Converts [cx, cy, aspect_ratio, height] to [top-left-x, top-left-y, width, height]."""
        ret = np.asarray(xyah, dtype=np.float64).copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2.0
        return ret

    @staticmethod
    def xyah_to_xyxy(xyah: np.ndarray) -> np.ndarray:
        """Converts [cx, cy, aspect_ratio, height] to [x1, y1, x2, y2]."""
        tlwh = BoxKalmanFilter.xyah_to_tlwh(xyah)
        return np.array([tlwh[0], tlwh[1], tlwh[0] + tlwh[2], tlwh[1] + tlwh[3]], dtype=np.float64)
