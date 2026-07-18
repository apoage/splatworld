"""Golden tests for tools/clean_relight.py — the splat cleanup / variant decimator.

Reuses the ~50-Gaussian synthetic AssetGaussians fixture pattern from test_ply_io.py.
Asserts: identity when unconfigured (arrays byte-equal), each filter in isolation,
combined AND, the fail-closed range/NaN gate (no write on violation), and metrics.
"""
import json
import sys

import numpy as np
import pytest

from precompute.core import ply_io, schema
from precompute.tools import clean_relight as clean


def _synthetic(n=50, n_basis=0, seed=0):
    """Valid extended asset (mirrors test_ply_io._synthetic)."""
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


def _write(tmp_path, g, name="in.relightply"):
    p = tmp_path / name
    ply_io.write_asset_ply(str(p), g)
    return p


def _run(tmp_path, inp, monkeypatch, *extra, out_name="out.relightply"):
    out = tmp_path / out_name
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out), *extra])
    clean.main()
    return out


# --- identity when unconfigured ----------------------------------------------
@pytest.mark.parametrize("n_basis", [0, 2])
def test_no_filters_is_identity(tmp_path, monkeypatch, n_basis):
    g = _synthetic(n_basis=n_basis)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch)
    r = ply_io.read_asset_ply(str(out))
    assert r.count == g.count
    for f in ("xyz", "scale", "rot", "opacity", "albedo", "normal", "rough", "trans"):
        np.testing.assert_array_equal(getattr(r, f), getattr(g, f), err_msg=f)
    np.testing.assert_array_equal(r.label, g.label)
    if n_basis:
        np.testing.assert_array_equal(r.basis, g.basis)


# --- each filter in isolation -------------------------------------------------
def test_crop_drops_outside_box(tmp_path, monkeypatch):
    # 5 splats: 2 inside a small box, 3 well outside it.
    g = _synthetic(n=5)
    g.xyz[:] = np.array([[0.0, 0.0, 0.0], [0.1, 0.1, 0.1],   # inside
                         [10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],  # outside
                        np.float32)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--crop-min=-1,-1,-1", "--crop-max=1,1,1")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 2


def test_crop_subset_of_axes(tmp_path, monkeypatch):
    # Only bound y from below: keep y >= 0. 3 above, 2 below.
    g = _synthetic(n=5)
    g.xyz[:, 1] = np.array([1.0, 2.0, 3.0, -1.0, -2.0], np.float32)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--crop-min", ",0,")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 3


def test_exclude_drops_inside_box(tmp_path, monkeypatch):
    g = _synthetic(n=5)
    g.xyz[:] = np.array([[0.0, 0.0, 0.0], [0.1, 0.1, 0.1],   # inside exclude -> dropped
                         [10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],  # kept
                        np.float32)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--exclude-min=-1,-1,-1", "--exclude-max=1,1,1")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 3


def test_drop_labels(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    g.label[:] = np.array([0, 0, 1, 2, 3, 0], np.uint8)   # three label-0 splats
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--drop-labels", "0")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 3
    assert (r.label != 0).all()


def test_keep_labels(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    g.label[:] = np.array([0, 0, 1, 2, 3, 0], np.uint8)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--keep-labels", "1,2")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 2
    assert set(np.unique(r.label)) == {1, 2}


def test_prune_opacity(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    # sigmoid(logit) -> 4 dense at 0.6, 2 near-transparent at 0.001.
    g.opacity[:] = np.log(np.array([0.6, 0.6, 0.6, 0.6, 0.001, 0.001]) /
                          (1.0 - np.array([0.6, 0.6, 0.6, 0.6, 0.001, 0.001]))).astype(np.float32)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--prune-opacity", "0.02")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 4


def test_keep_index_json(tmp_path, monkeypatch):
    g = _synthetic(n=10)
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps([2, 5]))
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--keep-index", str(sel))
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 2
    np.testing.assert_array_equal(r.xyz, g.xyz[[2, 5]])


def test_keep_index_newline(tmp_path, monkeypatch):
    g = _synthetic(n=10)
    sel = tmp_path / "sel.txt"
    sel.write_text("1\n3\n7\n")
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--keep-index", str(sel))
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 3
    np.testing.assert_array_equal(r.xyz, g.xyz[[1, 3, 7]])


def test_keep_index_out_of_range_fails(tmp_path, monkeypatch):
    g = _synthetic(n=5)
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps([0, 99]))          # 99 >= 5
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out),
                         "--keep-index", str(sel)])
    with pytest.raises(SystemExit):
        clean.main()
    assert not out.exists()


# --- fail-closed arg validation ----------------------------------------------
@pytest.mark.parametrize("flag,val", [("--drop-labels", "9"),
                                      ("--keep-labels", "256")])
def test_invalid_label_arg_fails_closed(tmp_path, monkeypatch, flag, val):
    # An out-of-schema label id must SystemExit BEFORE the uint8 cast (which would
    # OverflowError on numpy>=2 or silently wrap on numpy<1.24) and write nothing.
    g = _synthetic(n=6)
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out), flag, val])
    with pytest.raises(SystemExit):
        clean.main()
    assert not out.exists()


def test_keep_index_non_integral_json_fails(tmp_path, monkeypatch):
    # A float index must fail closed, not silently truncate to the WRONG splat.
    g = _synthetic(n=10)
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps([2.9, 5]))
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out),
                         "--keep-index", str(sel)])
    with pytest.raises(SystemExit):
        clean.main()
    assert not out.exists()


# --- combined AND -------------------------------------------------------------
def test_combined_filters_and(tmp_path, monkeypatch):
    # keep-index selects 4; crop then keeps only the subset inside the box.
    g = _synthetic(n=8)
    g.xyz[:] = 0.0
    g.xyz[3] = np.array([10.0, 0.0, 0.0], np.float32)   # index 3 outside crop
    g.label[:] = 1
    g.label[6] = 0                                      # index 6 dropped by label
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps([2, 3, 5, 6]))            # keep-index picks 4
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch,
               "--keep-index", str(sel),
               "--crop-min=-1,-1,-1", "--crop-max=1,1,1",
               "--drop-labels", "0")
    r = ply_io.read_asset_ply(str(out))
    # of {2,3,5,6}: drop 3 (crop) and 6 (label) -> {2,5}
    assert r.count == 2


# --- fail-closed range/NaN gate ----------------------------------------------
def test_range_gate_fails_and_does_not_write(tmp_path, monkeypatch):
    g = _synthetic(n=8)
    g.rough[2] = 2.0                                    # out of [0,1]
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out)])
    with pytest.raises(SystemExit):
        clean.main()
    assert out.read_bytes() == sentinel                 # not clobbered
    assert not (tmp_path / "metrics_clean.json").exists()


def test_nan_gate_fails(tmp_path, monkeypatch):
    g = _synthetic(n=8)
    g.albedo[1, 0] = np.nan
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out)])
    with pytest.raises(SystemExit):
        clean.main()
    assert not out.exists()


def test_empty_result_fails_without_allow_empty(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    g.label[:] = 2
    inp = _write(tmp_path, g)
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out),
                         "--keep-labels", "0"])          # nothing has label 0
    with pytest.raises(SystemExit):
        clean.main()
    assert not out.exists()


def test_empty_result_allowed_with_flag(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    g.label[:] = 2
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--keep-labels", "0", "--allow-empty")
    r = ply_io.read_asset_ply(str(out))
    assert r.count == 0


# --- metrics ------------------------------------------------------------------
def test_metrics_keys_and_counts(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    g.label[:] = np.array([0, 0, 1, 2, 3, 0], np.uint8)
    inp = _write(tmp_path, g)
    out = _run(tmp_path, inp, monkeypatch, "--drop-labels", "0")
    m = json.loads((tmp_path / "metrics_clean.json").read_text())
    assert m["stage"] == "clean_relight"
    assert m["schema_version"] == schema.SCHEMA_VERSION
    assert m["n_before"] == 6
    assert m["n_after"] == 3
    assert m["n_pruned"] == 3
    assert m["n_dropped_by_label"] == 3
    assert m["n_dropped_by_crop"] == 0
    assert "prune" in m and m["prune"]["n_before"] == 6
    assert m["params"]["drop_labels"] == [0]


def test_metrics_custom_path(tmp_path, monkeypatch):
    g = _synthetic(n=6)
    inp = _write(tmp_path, g)
    mpath = tmp_path / "custom_metrics.json"
    out = tmp_path / "out.relightply"
    monkeypatch.setattr(sys, "argv",
                        ["clean_relight", "--in", str(inp), "--out", str(out),
                         "--metrics", str(mpath)])
    clean.main()
    assert mpath.exists()
    assert not (tmp_path / "metrics_clean.json").exists()
