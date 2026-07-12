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

from .gaussmath import quat_to_rotmat

# Undistorted pinhole camera models train_base can consume directly. Anything else
# (OPENCV, RADIAL, FISHEYE, ...) carries distortion params that this pipeline drops
# silently — so those must be undistorted upstream and rejected here.
UNDISTORTED_MODELS = frozenset({"PINHOLE", "SIMPLE_PINHOLE"})


def qvec2rotmat(q) -> np.ndarray:
    """COLMAP qvec (w,x,y,z) -> 3x3 rotation matrix (float64). Thin wrapper over
    the shared vectorized `gaussmath.quat_to_rotmat`."""
    return quat_to_rotmat(q)


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
    """Parse images.txt. COLMAP writes exactly two lines per image (a metadata
    line, then a POINTS2D line that may be EMPTY for an image with no observations).

    A blank-line-dropping pass (the old `_data_lines`) shifts the 2-line pairing the
    moment any image has an empty POINTS2D line, silently corrupting poses. Parse
    statefully instead: a metadata line is one with >=10 whitespace fields
    (id, qw,qx,qy,qz, tx,ty,tz, cam_id, name...); the line after each metadata line
    is its POINTS2D line and is consumed regardless of content."""
    images = []
    expect_metadata = True
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("#"):
                continue
            if expect_metadata:
                t = line.split()
                if len(t) < 10:
                    # stray blank / short line before a metadata record — skip it
                    continue
                qvec = np.array(list(map(float, t[1:5])), dtype=np.float64)
                tvec = np.array(list(map(float, t[5:8])), dtype=np.float64)
                cam_id = int(t[8])
                name = " ".join(t[9:])   # filenames may contain spaces
                images.append(Image(name=name, camera_id=cam_id, qvec=qvec, tvec=tvec))
                expect_metadata = False
            else:
                # POINTS2D line for the image just read (may be empty) — consume it
                expect_metadata = True
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


def assert_undistorted(model: ColmapModel) -> None:
    """Raise ValueError unless every camera USED by a registered image is an
    undistorted pinhole model (PINHOLE / SIMPLE_PINHOLE).

    read_cameras_txt keeps fx/fy/cx/cy for distorted models (OPENCV etc.) but drops
    their distortion params — training on that model uses quietly wrong intrinsics
    and "works" while being geometrically wrong. This is the guard that turns that
    silent trap into a hard failure; train_base calls it right after load_model."""
    used = {im.camera_id for im in model.images} or set(model.cameras)
    bad = {cid: model.cameras[cid].model for cid in sorted(used)
           if cid in model.cameras and model.cameras[cid].model not in UNDISTORTED_MODELS}
    if bad:
        raise ValueError(
            "distorted COLMAP camera model(s) "
            f"{bad} — train_base needs an UNDISTORTED pinhole model. Point --sparse "
            "at the undistorted 'colmap/dense/sparse_txt' model (from "
            "`colmap image_undistorter` + `model_converter --output_type TXT`), "
            "NOT the raw SfM 'sparse/0' model.")
