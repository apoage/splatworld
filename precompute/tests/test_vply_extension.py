"""Deliverable A gates — the `.vply` extension unify (2026-07-23-vply-cleanup-roundtrip).

`.vply` is a FILENAME/ROUTING marker for our non-vanilla extended splat, NOT a schema
change: the on-disk bytes + the `splat_relight_schema` header comment must be byte-identical
regardless of the file's extension. These gates pin that (bytes unchanged by extension) and
assert the Godot rename is COMPLETE (zero remaining `.relightply` references under
godot/relight/ — a partial rename would leave the viewer loading a path that no longer exists).
"""
import os

import numpy as np

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


def test_asset_ext_constant():
    """schema.ASSET_EXT is the single source of truth for the extended-file extension."""
    assert schema.ASSET_EXT == "vply"


def test_extension_does_not_change_bytes(tmp_path):
    """Writing the SAME asset to a *.vply path and a *.ply path yields byte-identical
    files, and read_asset_ply round-trips from the *.vply path. This is the load-bearing
    invariant of deliverable A: `.vply` is routing-only — it must NOT alter the header
    (the schema comment stays byte-identical) or the payload. Would fail if write_asset_ply
    ever keyed any byte on the filename extension."""
    g = _synthetic()
    p_vply = tmp_path / "asset.vply"
    p_ply = tmp_path / "asset.ply"
    ply_io.write_asset_ply(str(p_vply), g)
    ply_io.write_asset_ply(str(p_ply), g)

    assert p_vply.read_bytes() == p_ply.read_bytes()
    # header still carries the UNCHANGED schema marker (no SCHEMA_VERSION bump).
    assert schema.HEADER_COMMENT.encode() in p_vply.read_bytes()[:200]

    r = ply_io.read_asset_ply(str(p_vply))
    assert r.count == g.count
    for f in ("xyz", "scale", "rot", "opacity", "albedo", "normal", "rough", "trans"):
        np.testing.assert_array_equal(getattr(r, f), getattr(g, f), err_msg=f)
    np.testing.assert_array_equal(r.label, g.label)


def test_no_relightply_references_under_godot_relight():
    """The Godot rename must be COMPLETE: zero dotted `.relightply` references remain under
    godot/relight/ (loader, controller ASSET_PATH, env-SH sidecar derivation, carpet/studio
    tools, render/smoke fixtures incl. their user:// temp paths). A partial rename would
    leave the viewer pointing at a path the mirror no longer produces. Would have failed on
    the pre-rename tree (43 references)."""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    root = os.path.join(repo, "godot", "relight")
    assert os.path.isdir(root), f"godot/relight not found at {root}"
    offenders = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            fp = os.path.join(dirpath, name)
            try:
                text = open(fp, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if ".relightply" in text:
                for i, line in enumerate(text.splitlines(), 1):
                    if ".relightply" in line:
                        offenders.append(f"{os.path.relpath(fp, repo)}:{i}")
    assert not offenders, "remaining .relightply references:\n" + "\n".join(offenders)
