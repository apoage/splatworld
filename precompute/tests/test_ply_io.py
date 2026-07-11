"""Golden tests for the PLY reader/writer (the schema contract).

Run before any change to the schema or ply_io:
    python -m pytest precompute/tests/test_ply_io.py -q
"""
import numpy as np
import pytest

from precompute.core import ply_io, schema


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


def _rotmat(qwxyz):
    w, x, y, z = qwxyz[:, 0], qwxyz[:, 1], qwxyz[:, 2], qwxyz[:, 3]
    R = np.empty((len(qwxyz), 3, 3), np.float32)
    R[:, 0, 0] = 1 - 2 * (y * y + z * z); R[:, 0, 1] = 2 * (x * y - w * z); R[:, 0, 2] = 2 * (x * z + w * y)
    R[:, 1, 0] = 2 * (x * y + w * z); R[:, 1, 1] = 1 - 2 * (x * x + z * z); R[:, 1, 2] = 2 * (y * z - w * x)
    R[:, 2, 0] = 2 * (x * z - w * y); R[:, 2, 1] = 2 * (y * z + w * x); R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R


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
    np.testing.assert_allclose(_rotmat(q_g), np.einsum("ij,njk->nik", M, _rotmat(q)), atol=1e-5)


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
