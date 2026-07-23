"""Deliverable B gates — baseline-refresh helper + decompose baseline-path wiring
(2026-07-23-vply-cleanup-roundtrip).

The 48k-clobber guard (decompose.read_verified_baseline_psnr) FATALs when the loaded cloud's
count differs from the baseline metrics' n_gaussians. That guard MUST stay intact; a cleaned
cloud (fewer splats) instead gets a NEW trustworthy baseline from tools/refresh_baseline, and
decompose reads the baseline whose name tracks the --in stem. These gates (fault-injection):

  * refresh_baseline writes the CLEANED count recounted from the ply — NOT the original
    (a decoy stale metrics_train_base.json is present to model the trap);
  * decompose.baseline_metrics_path derives metrics_<in-stem>.json (so train_base_clean.ply
    reads metrics_train_base_clean.json, train_base.ply still reads metrics_train_base.json);
  * the guard ACCEPTS the refreshed baseline for the cleaned count and still REFUSES a wrong
    count — so the budget gate can then evaluate.
"""
import json
import os

import numpy as np

from precompute.core import ply_io
from precompute.stages import decompose as D
from precompute.tools import refresh_baseline as RB


def _write_tiny_standard_ply(path, n, seed=0):
    """A minimal SH-degree-0 vanilla 3DGS ply (no f_rest) with unit quats."""
    rng = np.random.default_rng(seed)
    xyz = rng.standard_normal((n, 3)).astype(np.float32)
    sh0 = rng.standard_normal((n, 3)).astype(np.float32)
    shN = np.zeros((n, 0, 3), np.float32)
    opacity = rng.standard_normal(n).astype(np.float32)
    scales = rng.standard_normal((n, 3)).astype(np.float32)
    quats = rng.standard_normal((n, 4)).astype(np.float32)
    quats /= np.linalg.norm(quats, axis=1, keepdims=True)
    ply_io.write_standard_3dgs_ply(str(path), xyz, sh0, shN, opacity, scales, quats)


def test_baseline_metrics_path_tracks_in_stem(tmp_path):
    """decompose reads the baseline whose NAME tracks the --in stem: the original cloud
    keeps metrics_train_base.json (unchanged behaviour) while a cleaned re-decompose reads
    its own metrics_train_base_clean.json. Would fail if the path stayed hardcoded."""
    out_dir = str(tmp_path)
    assert D.baseline_metrics_path(os.path.join(out_dir, "train_base.ply"), out_dir) == \
        os.path.join(out_dir, "metrics_train_base.json")
    assert D.baseline_metrics_path(os.path.join(out_dir, "train_base_clean.ply"), out_dir) == \
        os.path.join(out_dir, "metrics_train_base_clean.json")


def test_refresh_baseline_writes_cleaned_count_not_original(tmp_path):
    """refresh_baseline recomputes n_gaussians FROM THE CLEANED cloud, never copying a stale
    baseline. A decoy original metrics_train_base.json (n_gaussians=999) sits beside it; the
    refreshed metrics_train_base_clean.json must carry the ply's real (smaller) count.

    Mutation reasoning: had the helper written the original count (999) — e.g. by reading the
    stale file instead of recounting — this asserts != 999 and == the cleaned 7. The renderer
    + view loader are injected (no CUDA) so the COUNT/gate logic is what is under test; the
    gsplat re-render path is the same one train_base uses and is exercised by the owner's GPU
    re-decompose."""
    n_clean = 7
    n_original = 999
    clean_ply = tmp_path / "train_base_clean.ply"
    _write_tiny_standard_ply(clean_ply, n_clean)
    # the trap: a stale original baseline claiming the pre-clean count
    (tmp_path / "metrics_train_base.json").write_text(
        json.dumps({"stage": "train_base", "n_gaussians": n_original, "psnr_heldout_db": 30.0}))

    # injected stubs: a handful of tiny views (test_every=8 -> views 0 and 8 held out) and a
    # fixed PSNR — refresh_baseline must still recount n from the CLEANED ply.
    def fake_load_views(sparse, images):
        gts = [np.zeros((4, 4, 3), np.uint8) for _ in range(9)]
        Ks = [None] * 9
        viewmats = [None] * 9
        names = [f"v{i}" for i in range(9)]
        return Ks, viewmats, gts, names

    def fake_heldout_psnr(g, sh, sh_degree, Ks, viewmats, gts, test_idx, W, H, gpu):
        return 24.0

    out = tmp_path / "metrics_train_base_clean.json"
    metrics = RB.refresh_baseline(
        str(clean_ply), "SPARSE", "IMAGES", str(out), test_every=8, gpu=0,
        _load_views=fake_load_views, _heldout_psnr=fake_heldout_psnr)

    written = json.load(open(out))
    assert written["n_gaussians"] == n_clean
    assert written["n_gaussians"] != n_original
    assert metrics["n_gaussians"] == n_clean
    assert written["psnr_heldout_db"] == 24.0
    assert written["test_views"] == 2            # views 0 and 8 with test_every=8


def test_guard_accepts_refreshed_baseline_and_refuses_wrong_count(tmp_path):
    """The 48k-clobber guard stays intact: given the refreshed baseline, decompose ACCEPTS it
    for the cleaned count (returns the PSNR so the 1.5 dB budget gate can evaluate) and REFUSES
    a mismatched count (SystemExit). Fault-injection on the exact guard the task must not
    weaken."""
    n_clean = 7
    clean_ply = tmp_path / "train_base_clean.ply"
    _write_tiny_standard_ply(clean_ply, n_clean)

    def fake_load_views(sparse, images):
        gts = [np.zeros((4, 4, 3), np.uint8) for _ in range(9)]
        return [None] * 9, [None] * 9, gts, [f"v{i}" for i in range(9)]

    def fake_heldout_psnr(*a, **k):
        return 24.0

    out = str(tmp_path / "metrics_train_base_clean.json")
    RB.refresh_baseline(str(clean_ply), "S", "I", out, test_every=8, gpu=0,
                        _load_views=fake_load_views, _heldout_psnr=fake_heldout_psnr)

    # accepts the cleaned count -> returns the baseline PSNR (budget gate then evaluates)
    assert D.read_verified_baseline_psnr(out, n_clean) == 24.0
    # still fires on a wrong count (the guard was NOT weakened)
    import pytest
    with pytest.raises(SystemExit):
        D.read_verified_baseline_psnr(out, 999)

    # and the returned PSNR flows through the budget gate exactly (in-budget passes, sub fails)
    D.enforce_rerender_budget(24.0, True, 25.0, 1.5)          # 24.0 >= 25.0 - 1.5 -> ok
    with pytest.raises(SystemExit):
        D.enforce_rerender_budget(22.0, True, 25.0, 1.5)      # 22.0 < 23.5 -> FATAL
