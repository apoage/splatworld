"""Deliverable C gate — the `.vply` -> standard-3DGS downgrade tool round-trip
(2026-07-23-vply-cleanup-roundtrip).

relight_to_vanilla is the inverse of vanilla_to_relight. Round-tripping a vanilla ply
through both must preserve geometry (xyz/opacity/scales/quats) and the SH degree-0 DC color
(albedo IS the SH-DC, so sh0 -> albedo -> sh0 is identity). Coordinate handling is EXPLICIT:
`--coord none` must NOT touch the frame; `--coord colmap` applies the diag(1,-1,-1) flip.
"""
import sys

import numpy as np
import pytest

from precompute.core import ply_io
from precompute.tools import vanilla_to_relight as V2R
from precompute.tools import relight_to_vanilla as R2V


def _write_vanilla(path, n=12, seed=3):
    """A tiny SH-degree-0 vanilla 3DGS ply whose albedo (sh0_to_rgb of f_dc) is strictly
    positive, so vanilla_to_relight's lower-clamp is a no-op and the round-trip is exact."""
    rng = np.random.default_rng(seed)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    # f_dc chosen so albedo = 0.5 + C0*f_dc lands in ~[0.2, 0.9] (all > 0, no clip loss)
    f_dc = rng.uniform(-1.0, 1.4, (n, 3)).astype(np.float32)
    shN = np.zeros((n, 0, 3), np.float32)
    opacity = rng.standard_normal(n).astype(np.float32)
    scales = rng.standard_normal((n, 3)).astype(np.float32)
    quats = rng.standard_normal((n, 4)).astype(np.float32)
    quats /= np.linalg.norm(quats, axis=1, keepdims=True)
    ply_io.write_standard_3dgs_ply(str(path), xyz, f_dc, shN, opacity, scales, quats)
    return dict(xyz=xyz, f_dc=f_dc, opacity=opacity, scales=scales, quats=quats)


def _run(mod, argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", argv)
    mod.main()


def test_roundtrip_preserves_geometry_and_sh0_coord_none(tmp_path, monkeypatch):
    """vanilla -> .vply -> vanilla with --coord none on BOTH legs: geometry within f32
    tolerance and sh0 (f_dc) preserved. Would FAIL if albedo<->sh0 were dropped (f_dc wrong)
    or if a coordinate flip were applied when --coord none (y/z would be negated)."""
    src = _write_vanilla(tmp_path / "in.ply")

    vply = tmp_path / "mid.vply"
    _run(V2R, ["vanilla_to_relight", "--in", str(tmp_path / "in.ply"), "--out", str(vply),
               "--coord", "none", "--normal-orient", "raw"], monkeypatch)

    back = tmp_path / "back.ply"
    _run(R2V, ["relight_to_vanilla", "--in", str(vply), "--out", str(back),
               "--coord", "none"], monkeypatch)

    out = ply_io.read_standard_3dgs_ply(str(back))
    np.testing.assert_allclose(out["xyz"], src["xyz"], atol=1e-6)          # frame untouched
    np.testing.assert_allclose(out["opacity"], src["opacity"], atol=1e-6)
    np.testing.assert_allclose(out["scale"], src["scales"], atol=1e-6)
    np.testing.assert_allclose(out["rot"], src["quats"], atol=1e-6)
    # sh0 round-trips: f_dc -> albedo=sh0_to_rgb -> sh0=rgb2sh -> f_dc (exact, no clip)
    np.testing.assert_allclose(out["f_dc"], src["f_dc"], atol=1e-5)
    # downgraded asset is flat SH degree-0 (higher SH zeroed / absent)
    assert out["f_rest"].shape[1] == 0


def test_coord_colmap_applies_flip_none_does_not(tmp_path, monkeypatch):
    """The diag(1,-1,-1) flip is applied ONLY when asked. --coord colmap negates y and z
    (COLMAP<->Godot involution); --coord none leaves them. A regression that flipped on
    `none` (or never flipped on `colmap`) is caught here."""
    _write_vanilla(tmp_path / "in.ply")
    vply = tmp_path / "mid.vply"
    _run(V2R, ["vanilla_to_relight", "--in", str(tmp_path / "in.ply"), "--out", str(vply),
               "--coord", "none", "--normal-orient", "raw"], monkeypatch)
    asset = ply_io.read_asset_ply(str(vply))

    none_out = tmp_path / "none.ply"
    _run(R2V, ["relight_to_vanilla", "--in", str(vply), "--out", str(none_out),
               "--coord", "none"], monkeypatch)
    colmap_out = tmp_path / "colmap.ply"
    _run(R2V, ["relight_to_vanilla", "--in", str(vply), "--out", str(colmap_out),
               "--coord", "colmap"], monkeypatch)

    none_xyz = ply_io.read_standard_3dgs_ply(str(none_out))["xyz"]
    colmap_xyz = ply_io.read_standard_3dgs_ply(str(colmap_out))["xyz"]

    # none: identical to the asset frame
    np.testing.assert_allclose(none_xyz, asset.xyz, atol=1e-6)
    # colmap: x preserved, y & z negated (diag(1,-1,-1))
    np.testing.assert_allclose(colmap_xyz[:, 0], asset.xyz[:, 0], atol=1e-6)
    np.testing.assert_allclose(colmap_xyz[:, 1], -asset.xyz[:, 1], atol=1e-6)
    np.testing.assert_allclose(colmap_xyz[:, 2], -asset.xyz[:, 2], atol=1e-6)
    # sanity: the two coord modes actually differ (flip is not a silent no-op)
    assert not np.allclose(colmap_xyz, none_xyz)
