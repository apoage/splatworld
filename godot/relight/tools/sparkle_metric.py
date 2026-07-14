#!/usr/bin/env python3
"""sparkle_metric.py — temporal-flicker (sparkle) metric over an orbit frame sequence.

DIAGNOSTIC tool (NEW, normal-quality diagnosis task 2026-07-13). Consumes the PNG
frame sequences dumped by render_sparkle.gd (frame_%04d.png) and quantifies the
high-frequency TEMPORAL flicker per covered pixel — the "sparkle" the owner saw on
individual splats during the light orbit — separated from the smooth relight ramp.

Runs headless/CPU in the splat-relight conda env (numpy + PIL only). No GPU.

METRIC (primary = temporal high-pass RMS of luma):
  luma L_t(p) = 0.2126 R + 0.7152 G + 0.0722 B, per pixel, in [0,1] (8-bit PNG /255).
  Background reference BG = median of the outer-border pixels of frame 0 (robust to
  the tonemap/sRGB transform Godot applies on save). A pixel is FOREGROUND iff, in
  EVERY frame, the L1 colour distance to BG exceeds COVER_EPS (=0.05) — the temporal
  intersection, so silhouette edges that blink to background never enter the metric.
  Second temporal difference d2_t(p) = L_{t+1} - 2 L_t + L_{t-1}  (t = 1..N-2). This
  is a discrete high-pass: it is ZERO for any constant or linearly-ramping luma, so
  the smooth relight response (a slow ramp/sinusoid as the light sweeps) is rejected
  and only frame-to-frame twinkle survives.
    per-pixel sparkle  s(p)  = sqrt( mean_t d2_t(p)^2 )
    SCENE SPARKLE SCORE       = mean over foreground pixels of s(p)   [x1000 in table]
  Reported alongside: p99 / p999 of s(p) (the worst-twinkling splats the eye catches),
  a deadbanded sign-flip rate on the first differences (twinkle frequency), mean|dL|
  (total temporal activity incl. the smooth ramp), and the scene-mean-luma range over
  the orbit (confirms RELIT responds to the light and RAW is flat / camera-static).

ATTRIBUTION (interpretation is in the validation doc):
  RELIT >> RAW           -> shading class (normals/specular) -> Step-2 warranted.
  RAW ~= RELIT           -> sort-order/aliasing class (GDGS-side) -> STOP + DECISIONS.
  pruning removes most   -> floaters catching the light (prune/export mitigation).

Usage:
  python sparkle_metric.py \
    --variant raw=/abs/raw --variant relit=/abs/relit --variant relit_pruned=/abs/pruned \
    --evidence-dir /abs/evidence
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil

import numpy as np
from PIL import Image

COVER_EPS = 0.05      # L1 colour distance from BG to count a pixel as covered
BORDER = 8            # px border used to estimate the background colour
SIGNFLIP_DEADBAND = 1.0 / 255.0   # ignore sub-LSB wiggle when counting sign flips


def _load_luma_stack(frames_dir: str):
    paths = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    if len(paths) < 3:
        raise SystemExit(f"[sparkle] need >=3 frames in {frames_dir}, found {len(paths)}")
    imgs = []
    for p in paths:
        a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32) / 255.0
        imgs.append(a)
    rgb = np.stack(imgs, axis=0)                    # (N, H, W, 3)
    luma = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2])
    return rgb, luma, paths


def _bg_color(rgb0: np.ndarray) -> np.ndarray:
    h, w, _ = rgb0.shape
    b = BORDER
    border = np.concatenate([
        rgb0[:b, :, :].reshape(-1, 3), rgb0[-b:, :, :].reshape(-1, 3),
        rgb0[:, :b, :].reshape(-1, 3), rgb0[:, -b:, :].reshape(-1, 3),
    ], axis=0)
    return np.median(border, axis=0)


def _scores(luma: np.ndarray, fg: np.ndarray) -> dict:
    """Per-pixel + scene scores over the foreground pixels `fg` (H,W bool)."""
    h, w = fg.shape
    n_fg = int(fg.sum())
    lf = luma[:, fg]                                            # (N, n_fg)

    # NOTE: this screen d2 metric is QUALITATIVE ONLY. On 8-bit PNG luma the 2nd
    # temporal difference of a smooth relight ramp has a quantization RMS floor of
    # ~sqrt(0.5)/255 ~= 2.77 (x1000), so the RELIT absolute is NOT a twinkle magnitude
    # (use precompute/tools/gaussian_twinkle.py for that). RAW being ~flat (its frames
    # are identical => no inter-frame quantization) is the load-bearing fact here.
    d2 = lf[2:] - 2.0 * lf[1:-1] + lf[:-2]                      # (N-2, n_fg)
    s = np.sqrt(np.mean(d2 * d2, axis=0))                       # (n_fg,)

    d1 = lf[1:] - lf[:-1]                                       # (N-1, n_fg)
    sig = np.where(np.abs(d1) > SIGNFLIP_DEADBAND, np.sign(d1), 0.0)
    flips = np.zeros(n_fg, dtype=np.float64)
    prev = sig[0].copy()
    for t in range(1, sig.shape[0]):
        cur = sig[t]
        both = (prev != 0) & (cur != 0)
        flips += (both & (cur != prev)).astype(np.float64)
        prev = np.where(cur != 0, cur, prev)
    signflip_rate = float((flips / max(sig.shape[0] - 1, 1)).mean())

    per_frame_mean = lf.mean(axis=1)
    smap = np.zeros((h, w), dtype=np.float32)
    smap[fg] = s
    return {
        "n_foreground": n_fg, "coverage_frac": n_fg / float(h * w),
        "sparkle_score": float(s.mean()),
        "sparkle_p99": float(np.percentile(s, 99)),
        "sparkle_p999": float(np.percentile(s, 99.9)),
        "sparkle_max": float(s.max()),
        "signflip_rate": signflip_rate,
        "mean_abs_dluma": float(np.abs(d1).mean()),
        "luma_range": float(per_frame_mean.max() - per_frame_mean.min()),
        "smap": smap,
    }


def analyze(name: str, frames_dir: str) -> dict:
    """Load a variant and score it on its OWN per-frame-intersection foreground."""
    rgb, luma, paths = _load_luma_stack(frames_dir)
    n, h, w = luma.shape
    bg = _bg_color(rgb[0])
    # foreground = covered (L1 dist from BG > eps) in EVERY frame (temporal intersection)
    fg = (np.abs(rgb - bg[None, None, None, :]).sum(axis=-1) > COVER_EPS).all(axis=0)
    if int(fg.sum()) == 0:
        raise SystemExit(f"[sparkle] {name}: no foreground pixels covered in all frames")
    out = {"name": name, "frames_dir": frames_dir, "n_frames": n,
           "resolution": (w, h), "bg": bg.tolist(), "n_total": h * w,
           "fg": fg, "luma": luma, "paths": paths}
    out.update(_scores(luma, fg))
    return out


def _write_heatmap(res: dict, out_path: str, vmax: float) -> None:
    smap = res["smap"]
    norm = np.clip(smap / max(vmax, 1e-9), 0.0, 1.0)
    norm = np.power(norm, 0.5)          # gamma to lift faint twinkle for the eye
    img = (norm * 255.0).astype(np.uint8)
    Image.fromarray(img, mode="L").save(out_path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", action="append", required=True,
                    help="name=frames_dir (repeatable)")
    ap.add_argument("--evidence-dir", default=None,
                    help="write per-variant sparkle heatmaps + 2 sample frames here")
    ap.add_argument("--shared-mask", action="store_true",
                    help="score every variant on ONE shared foreground mask (the "
                         "intersection of each variant's per-frame-covered mask) so the "
                         "numbers are strictly comparable pixel-for-pixel.")
    args = ap.parse_args()

    variants = []
    for v in args.variant:
        if "=" not in v:
            raise SystemExit(f"[sparkle] --variant must be name=dir, got {v!r}")
        name, d = v.split("=", 1)
        variants.append((name, d))

    results = [analyze(name, d) for name, d in variants]

    if args.shared_mask:
        shared = results[0]["fg"].copy()
        for r in results[1:]:
            shared &= r["fg"]
        if int(shared.sum()) == 0:
            raise SystemExit("[sparkle] --shared-mask: variants share no foreground pixels")
        for r in results:
            r["fg"] = shared
            r.update(_scores(r["luma"], shared))
        print(f"[sparkle] shared foreground mask: {int(shared.sum())} px "
              f"({shared.sum()/float(shared.size)*100:.2f}% of frame), locked frame count "
              f"{results[0]['n_frames']}")

    # shared heatmap normalisation so the three maps are visually comparable
    vmax = max(float(np.percentile(r["smap"][r["fg"]], 99.5)) for r in results)

    print("\n=== SCREEN d2 TABLE (QUALITATIVE ONLY — 8-bit-quantization-confounded; "
          "RELIT absolute is NOT a twinkle magnitude; see gaussian_twinkle.py) ===")
    hdr = (f"{'variant':<16}{'splat_score':>12}{'p99':>10}{'p999':>10}"
           f"{'signflip':>10}{'mean|dL|':>10}{'luma_rng':>10}{'cover%':>9}")
    print(hdr)
    print("-" * len(hdr))
    base = None
    for r in results:
        if r["name"] == "raw":
            base = r
    for r in results:
        line = (f"{r['name']:<16}"
                f"{r['sparkle_score']*1000:>12.4f}"
                f"{r['sparkle_p99']*1000:>10.3f}"
                f"{r['sparkle_p999']*1000:>10.3f}"
                f"{r['signflip_rate']:>10.4f}"
                f"{r['mean_abs_dluma']*1000:>10.3f}"
                f"{r['luma_range']*1000:>10.3f}"
                f"{r['coverage_frac']*100:>9.2f}")
        print(line)
    if base is not None and base["sparkle_score"] > 0:
        print("\n--- ratios vs RAW baseline (sparkle_score) ---")
        for r in results:
            print(f"  {r['name']:<16} {r['sparkle_score']/base['sparkle_score']:.2f}x")

    if args.evidence_dir:
        os.makedirs(args.evidence_dir, exist_ok=True)
        for r in results:
            hp = os.path.join(args.evidence_dir, f"sparkle_{r['name']}.png")
            _write_heatmap(r, hp, vmax)
            print(f"[sparkle] heatmap -> {hp}")
            paths = r["paths"]
            for frac, tag in ((0.25, "q1"), (0.75, "q3")):
                idx = int(round(frac * (len(paths) - 1)))
                dst = os.path.join(args.evidence_dir, f"frame_{r['name']}_{tag}_{idx:04d}.png")
                shutil.copyfile(paths[idx], dst)
                print(f"[sparkle] sample -> {dst}")
        print(f"[sparkle] shared heatmap vmax(p99.5) = {vmax*1000:.4f} (x1000 luma)")


if __name__ == "__main__":
    main()
