"""Golden tests for the PLY reader/writer (the schema contract).

Run before any change to the schema or ply_io:
    python -m pytest precompute/tests/test_ply_io.py -q
"""
import numpy as np
import pytest

from precompute.core import ply_io, schema, gaussmath


def _synthetic(n=50, n_basis=0, seed=0):
    rng = np.random.default_rng(seed)
    rot = rng.standard_normal((n, 4)).astype(np.float32)
    rot /= np.linalg.norm(rot, axis=1, keepdims=True)
    normal = rng.standard_normal((n, 3)).astype(np.float32)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    basis = rng.random((n, n_basis, 3), dtype=np.float32) if n_basis else None
    return ply_io.AssetGaussians(
        xyz=rng.standard_normal((n, 3)).astype(np.float32),
        scale=rng.standard_normal((n, 3)).astype(np.float32),
        rot=rot,
        opacity=rng.standard_normal(n).astype(np.float32),
        albedo=rng.random((n, 3), dtype=np.float32),
        normal=normal,
        rough=rng.random(n, dtype=np.float32),
        trans=rng.random(n, dtype=np.float32),
        label=rng.integers(0, 4, n, dtype=np.uint8),
        basis=basis,
    )


@pytest.mark.parametrize("n_basis", [0, 2])
def test_asset_roundtrip(tmp_path, n_basis):
    g = _synthetic(n_basis=n_basis)
    p = tmp_path / "asset.ply"
    ply_io.write_asset_ply(str(p), g)
    r = ply_io.read_asset_ply(str(p))

    assert r.count == g.count
    assert r.n_basis == n_basis
    # f32 round-trip must be bit-exact
    for f in ("xyz", "scale", "rot", "opacity", "albedo", "normal", "rough", "trans"):
        np.testing.assert_array_equal(getattr(r, f), getattr(g, f), err_msg=f)
    np.testing.assert_array_equal(r.label, g.label)
    if n_basis:
        np.testing.assert_array_equal(r.basis, g.basis)


def test_header_has_schema_version(tmp_path):
    g = _synthetic()
    p = tmp_path / "asset.ply"
    ply_io.write_asset_ply(str(p), g)
    with open(p, "rb") as f:
        head = f.read(200)
    assert schema.HEADER_COMMENT.encode() in head
    assert b"format binary_little_endian 1.0" in head


def test_coordinate_conversion_transforms_orientation_by_M():
    """A 3DGS covariance transforms as Sigma' = M Sigma M^T, so the Gaussian's
    orientation matrix must map R -> M @ R (== q' = q_M (x) q). Also positions and
    normals map by M. Validates colmap_to_godot end to end."""
    rng = np.random.default_rng(1)
    n = 32
    q = rng.standard_normal((n, 4)).astype(np.float32)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    nrm = rng.standard_normal((n, 3)).astype(np.float32)

    xyz_g, nrm_g, q_g = ply_io.colmap_to_godot(xyz, nrm, q)
    M = ply_io.COLMAP_TO_GODOT
    np.testing.assert_allclose(xyz_g, xyz @ M.T, atol=1e-6)
    np.testing.assert_allclose(nrm_g, nrm @ M.T, atol=1e-6)
    # shared gaussmath.quat_to_rotmat (was a local copy) — dedup guard for item 8
    np.testing.assert_allclose(gaussmath.quat_to_rotmat(q_g),
                               np.einsum("ij,njk->nik", M, gaussmath.quat_to_rotmat(q)),
                               atol=1e-5)


def test_standard_3dgs_read(tmp_path):
    """Read a minimal hand-built vanilla 3DGS PLY (x/y/z, f_dc, opacity, scale, rot)."""
    n = 10
    props = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
             "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    dt = np.dtype([(p, "<f4") for p in props])
    arr = np.zeros(n, dt)
    rng = np.random.default_rng(2)
    for p in props:
        arr[p] = rng.standard_normal(n).astype(np.float32)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {p}" for p in props] + ["end_header\n"]
    path = tmp_path / "std.ply"
    with open(path, "wb") as f:
        f.write("\n".join(header).encode())
        f.write(arr.tobytes())

    out = ply_io.read_standard_3dgs_ply(str(path))
    assert out["xyz"].shape == (n, 3)
    assert out["f_dc"].shape == (n, 3)
    assert out["f_rest"].shape == (n, 0)
    np.testing.assert_array_equal(out["xyz"][:, 0], arr["x"])


# --- item 2: read_asset_ply must validate the schema-version header comment ----
def test_read_asset_rejects_missing_schema_comment(tmp_path):
    g = _synthetic()
    p = tmp_path / "asset.ply"
    ply_io.write_asset_ply(str(p), g)
    raw = p.read_bytes()
    stripped = raw.replace(("comment " + schema.HEADER_COMMENT + "\n").encode(), b"", 1)
    assert stripped != raw, "test setup: comment line not found to strip"
    q = tmp_path / "no_comment.ply"
    q.write_bytes(stripped)
    with pytest.raises(ValueError, match="splat_relight_schema"):
        ply_io.read_asset_ply(str(q))


def test_read_asset_rejects_wrong_schema_version(tmp_path):
    g = _synthetic()
    p = tmp_path / "asset.ply"
    ply_io.write_asset_ply(str(p), g)
    raw = p.read_bytes()
    # same byte length keeps the data offset intact — flip only the version digit
    bad = raw.replace(b"splat_relight_schema 1", b"splat_relight_schema 2", 1)
    assert bad != raw, "test setup: schema comment not found"
    q = tmp_path / "wrong_version.ply"
    q.write_bytes(bad)
    with pytest.raises(ValueError, match="version mismatch"):
        ply_io.read_asset_ply(str(q))


# --- item 6: missing-field ValueError must be reachable (before column access) -
def test_read_standard_missing_field_raises_valueerror(tmp_path):
    # omit rot_3 (and it is accessed via need(...) — the old code KeyError'd first)
    props = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
             "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2"]  # no rot_3
    n = 4
    dt = np.dtype([(p, "<f4") for p in props])
    arr = np.zeros(n, dt)
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {p}" for p in props] + ["end_header\n"]
    path = tmp_path / "missing.ply"
    with open(path, "wb") as f:
        f.write("\n".join(header).encode())
        f.write(arr.tobytes())
    with pytest.raises(ValueError, match="missing"):
        ply_io.read_standard_3dgs_ply(str(path))


# --- item 11: write_standard -> read_standard round trip incl f_rest ordering --
def test_standard_3dgs_roundtrip_channel_major_frest(tmp_path):
    n, krest = 5, 3          # SH degree 1 -> 3 rest coeffs per channel
    rng = np.random.default_rng(7)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    sh0 = rng.standard_normal((n, 3)).astype(np.float32)
    # distinct, structured values so a point-vs-channel-major mixup is detectable
    shN = np.empty((n, krest, 3), np.float32)
    for i in range(n):
        for k in range(krest):
            for c in range(3):
                shN[i, k, c] = 100 * c + 10 * k + i
    opacity = rng.standard_normal(n).astype(np.float32)
    scales = rng.standard_normal((n, 3)).astype(np.float32)
    quats = rng.standard_normal((n, 4)).astype(np.float32)
    quats /= np.linalg.norm(quats, axis=1, keepdims=True)

    p = tmp_path / "std_rt.ply"
    ply_io.write_standard_3dgs_ply(str(p), xyz, sh0, shN, opacity, scales, quats)
    out = ply_io.read_standard_3dgs_ply(str(p))

    np.testing.assert_array_equal(out["xyz"], xyz)
    np.testing.assert_array_equal(out["f_dc"], sh0)
    np.testing.assert_array_equal(out["opacity"], opacity)
    np.testing.assert_array_equal(out["scale"], scales)
    # writer re-normalizes quats (already unit here) -> f32 rounding, not exact
    np.testing.assert_allclose(out["rot"], quats, atol=1e-6)
    assert out["f_rest"].shape == (n, 3 * krest)
    # hand-computed channel-major layout: index = c*krest + k holds shN[:,k,c]
    for c in range(3):
        for k in range(krest):
            np.testing.assert_array_equal(out["f_rest"][:, c * krest + k], shN[:, k, c])
