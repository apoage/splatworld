"""World-up estimation from the camera rig — ground-alignment heuristic.

The capture phone knew "down" at record time (g-sensor), but no usable IMU data
reaches the pipeline, and SfM's world frame is gauge-arbitrary: nothing in the
COLMAP model tells us which way is up. For walkaround / orbit captures the camera
rig itself is the cue — the operator walks a roughly level loop around the subject,
so the camera CENTERS lie near a horizontal plane whose normal is world up.

This module estimates that up direction in the COLMAP world frame and builds the
proper rotation that carries it onto Godot's +Y. Pure numpy, no torch, no PLY /
COLMAP I/O — callers hand in plain arrays so the estimator is trivially unit-tested.

COLMAP convention (OpenCV): x-right, y-DOWN, z-forward; poses are world->camera, so
a camera's up-vector in world coords is -(row 1 of its world->cam rotation R).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


def _unit(v: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / max(float(np.linalg.norm(v)), eps)


@dataclass
class UpEstimate:
    up: np.ndarray                 # (3,) unit, COLMAP frame
    method: str                    # "plane_fit" | "camera_up_fallback"
    confidence: float              # [0,1]; 0.0 for the degenerate fallback
    plane_residual_rms: float      # RMS perpendicular camera distance to the fit plane (world units)
    mean_camera_up: np.ndarray     # (3,) unit, COLMAP frame
    n_cameras: int
    singular_values: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "confidence": float(self.confidence),
            "plane_residual_rms": float(self.plane_residual_rms),
            "up_colmap": [float(x) for x in self.up],
            "mean_camera_up_colmap": [float(x) for x in self.mean_camera_up],
            "n_cameras": int(self.n_cameras),
            "singular_values": [float(s) for s in self.singular_values],
        }


def estimate_up_from_cameras(centers: np.ndarray,
                             camera_ups: np.ndarray,
                             *,
                             collinear_ratio: float = 1e-2) -> UpEstimate:
    """Estimate world up (COLMAP frame) from the camera rig.

    Least-squares plane fit through the camera `centers` (N,3): up = plane normal
    (the right-singular vector of the smallest singular value of the centered
    centers), sign chosen so the mean `camera_ups` vector has positive dot with it.

    Degenerate fallback: when the centers are (near-)collinear the plane is
    ill-defined — the second singular value collapses relative to the first
    (`s1/s0 < collinear_ratio`) — or there are fewer than 3 cameras. Then up is
    just the mean camera up-vector and confidence is 0.0.

    `camera_ups` is one world-space up-vector per camera (COLMAP: -R row 1).
    Returns an `UpEstimate`. Confidence for the plane-fit path is
    `1 - s2/s1` clamped to [0,1] (how flat the ring's off-plane spread is relative
    to its in-plane spread); the raw plane residual is reported separately.
    """
    centers = np.asarray(centers, dtype=np.float64).reshape(-1, 3)
    camera_ups = np.asarray(camera_ups, dtype=np.float64).reshape(-1, 3)
    n = int(centers.shape[0])
    mean_up = _unit(camera_ups.mean(axis=0))

    if n < 3:
        return UpEstimate(up=mean_up, method="camera_up_fallback", confidence=0.0,
                          plane_residual_rms=0.0, mean_camera_up=mean_up, n_cameras=n,
                          singular_values=np.zeros(3))

    centroid = centers.mean(axis=0)
    a = centers - centroid
    _u, s, vh = np.linalg.svd(a, full_matrices=False)
    s = np.asarray(s, dtype=np.float64)
    s0, s1, s2 = float(s[0]), float(s[1]), float(s[2])

    degenerate = (s0 <= 1e-12) or (s1 / s0 < float(collinear_ratio))
    if degenerate:
        return UpEstimate(up=mean_up, method="camera_up_fallback", confidence=0.0,
                          plane_residual_rms=(s2 / np.sqrt(n)),
                          mean_camera_up=mean_up, n_cameras=n, singular_values=s)

    normal = _unit(vh[2])
    if float(np.dot(normal, mean_up)) < 0.0:
        normal = -normal
    confidence = float(np.clip(1.0 - (s2 / s1), 0.0, 1.0)) if s1 > 0 else 0.0
    return UpEstimate(up=normal, method="plane_fit", confidence=confidence,
                      plane_residual_rms=(s2 / np.sqrt(n)),
                      mean_camera_up=mean_up, n_cameras=n, singular_values=s)


def rotation_between_vectors(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest-arc proper rotation R (3x3, det +1) with R @ a_hat = b_hat.

    `a`, `b` need not be unit. Handles a≈b (identity) and a≈-b (a stable 180deg
    rotation about an axis perpendicular to a)."""
    a = _unit(a)
    b = _unit(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c > 1.0 - 1e-12:
        return np.eye(3, dtype=np.float64)
    if c < -1.0 + 1e-12:
        # antiparallel: 180deg about any axis perpendicular to a. R = 2 u u^T - I.
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if float(np.linalg.norm(axis)) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = _unit(axis)
        return (2.0 * np.outer(axis, axis) - np.eye(3)).astype(np.float64)
    k = np.array([[0.0, -v[2], v[1]],
                  [v[2], 0.0, -v[0]],
                  [-v[1], v[0], 0.0]], dtype=np.float64)
    return (np.eye(3) + k + k @ k * (1.0 / (1.0 + c))).astype(np.float64)


# The COLMAP direction that the COLMAP->Godot flip M=diag(1,-1,-1) sends to Godot
# +Y (up): M @ v = (0,1,0) <=> v = M @ (0,1,0) = (0,-1,0) (M is an involution).
UP_TARGET_COLMAP = np.array([0.0, -1.0, 0.0], dtype=np.float64)


def align_up_rotation(up_colmap: np.ndarray) -> np.ndarray:
    """R_align (3x3, det +1, COLMAP frame) mapping the estimated up onto
    UP_TARGET_COLMAP=(0,-1,0) — the direction M=diag(1,-1,-1) then carries to Godot
    +Y. Composing M @ R_align makes the estimated up render straight up in Godot."""
    return rotation_between_vectors(np.asarray(up_colmap, dtype=np.float64), UP_TARGET_COLMAP)
