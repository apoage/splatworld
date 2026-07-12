"""Tests for core/colmap_io.py — the COLMAP TXT model reader (items 7, 12).

Covers: qvec->R known answers, images.txt pairing INCLUDING the empty-POINTS2D
case (the pairing-shift bug) and filenames with spaces, PINHOLE vs OPENCV camera
branches, and the assert_undistorted guard train_base relies on.
"""
import numpy as np
import pytest

from precompute.core import colmap_io
from precompute.core.colmap_io import Camera, Image, ColmapModel, assert_undistorted


# --- item 12: qvec -> rotation matrix known answers ---------------------------
def test_qvec2rotmat_identity():
    np.testing.assert_allclose(colmap_io.qvec2rotmat([1.0, 0.0, 0.0, 0.0]), np.eye(3), atol=1e-12)


def test_qvec2rotmat_180_about_z():
    np.testing.assert_allclose(colmap_io.qvec2rotmat([0.0, 0.0, 0.0, 1.0]),
                               np.diag([-1.0, -1.0, 1.0]), atol=1e-12)


def _write(path, lines):
    path.write_text("\n".join(lines) + "\n")


def _cameras_txt(tmp_path, body_lines):
    p = tmp_path / "cameras.txt"
    _write(p, ["# Camera list", *body_lines])
    return p


def _images_txt(tmp_path, records):
    """records: list of (meta_line, points_line)."""
    lines = ["# Image list with two lines of data per image:", "#   header"]
    for meta, pts in records:
        lines.append(meta)
        lines.append(pts)     # may be "" (empty POINTS2D)
    p = tmp_path / "images.txt"
    _write(p, lines)
    return p


def _points3d_txt(tmp_path):
    p = tmp_path / "points3D.txt"
    _write(p, ["# 3D points", "1 0.0 0.0 0.0 10 20 30 0.5 1 0 2 1"])
    return p


# --- item 12: camera model branches -------------------------------------------
def test_read_cameras_pinhole_and_opencv(tmp_path):
    p = _cameras_txt(tmp_path, [
        "1 PINHOLE 1000 800 500 501 400 300",
        "2 SIMPLE_PINHOLE 640 480 520 320 240",
        "3 OPENCV 1080 1440 700 701 540 720 0.01 -0.02 0.001 0.0005",
    ])
    cams = colmap_io.read_cameras_txt(str(p))
    assert cams[1].model == "PINHOLE" and cams[1].fx == 500 and cams[1].cy == 300
    assert cams[2].model == "SIMPLE_PINHOLE" and cams[2].fx == cams[2].fy == 520
    # OPENCV: fx/fy/cx/cy kept, distortion silently dropped (that is why the guard exists)
    assert cams[3].model == "OPENCV" and cams[3].fx == 700 and cams[3].cy == 720


# --- item 7: images.txt pairing, empty points, spaces in names ----------------
def test_images_txt_basic_pairing(tmp_path):
    recs = [
        ("1 1 0 0 0 0.1 0.2 0.3 1 frame_0001.jpg", "12.0 3.0 -1 4.0 5.0 -1"),
        ("2 0 0 0 1 1.0 2.0 3.0 1 frame_0002.jpg", "6.0 7.0 -1"),
    ]
    imgs = colmap_io.read_images_txt(str(_images_txt(tmp_path, recs)))
    assert [im.name for im in imgs] == ["frame_0001.jpg", "frame_0002.jpg"]
    assert imgs[0].camera_id == 1 and imgs[1].camera_id == 1
    np.testing.assert_allclose(imgs[0].qvec, [1, 0, 0, 0])
    np.testing.assert_allclose(imgs[1].tvec, [1.0, 2.0, 3.0])


def test_images_txt_empty_points_does_not_shift_pairing(tmp_path):
    # image 1 has an EMPTY POINTS2D line — the old blank-dropping parser shifted
    # the 2-line pairing and corrupted every subsequent pose.
    recs = [
        ("1 1 0 0 0 0.1 0.2 0.3 1 a.jpg", ""),   # empty points line
        ("2 0 1 0 0 1.0 2.0 3.0 2 b.jpg", "9.0 8.0 -1"),
    ]
    imgs = colmap_io.read_images_txt(str(_images_txt(tmp_path, recs)))
    assert len(imgs) == 2
    assert [im.name for im in imgs] == ["a.jpg", "b.jpg"]
    assert imgs[0].camera_id == 1 and imgs[1].camera_id == 2
    np.testing.assert_allclose(imgs[1].qvec, [0, 1, 0, 0])
    np.testing.assert_allclose(imgs[1].tvec, [1.0, 2.0, 3.0])


def test_images_txt_filename_with_spaces(tmp_path):
    recs = [("1 1 0 0 0 0 0 0 1 my frame 01.jpg", "1.0 2.0 -1")]
    imgs = colmap_io.read_images_txt(str(_images_txt(tmp_path, recs)))
    assert imgs[0].name == "my frame 01.jpg"


def test_load_model_end_to_end(tmp_path):
    _cameras_txt(tmp_path, ["1 PINHOLE 1000 800 500 501 400 300"])
    _images_txt(tmp_path, [("1 1 0 0 0 0 0 0 1 a.jpg", "")])
    _points3d_txt(tmp_path)
    m = colmap_io.load_model(str(tmp_path))
    assert len(m.images) == 1 and m.points_xyz.shape == (1, 3)
    assert_undistorted(m)   # PINHOLE -> ok, no raise


# --- item 3/12: assert_undistorted guard --------------------------------------
def _model(cam_model):
    cams = {1: Camera(cam_model, 100, 100, 50, 50, 50, 50)}
    imgs = [Image(name="a.jpg", camera_id=1,
                  qvec=np.array([1.0, 0, 0, 0]), tvec=np.zeros(3))]
    return ColmapModel(cameras=cams, images=imgs,
                       points_xyz=np.zeros((0, 3)), points_rgb=np.zeros((0, 3), np.uint8))


def test_assert_undistorted_accepts_pinhole():
    assert_undistorted(_model("PINHOLE"))
    assert_undistorted(_model("SIMPLE_PINHOLE"))


def test_assert_undistorted_rejects_opencv():
    with pytest.raises(ValueError, match="distorted"):
        assert_undistorted(_model("OPENCV"))
