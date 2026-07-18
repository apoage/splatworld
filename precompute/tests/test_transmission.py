"""Tests for the transmission stage: constant per-label `trans` assignment (M3).

Builds a tiny extended asset with mixed labels via ply_io, runs the stage, and asserts
leaf/grass got the requested transmission, bark/ground stayed 0, the range is [0,1], and
no NaN. Mirrors the style of test_export.py (synthetic asset + monkeypatch argv + main()).
"""
import json
import sys

import numpy as np
import pytest

from precompute.core import ply_io, schema
from precompute.stages import transmission as trans_mod

# ground(0) x2, grass(1) x3, leaf(2) x4, bark(3) x2
_LABELS = [0, 0, 1, 1, 1, 2, 2, 2, 2, 3, 3]


def _make_asset(path, labels):
    n = len(labels)
    rng = np.random.default_rng(0)
    g = ply_io.AssetGaussians(
        xyz=rng.normal(size=(n, 3)).astype(np.float32),
        scale=np.log(np.full((n, 3), 0.1, np.float32)),
        rot=np.tile(np.array([1.0, 0, 0, 0], np.float32), (n, 1)),
        opacity=np.zeros(n, np.float32),
        albedo=np.full((n, 3), 0.5, np.float32),
        normal=np.tile(np.array([0.0, 1.0, 0.0], np.float32), (n, 1)),
        rough=np.full(n, 0.6, np.float32),
        trans=np.zeros(n, np.float32),                    # placeholder (pre-stage)
        label=np.asarray(labels, np.uint8),
    )
    ply_io.write_asset_ply(str(path), g)


def _run(monkeypatch, inp, out, extra=None):
    argv = ["transmission", "--in", str(inp), "--out", str(out)]
    if extra:
        argv += extra
    monkeypatch.setattr(sys, "argv", argv)
    trans_mod.main()


def test_default_assigns_leaf_grass_keeps_opaque_zero(tmp_path, monkeypatch):
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    out = tmp_path / "asset_out.ply"
    _run(monkeypatch, inp, out)                            # defaults: leaf/grass 0.5

    a = ply_io.read_asset_ply(str(out))
    label = np.asarray(_LABELS, np.uint8)
    leaf, grass = schema.LABEL_IDS["leaf"], schema.LABEL_IDS["grass"]
    ground, bark = schema.LABEL_IDS["ground"], schema.LABEL_IDS["bark"]

    np.testing.assert_allclose(a.trans[label == leaf], 0.5)
    np.testing.assert_allclose(a.trans[label == grass], 0.5)
    assert np.all(a.trans[label == ground] == 0.0)        # opaque stays 0
    assert np.all(a.trans[label == bark] == 0.0)
    assert float(a.trans.min()) >= 0.0 and float(a.trans.max()) <= 1.0
    assert not np.isnan(a.trans).any() and not np.isinf(a.trans).any()

    m = json.loads((tmp_path / "metrics_transmission.json").read_text())
    assert m["per_label"]["leaf"]["count"] == 4
    assert m["per_label"]["grass"]["count"] == 3
    assert m["per_label"]["bark"]["trans_max"] == 0.0
    assert m["per_label"]["ground"]["trans_max"] == 0.0
    assert m["trans_range"] == [0.0, 0.5]


def test_custom_per_label_constants(tmp_path, monkeypatch):
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    out = tmp_path / "asset_out.ply"
    _run(monkeypatch, inp, out, ["--trans-leaf", "0.3", "--trans-grass", "0.7"])

    a = ply_io.read_asset_ply(str(out))
    label = np.asarray(_LABELS, np.uint8)
    np.testing.assert_allclose(a.trans[label == schema.LABEL_IDS["leaf"]], 0.3)
    np.testing.assert_allclose(a.trans[label == schema.LABEL_IDS["grass"]], 0.7)
    assert np.all(a.trans[label == schema.LABEL_IDS["bark"]] == 0.0)


def test_in_place_rewrite(tmp_path, monkeypatch):
    # --out omitted => rewrite --in in place.
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    monkeypatch.setattr(sys, "argv", ["transmission", "--in", str(inp), "--trans-leaf", "0.4"])
    trans_mod.main()
    a = ply_io.read_asset_ply(str(inp))
    np.testing.assert_allclose(a.trans[np.asarray(_LABELS, np.uint8) == schema.LABEL_IDS["leaf"]], 0.4)


def test_landed_assignment_gate_fires_on_broken_mask(tmp_path, monkeypatch):
    # The POSITIVE gate: if the mask logic assigned the WRONG (or no) gaussians, the
    # requested foliage trans never lands, and the stage MUST fail-closed BEFORE writing.
    # Simulate a broken assignment by stubbing assign_trans to leave everything 0 (an
    # empty/wrong mask). If the landed-assignment gate were removed, main() would write a
    # bad asset and NOT raise -> this test (asserting SystemExit + no clobber) would fail.
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    out = tmp_path / "asset_out.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)

    monkeypatch.setattr(trans_mod, "assign_trans",
                        lambda label, tbl: np.zeros(len(label), np.float32))
    monkeypatch.setattr(sys, "argv",
                        ["transmission", "--in", str(inp), "--out", str(out)])  # leaf/grass 0.5
    with pytest.raises(SystemExit):
        trans_mod.main()

    assert out.read_bytes() == sentinel                    # not clobbered
    assert not (tmp_path / "metrics_transmission.json").exists()


def test_landed_assignment_metric_records_ok(tmp_path, monkeypatch):
    # On a correct run the metric carries the positive evidence (assigned_ok + expected).
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    out = tmp_path / "asset_out.ply"
    _run(monkeypatch, inp, out, ["--trans-leaf", "0.5", "--trans-grass", "0.5"])
    m = json.loads((tmp_path / "metrics_transmission.json").read_text())
    assert m["assignment"]["leaf"]["assigned_ok"] is True
    assert m["assignment"]["leaf"]["expected"] == 0.5
    assert m["assignment"]["grass"]["assigned_ok"] is True
    assert m["counts_consistent"] is True
    assert m["n_other_label"] == 0


def test_out_of_range_flag_fails_without_clobber(tmp_path, monkeypatch):
    # An out-of-[0,1] flag must fail-closed BEFORE any write — never clobbering a prior
    # good asset.ply, and writing no metrics.
    inp = tmp_path / "asset.ply"
    _make_asset(inp, _LABELS)
    out = tmp_path / "asset_out.ply"
    sentinel = b"SENTINEL-do-not-clobber"
    out.write_bytes(sentinel)

    monkeypatch.setattr(sys, "argv",
                        ["transmission", "--in", str(inp), "--out", str(out),
                         "--trans-leaf", "1.5"])
    with pytest.raises(SystemExit):
        trans_mod.main()

    assert out.read_bytes() == sentinel                    # not clobbered
    assert not (tmp_path / "metrics_transmission.json").exists()
