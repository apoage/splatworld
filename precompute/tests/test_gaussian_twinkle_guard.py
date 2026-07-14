"""Frame guard for the diagnosis tool precompute.tools.gaussian_twinkle.

The tool applies the COLMAP->Godot conversion exactly once, so it must be fed a
COLMAP-frame decompose.ply and must REFUSE an already-Godot-frame exported asset.ply
(read_decompose_ply would otherwise read its columns and the normals would be
silently double-converted).
"""
import numpy as np
import pytest

from precompute.core import ply_io
from precompute.tools.gaussian_twinkle import assert_decompose_ply


def _tiny_decompose(path, n=8):
    rng = np.random.default_rng(0)
    rot = rng.standard_normal((n, 4)).astype(np.float32)
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    normal = rng.standard_normal((n, 3)).astype(np.float32)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    ply_io.write_decompose_ply(
        str(path),
        xyz=rng.standard_normal((n, 3)).astype(np.float32),
        sh0=rng.standard_normal((n, 3)).astype(np.float32),
        opacity=rng.standard_normal(n).astype(np.float32),
        scales=rng.standard_normal((n, 3)).astype(np.float32),
        quats=rot,
        albedo=rng.random((n, 3), dtype=np.float32),
        normal=normal,
        rough=rng.random(n, dtype=np.float32),
    )


def _tiny_asset(path, n=8):
    rng = np.random.default_rng(1)
    rot = rng.standard_normal((n, 4)).astype(np.float32)
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    normal = rng.standard_normal((n, 3)).astype(np.float32)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    ply_io.write_asset_ply(str(path), ply_io.AssetGaussians(
        xyz=rng.standard_normal((n, 3)).astype(np.float32),
        scale=rng.standard_normal((n, 3)).astype(np.float32),
        rot=rot,
        opacity=rng.standard_normal(n).astype(np.float32),
        albedo=rng.random((n, 3), dtype=np.float32),
        normal=normal,
        rough=rng.random(n, dtype=np.float32),
        trans=rng.random(n, dtype=np.float32),
        label=rng.integers(0, 4, n, dtype=np.uint8),
        basis=None,
    ))


def test_guard_accepts_decompose_ply(tmp_path):
    p = tmp_path / "decompose.ply"
    _tiny_decompose(p)
    assert_decompose_ply(str(p))            # must NOT raise


def test_guard_refuses_exported_asset_ply(tmp_path):
    p = tmp_path / "asset.ply"
    _tiny_asset(p)
    with pytest.raises(SystemExit, match="splat_relight_schema"):
        assert_decompose_ply(str(p))
