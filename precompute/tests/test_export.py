"""Known-answer tests for export.shortest_axis_normals (item 13).

The exported normal is the covariance axis with the SMALLEST scale (flattest
direction) = the corresponding column of the Gaussian's rotation matrix. Uses
axis-aligned quats with unequal scales so the expected column is exact.
"""
import sys

import numpy as np
import pytest

from precompute.core import ply_io
from precompute.stages import export as export_mod
from precompute.stages.export import shortest_axis_normals, floater_prune_mask

_S = np.sqrt(0.5)


def _logit(p):
    return np.log(p / (1.0 - p))


def test_floater_prune_default_off_keeps_all():
    # No criteria enabled -> keep everything, byte-unchanged export path.
    n = 50
    rng = np.random.default_rng(0)
    opac = _logit(np.full(n, 0.5))
    scale = np.log(np.full((n, 3), 0.1))
    xyz = rng.normal(size=(n, 3))
    keep, info = floater_prune_mask(opac, scale, xyz)
    assert keep.all()
    assert info["enabled"] is False
    assert info["n_after"] == n and info["n_pruned"] == 0


def test_floater_prune_opacity_drops_transparent():
    # A dense body at opacity 0.6 + a few near-transparent splats at 0.001.
    opac = _logit(np.array([0.6, 0.6, 0.6, 0.6, 0.001, 0.001], np.float64))
    scale = np.log(np.full((6, 3), 0.1))
    xyz = np.zeros((6, 3))
    keep, info = floater_prune_mask(opac, scale, xyz, prune_opacity=0.02)
    assert info["n_by_opacity"] == 2
    assert list(keep) == [True, True, True, True, False, False]


def test_floater_prune_isolation_drops_outlier():
    # A tight cluster near the origin + one far-away isolated floater.
    cluster = np.zeros((20, 3)) + np.linspace(0, 0.05, 20)[:, None]
    floater = np.array([[100.0, 100.0, 100.0]])
    xyz = np.vstack([cluster, floater])
    opac = _logit(np.full(len(xyz), 0.5))
    scale = np.log(np.full((len(xyz), 3), 0.1))
    keep, info = floater_prune_mask(opac, scale, xyz, prune_isolation_std=3.0, isolation_k=3)
    assert info["n_by_isolation"] >= 1
    assert keep[-1] == False          # the far floater is dropped
    assert keep[:20].all()            # the cluster is kept


def test_export_empty_prune_fails_closed_without_clobber(tmp_path, monkeypatch):
    # A prune that removes ALL Gaussians must fail-closed with a clear SystemExit
    # BEFORE writing anything — never clobbering a pre-existing good asset.ply.
    n = 8
    rng = np.random.default_rng(1)
    xyz = rng.normal(size=(n, 3)).astype(np.float32)
    sh0 = rng.normal(size=(n, 3)).astype(np.float32)
    shN = np.zeros((n, 0, 3), np.float32)
    opacity = np.zeros(n, np.float32)                 # logit 0 -> sigmoid 0.5
    scales = np.log(np.full((n, 3), 0.1, np.float32))
    quats = np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1))
    inp = tmp_path / "train_base.ply"
    ply_io.write_standard_3dgs_ply(str(inp), xyz, sh0, shN, opacity, scales, quats)

    out = tmp_path / "asset.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)                          # pre-existing good asset

    # --prune-opacity 1.0 => sigmoid(opacity) < 1.0 is always true => drop all.
    monkeypatch.setattr(sys, "argv",
                        ["export", "--in", str(inp), "--out", str(out),
                         "--prune-opacity", "1.0"])
    with pytest.raises(SystemExit):
        export_mod.main()

    # the guard runs before any write: the sentinel asset is untouched, and no
    # empty metrics_export.json was written either.
    assert out.read_bytes() == sentinel
    assert not (tmp_path / "metrics_export.json").exists()


def test_export_decompose_range_violation_fails_without_clobber(tmp_path, monkeypatch):
    # MINOR-6: on the decompose path albedo is real reflectance validated to [0,1]. An
    # albedo > 1 must FAIL the FIELD_RANGES gate and exit nonzero BEFORE write_asset_ply
    # runs — so a prior good asset.ply (sentinel) is never clobbered and no metrics land.
    n = 8
    rng = np.random.default_rng(2)
    xyz = rng.normal(size=(n, 3)).astype(np.float32)
    sh0 = rng.normal(size=(n, 3)).astype(np.float32)
    opacity = np.zeros(n, np.float32)
    scales = np.log(np.full((n, 3), 0.1, np.float32))
    quats = np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1))
    normal = rng.normal(size=(n, 3)).astype(np.float32)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)           # unit (pass normal gate)
    albedo = np.full((n, 3), 1.5, np.float32)                         # > 1 -> range violation
    rough = np.full(n, 0.5, np.float32)
    dec = tmp_path / "decompose.ply"
    ply_io.write_decompose_ply(str(dec), xyz, sh0, opacity, scales, quats, albedo, normal, rough)

    out = tmp_path / "asset.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)

    monkeypatch.setattr(sys, "argv",
                        ["export", "--in", str(dec), "--out", str(out),
                         "--from-decompose", str(dec)])
    with pytest.raises(SystemExit):
        export_mod.main()

    assert out.read_bytes() == sentinel                              # not clobbered
    assert not (tmp_path / "metrics_export.json").exists()           # no metrics written


def test_shortest_axis_normals_known():
    # (quat wxyz, scales_log, expected unit normal)
    cases = [
        # identity rotation -> columns are world axes; pick the min-scale axis
        (np.array([1.0, 0, 0, 0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 1.0, 0.0])),  # axis 1
        (np.array([1.0, 0, 0, 0]), np.array([-2.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),  # axis 0
        # 90 deg about Z: R col2 = world Z; min scale on axis 2
        (np.array([_S, 0, 0, _S]), np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])),
        # 90 deg about X: R col1 = world +Z; min scale on axis 1
        (np.array([_S, _S, 0, 0]), np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    ]
    quats = np.stack([c[0] for c in cases]).astype(np.float32)
    scales = np.stack([c[1] for c in cases]).astype(np.float32)
    expected = np.stack([c[2] for c in cases]).astype(np.float32)

    normals = shortest_axis_normals(scales, quats)
    assert normals.shape == (4, 3)
    np.testing.assert_allclose(normals, expected, atol=1e-6)
    # always unit length
    np.testing.assert_allclose(np.linalg.norm(normals, axis=1), np.ones(4), atol=1e-6)
