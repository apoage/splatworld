"""End-to-end tests for export's ground alignment (--sparse / --no-align).

Builds a tiny synthetic COLMAP model (camera ring with a known tilt) plus a tiny
train_base / decompose PLY in tmp_path and drives export.main():

  * --no-align (with --sparse) is BYTE-IDENTICAL to a plain no-sparse export
    (the alignment code path is fully bypassed);
  * an aligned export CHANGES the bytes and reports ring_normal_dot_up > 0.98 in
    metrics_export.json (the camera ring is horizontal in Godot by construction);
  * the aligned decompose path rotates the env-SH sidecar by the SAME composed
    conversion C = M @ R_align (not the M-only sign flip).
"""
import hashlib
import json
import sys

import numpy as np
import pytest

from precompute.core import ply_io, sh_env
from precompute.core.gaussmath import rotmat_to_quat
from precompute.stages import export as export_mod


# --- synthetic COLMAP model -------------------------------------------------
def _basis_perp(n):
    n = n / np.linalg.norm(n)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = np.cross(n, a); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    return e1, e2


def _cam_pose_looking_at(center, target, world_up):
    """world->cam (R, t) for a camera at `center` looking at `target`, right-side up
    w.r.t. world_up. COLMAP/OpenCV rows of R = [x_right, y_down, z_forward] in world;
    camera up-vector in world = -R[1] ~ world_up."""
    z = target - center; z /= np.linalg.norm(z)              # forward
    x = np.cross(z, world_up); x /= np.linalg.norm(x)        # right = fwd x up
    y = np.cross(z, x)                                       # down (~ -world_up)
    R = np.stack([x, y, z], axis=0)                          # rows = cam axes in world
    t = -R @ center                                          # center = -R^T t
    return R, t


def _fixed_pose(center, cam_up):
    """world->cam (R, t) whose camera up-vector in world is EXACTLY cam_up (down row
    y = -cam_up, a fixed forward perpendicular to it). Shared across the ring, so the
    MEAN camera up is exactly cam_up — used to decouple the two up cues cleanly."""
    y = -np.asarray(cam_up, float); y /= np.linalg.norm(y)   # camera down = -cam_up
    base = np.array([1.0, 0.0, 0.0]) if abs(y[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    z = base - np.dot(base, y) * y; z /= np.linalg.norm(z)   # forward, perp to y
    x = np.cross(y, z)                                       # right; rows [x,y,z], det +1
    R = np.stack([x, y, z], axis=0)
    t = -R @ center
    return R, t


def _write_colmap(dirpath, true_up, n=48, radius=5.0, cam_up=None):
    """Synthetic COLMAP ring. Centers lie on the plane perpendicular to `true_up`
    (so the plane-fit normal ~ true_up). With cam_up=None the cameras look at the
    origin (mean camera up ~ true_up: the two cues agree). Passing an explicit cam_up
    gives every camera a fixed orientation whose world up-vector is EXACTLY cam_up, so
    the mean-camera-up cue differs from the ring normal by angle(true_up, cam_up) —
    exercising the plane-normal-vs-camera-up disagreement."""
    dirpath.mkdir(parents=True, exist_ok=True)
    true_up = np.asarray(true_up, float); true_up /= np.linalg.norm(true_up)
    decouple = cam_up is not None
    if decouple:
        cam_up = np.asarray(cam_up, float) / np.linalg.norm(cam_up)
    e1, e2 = _basis_perp(true_up)
    ang = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    centers = radius * (np.cos(ang)[:, None] * e1 + np.sin(ang)[:, None] * e2)

    (dirpath / "cameras.txt").write_text(
        "# Camera list\n1 PINHOLE 100 100 50.0 50.0 50.0 50.0\n")

    lines = ["# Image list", "#   two lines per image"]
    for i, c in enumerate(centers, start=1):
        R, t = _fixed_pose(c, cam_up) if decouple else _cam_pose_looking_at(c, np.zeros(3), true_up)
        q = rotmat_to_quat(R)                                 # (w,x,y,z)
        lines.append(f"{i} {q[0]} {q[1]} {q[2]} {q[3]} {t[0]} {t[1]} {t[2]} 1 frame_{i:04d}.jpg")
        lines.append("0.0 0.0 -1")                            # dummy POINTS2D line
    (dirpath / "images.txt").write_text("\n".join(lines) + "\n")

    (dirpath / "points3D.txt").write_text(
        "# 3D points\n1 0.0 0.0 0.0 10 20 30 0.5 1 0 2 1\n")
    return dirpath


# --- tiny PLYs --------------------------------------------------------------
def _write_train_base(path, n=32, seed=0):
    rng = np.random.default_rng(seed)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    f_dc = rng.standard_normal((n, 3)).astype(np.float32) * 0.3
    shN = np.zeros((n, 0, 3), np.float32)
    opacity = np.zeros(n, np.float32)
    scales = np.log(np.full((n, 3), 0.1, np.float32))
    quats = np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1))
    ply_io.write_standard_3dgs_ply(str(path), xyz, f_dc, shN, opacity, scales, quats)


def _write_decompose(path, n=32, seed=1):
    rng = np.random.default_rng(seed)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    sh0 = rng.standard_normal((n, 3)).astype(np.float32) * 0.3
    opacity = np.zeros(n, np.float32)
    scales = np.log(np.full((n, 3), 0.1, np.float32))
    quats = np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1))
    normal = rng.standard_normal((n, 3)).astype(np.float32)
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    albedo = np.clip(rng.random((n, 3)).astype(np.float32), 0.0, 1.0)
    rough = np.full(n, 0.5, np.float32)
    ply_io.write_decompose_ply(str(path), xyz, sh0, opacity, scales, quats, albedo, normal, rough)


def _md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def _run_export(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["export", *argv])
    export_mod.main()


# --- tests ------------------------------------------------------------------
def test_no_align_byte_identical_to_no_sparse(tmp_path, monkeypatch):
    """--no-align (with --sparse) reproduces a plain no-sparse export byte-for-byte:
    the alignment path is fully bypassed (R_align=None => pure M conversion)."""
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.25, -0.9, -0.3])

    a_plain = tmp_path / "plain.ply"
    a_noalign = tmp_path / "noalign.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(a_plain)])
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(a_noalign),
                              "--sparse", str(sparse), "--no-align"])
    assert _md5(a_plain) == _md5(a_noalign), "--no-align not byte-identical to no-sparse export"


def test_aligned_export_changes_bytes_and_levels_ring(tmp_path, monkeypatch):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.25, -0.9, -0.3])

    a_plain = tmp_path / "plain.ply"
    a_aligned = tmp_path / "aligned.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(a_plain)])
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(a_aligned), "--sparse", str(sparse)])

    # alignment actually rotated the asset
    assert _md5(a_plain) != _md5(a_aligned)
    # and the camera-ring plane is horizontal in Godot
    metrics = json.loads((tmp_path / "metrics_export.json").read_text())
    al = metrics["alignment"]
    assert al["enabled"] is True
    assert al["method"] == "plane_fit"
    assert metrics["ring_normal_dot_up"] > 0.98
    # a clean ring (cam-up == ring normal) is NOT suspect, and metrics carry BOTH
    # candidate ups (plane normal + mean camera up).
    assert al["alignment_suspect"] is False
    assert al["up_camera_disagreement_deg"] < 5.0
    assert "up_colmap" in al and "mean_camera_up_colmap" in al


def test_no_align_reports_raw_tilt_below_threshold(tmp_path, monkeypatch):
    # With a strong tilt and alignment OFF, the exported ring is NOT horizontal —
    # ring_normal_dot_up reflects the raw tilt (the "before" A/B value).
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.6, -0.5, -0.62])

    out = tmp_path / "noalign.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out),
                              "--sparse", str(sparse), "--no-align"])
    metrics = json.loads((tmp_path / "metrics_export.json").read_text())
    assert metrics["alignment"]["enabled"] is False
    assert metrics["ring_normal_dot_up"] < 0.98        # tilt is visible, not corrected


def test_aligned_decompose_rotates_env_sh_by_full_conversion(tmp_path, monkeypatch):
    from precompute.core import colmap_io, orient
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.2, -0.92, -0.34])

    amb = (np.random.default_rng(5).standard_normal((sh_env.N_SH, 3)) * 0.5)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"ambient_sh": amb.tolist()}))

    out = tmp_path / "asset.ply"
    _run_export(monkeypatch, ["--from-decompose", str(dec), "--in", str(dec),
                              "--out", str(out), "--sparse", str(sparse),
                              "--env-sh", str(env_json)])

    sidecar = json.loads((tmp_path / "asset_env_sh.json").read_text())
    assert sidecar["aligned"] is True
    got = np.asarray(sidecar["ambient_sh"], np.float64)
    assert np.isfinite(got).all()

    # reproduce the expected rotation independently: C = M @ R_align built from the
    # SAME model, and confirm the sidecar used C (not the M-only sign flip).
    model = colmap_io.load_model(str(sparse))
    centers = np.array([im.center() for im in model.images])
    cam_ups = np.array([-colmap_io.qvec2rotmat(im.qvec)[1, :] for im in model.images])
    R_align = orient.align_up_rotation(orient.estimate_up_from_cameras(centers, cam_ups).up)
    C = ply_io.COLMAP_TO_GODOT.astype(np.float64) @ R_align
    expected = sh_env.rotate_env_sh(amb, C)
    np.testing.assert_allclose(got, expected, atol=1e-5)
    # a tilted asset: the full rotation differs from the M-only sign flip
    assert np.abs(got - sh_env.flip_env_sh_colmap_to_godot(amb)).max() > 1e-3


# --- FIX 4: --no-align / no-sparse decompose sidecar is byte-identical ----------
def test_no_align_decompose_sidecar_byte_identical(tmp_path, monkeypatch):
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.25, -0.9, -0.3])
    amb = (np.random.default_rng(9).standard_normal((sh_env.N_SH, 3)) * 0.4)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"ambient_sh": amb.tolist()}))

    out_plain = tmp_path / "plain.ply"
    out_noalign = tmp_path / "noalign.ply"
    _run_export(monkeypatch, ["--from-decompose", str(dec), "--in", str(dec),
                              "--out", str(out_plain), "--env-sh", str(env_json)])
    _run_export(monkeypatch, ["--from-decompose", str(dec), "--in", str(dec),
                              "--out", str(out_noalign), "--env-sh", str(env_json),
                              "--sparse", str(sparse), "--no-align"])

    side_plain = tmp_path / "plain_env_sh.json"
    side_noalign = tmp_path / "noalign_env_sh.json"
    # the `aligned` key is emitted for NEITHER (both are M-only) -> byte-identical.
    assert "aligned" not in json.loads(side_plain.read_text())
    assert "aligned" not in json.loads(side_noalign.read_text())
    assert _md5(side_plain) == _md5(side_noalign)


# --- FIX 5: aligned decompose export requires --env-sh --------------------------
def test_aligned_decompose_without_env_sh_fails_closed(tmp_path, monkeypatch):
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.25, -0.9, -0.3])
    out = tmp_path / "asset.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)
    monkeypatch.setattr(sys, "argv",
                        ["export", "--from-decompose", str(dec), "--in", str(dec),
                         "--out", str(out), "--sparse", str(sparse)])  # NO --env-sh
    with pytest.raises(SystemExit, match="env-sh"):
        export_mod.main()
    assert out.read_bytes() == sentinel                        # not clobbered
    # ...and --no-align (no geometry rotation) is allowed without --env-sh
    _run_export(monkeypatch, ["--from-decompose", str(dec), "--in", str(dec),
                              "--out", str(out), "--sparse", str(sparse), "--no-align"])
    assert out.read_bytes() != sentinel                        # wrote a real asset


# --- FIX 1: env sidecar validated BEFORE any write (no clobber, no bad ship) -----
@pytest.mark.parametrize("bad_amb, match", [
    ([[0.0] * 3] * 9, None),                                             # valid control
    ([[float("nan")] + [0.0, 0.0]] + [[0.0] * 3] * 8, "NaN/Inf"),        # non-finite
    ([[1e6, 0.0, 0.0]] + [[0.0] * 3] * 8, "magnitude"),                  # absurd magnitude
    ([[0.0, 0.0]] * 9, "shape"),                                         # wrong shape
])
def test_env_sh_validated_before_write(tmp_path, monkeypatch, bad_amb, match):
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"ambient_sh": bad_amb}))
    out = tmp_path / "asset.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)
    argv = ["export", "--from-decompose", str(dec), "--in", str(dec),
            "--out", str(out), "--env-sh", str(env_json)]
    monkeypatch.setattr(sys, "argv", argv)
    if match is None:
        export_mod.main()
        assert out.read_bytes() != sentinel                    # valid env -> asset written
    else:
        with pytest.raises(SystemExit, match=match):
            export_mod.main()
        assert out.read_bytes() == sentinel                    # bad env -> NOT clobbered
        assert not (tmp_path / "asset_env_sh.json").exists()   # no partial sidecar
        assert not (tmp_path / "metrics_export.json").exists() # no metrics either


def test_env_sh_missing_key_fails_closed(tmp_path, monkeypatch):
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"not_ambient_sh": 1}))
    out = tmp_path / "asset.ply"
    out.write_bytes(b"SENTINEL")
    monkeypatch.setattr(sys, "argv",
                        ["export", "--from-decompose", str(dec), "--in", str(dec),
                         "--out", str(out), "--env-sh", str(env_json)])
    with pytest.raises(SystemExit, match="missing 'ambient_sh'"):
        export_mod.main()
    assert out.read_bytes() == b"SENTINEL"


# --- FIX 3 + FIX D: ring metric goes THROUGH colmap_to_godot AND fail-closes ------
def test_ring_metric_gate_catches_transform_regression(tmp_path, monkeypatch):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.5, -0.6, -0.62])

    # Inject a bug into the single conversion: DROP R_align (as if colmap_to_godot
    # forgot to apply the alignment). ring_normal_dot_up is computed via the SAME
    # function, so on the ALIGNED path it registers the un-levelled ring and the FIX D
    # gate must fail closed (SystemExit) WITHOUT clobbering a prior asset.
    orig = ply_io.colmap_to_godot
    def buggy(xyz, normal, rot, R_align=None):
        return orig(xyz, normal, rot, R_align=None)             # BUG: ignores R_align
    monkeypatch.setattr(export_mod.ply_io, "colmap_to_godot", buggy)

    out = tmp_path / "aligned.ply"
    sentinel = b"SENTINEL"
    out.write_bytes(sentinel)
    monkeypatch.setattr(sys, "argv",
                        ["export", "--in", str(tb), "--out", str(out), "--sparse", str(sparse)])
    with pytest.raises(SystemExit, match="not levelled"):
        export_mod.main()
    assert out.read_bytes() == sentinel                         # gate is clobber-safe
    assert not (tmp_path / "metrics_export.json").exists()

    # The --no-align path is deliberately UNGATED: same bug (irrelevant, R_align=None
    # there anyway), it exits 0 and reports the raw pre-alignment tilt (< 0.98) for A/B.
    out2 = tmp_path / "noalign.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out2),
                              "--sparse", str(sparse), "--no-align"])
    metrics = json.loads((tmp_path / "metrics_export.json").read_text())
    assert metrics["alignment"]["enabled"] is False
    assert metrics["ring_normal_dot_up"] < 0.98                 # raw tilt, legitimately low


# --- FIX A: neutral re-export to the same --out drops a stale aligned sidecar -----
def test_neutral_export_removes_stale_sidecar(tmp_path, monkeypatch):
    dec = tmp_path / "decompose.ply"
    _write_decompose(dec)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.2, -0.92, -0.34])
    amb = (np.random.default_rng(6).standard_normal((sh_env.N_SH, 3)) * 0.4)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"ambient_sh": amb.tolist()}))

    out = tmp_path / "asset.ply"
    sidecar = tmp_path / "asset_env_sh.json"
    # 1) aligned decompose export writes asset.ply + an aligned sidecar
    _run_export(monkeypatch, ["--from-decompose", str(dec), "--in", str(dec), "--out", str(out),
                              "--sparse", str(sparse), "--env-sh", str(env_json)])
    assert sidecar.exists()
    assert json.loads(sidecar.read_text()).get("aligned") is True

    # 2) a later NEUTRAL export to the SAME --out (writes NO sidecar) must DELETE the
    #    stale aligned sidecar, so the reader can never light the new asset old-frame.
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out)])   # neutral
    assert out.exists()                                              # new asset written
    assert not sidecar.exists()                                      # stale sidecar gone


# --- FIX B: --env-sh on a neutral export warns and is dropped --------------------
def test_env_sh_ignored_in_neutral_mode_warns(tmp_path, monkeypatch, capsys):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    amb = (np.random.default_rng(8).standard_normal((sh_env.N_SH, 3)) * 0.3)
    env_json = tmp_path / "env_sh.json"
    env_json.write_text(json.dumps({"ambient_sh": amb.tolist()}))
    out = tmp_path / "asset.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out), "--env-sh", str(env_json)])
    assert "env-sh ignored" in capsys.readouterr().err              # loud stderr warning
    assert not (tmp_path / "asset_env_sh.json").exists()            # no sidecar written


# --- FIX 2: suspect disagreement is observable + gated by --strict-align ---------
def test_alignment_suspect_on_disagreement(tmp_path, monkeypatch):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    # ring plane normal ~ true_up, cameras rolled ~40deg away -> the two up cues split.
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.0, -1.0, 0.0],
                           cam_up=[0.0, -np.cos(np.radians(40)), np.sin(np.radians(40))])
    out = tmp_path / "asset.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out), "--sparse", str(sparse)])
    al = json.loads((tmp_path / "metrics_export.json").read_text())["alignment"]
    assert al["alignment_suspect"] is True
    assert al["up_camera_disagreement_deg"] > 25.0
    # aligned anyway (default is NOT to hard-fail); ring still levels by construction.
    assert al["ring_normal_dot_up"] > 0.98


def test_strict_align_rejects_suspect(tmp_path, monkeypatch):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.0, -1.0, 0.0],
                           cam_up=[0.0, -np.cos(np.radians(40)), np.sin(np.radians(40))])
    out = tmp_path / "asset.ply"
    sentinel = b"SENTINEL"
    out.write_bytes(sentinel)
    monkeypatch.setattr(sys, "argv",
                        ["export", "--in", str(tb), "--out", str(out),
                         "--sparse", str(sparse), "--strict-align"])
    with pytest.raises(SystemExit, match="SUSPECT"):
        export_mod.main()
    assert out.read_bytes() == sentinel                        # nothing written on rejection


def test_strict_align_passes_clean_ring(tmp_path, monkeypatch):
    tb = tmp_path / "train_base.ply"
    _write_train_base(tb)
    sparse = _write_colmap(tmp_path / "sparse", true_up=[0.1, -0.98, -0.05])  # clean, not suspect
    out = tmp_path / "asset.ply"
    _run_export(monkeypatch, ["--in", str(tb), "--out", str(out),
                              "--sparse", str(sparse), "--strict-align"])
    al = json.loads((tmp_path / "metrics_export.json").read_text())["alignment"]
    assert al["alignment_suspect"] is False
    assert al["ring_normal_dot_up"] > 0.98
