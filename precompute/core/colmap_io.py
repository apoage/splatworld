"""Minimal COLMAP model reader (TXT format).

Reads a COLMAP sparse model exported as text (cameras.txt / images.txt /
points3D.txt) — as produced by `colmap model_converter --output_type TXT`.
Used by `train_base` to get intrinsics, per-image world->cam poses, and the SfM
point cloud for Gaussian initialization.

COLMAP convention (OpenCV): x-right, y-down, z-forward; poses are world->camera.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


def qvec2rotmat(q) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


@dataclass
class Camera:
    model: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0, self.cx],
                         [0, self.fy, self.cy],
                         [0, 0, 1]], dtype=np.float64)


@dataclass
class Image:
    name: str
    camera_id: int
    qvec: np.ndarray      # (4,) w,x,y,z
    tvec: np.ndarray      # (3,)

    def viewmat(self) -> np.ndarray:
        """4x4 world->camera."""
        R = qvec2rotmat(self.qvec)
        V = np.eye(4, dtype=np.float64)
        V[:3, :3] = R
        V[:3, 3] = self.tvec
        return V

    def center(self) -> np.ndarray:
        """Camera center in world coords: -R^T t."""
        R = qvec2rotmat(self.qvec)
        return -R.T @ self.tvec


@dataclass
class ColmapModel:
    cameras: dict          # {id: Camera}
    images: list           # [Image] (registered, in file order)
    points_xyz: np.ndarray # (M,3) f64
    points_rgb: np.ndarray # (M,3) u8


def _data_lines(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                yield line


def read_cameras_txt(path) -> dict:
    cams = {}
    for line in _data_lines(path):
        t = line.split()
        cid, model, w, h = int(t[0]), t[1], int(t[2]), int(t[3])
        params = list(map(float, t[4:]))
        if model in ("PINHOLE",):
            fx, fy, cx, cy = params[0], params[1], params[2], params[3]
        elif model in ("SIMPLE_PINHOLE",):
            fx = fy = params[0]; cx, cy = params[1], params[2]
        else:
            # OPENCV etc.: fx fy cx cy [distortion...]; distortion ignored here
            # (train on the undistorted PINHOLE model instead).
            fx, fy, cx, cy = params[0], params[1], params[2], params[3]
        cams[cid] = Camera(model, w, h, fx, fy, cx, cy)
    return cams


def read_images_txt(path) -> list:
    lines = list(_data_lines(path))
    images = []
    # two lines per image: metadata, then 2D points (skip the points line)
    for i in range(0, len(lines), 2):
        t = lines[i].split()
        qvec = np.array(list(map(float, t[1:5])), dtype=np.float64)
        tvec = np.array(list(map(float, t[5:8])), dtype=np.float64)
        cam_id = int(t[8])
        name = t[9]
        images.append(Image(name=name, camera_id=cam_id, qvec=qvec, tvec=tvec))
    return images


def read_points3D_txt(path):
    xyz, rgb = [], []
    for line in _data_lines(path):
        t = line.split()
        xyz.append([float(t[1]), float(t[2]), float(t[3])])
        rgb.append([int(t[4]), int(t[5]), int(t[6])])
    return (np.asarray(xyz, np.float64).reshape(-1, 3),
            np.asarray(rgb, np.uint8).reshape(-1, 3))


def load_model(sparse_txt_dir: str) -> ColmapModel:
    import os
    cams = read_cameras_txt(os.path.join(sparse_txt_dir, "cameras.txt"))
    imgs = read_images_txt(os.path.join(sparse_txt_dir, "images.txt"))
    xyz, rgb = read_points3D_txt(os.path.join(sparse_txt_dir, "points3D.txt"))
    return ColmapModel(cameras=cams, images=imgs, points_xyz=xyz, points_rgb=rgb)
