"""ingest — video -> frames -> COLMAP SfM -> undistort -> PINHOLE TXT model (stage 1).

Formalizes the validated shakedown recipe (prototype/run_colmap_pxl144634.sh +
prototype/undistort_pxl144634.sh, 204/204 @ 0.90px on pxl_144634) into a resumable
pipeline stage. Produces exactly what train_base consumes:
  assets/raw/<name>/colmap/dense/{sparse_txt,images}

COLMAP runs in the isolated `colmap` conda env (CLAUDE.md); this COLMAP is 4.1.0 so the
GPU flags are `FeatureExtraction.use_gpu` / `FeatureMatching.use_gpu` (NOT Sift*).
Source clips under datasets/ are READ-ONLY; assets/raw/<name>/ is the writable workspace.

Resume model — per-step completion sentinels (NOT bare output-existence), because COLMAP
creates its outputs (frame files, database.db) at the START of a step, so a crashed step
leaves partial outputs that must not be trusted:
  .frames.done   {count, fps, video}  — written only after ffmpeg exits 0
  .features.done                       — written only after feature_extractor exits 0
  .match.done                          — written only after sequential_matcher exits 0
mapper/undistort/convert resume on their own final outputs (sparse/0, dense/sparse,
sparse_txt). Already-complete outputs from a pre-sentinel run are backfilled (trusted as
done, sentinel written) rather than re-run. The source clip and the colmap env are only
required when there is actual extraction/SfM work to do — a checkout with the built model
but no clip (e.g. the trader box, datasets/ gitignored) runs clean.

Usage:
  python -m precompute.stages.ingest --asset pxl_131945 \
    --video datasets/pixel4/PXL_20260711_131945488.LS.mp4 --fps 10
  # --video may be omitted: discovered from datasets/ by the HHMMSS token in --asset,
  # and is only needed when frames must actually be (re)extracted.
"""
from __future__ import annotations

import argparse, glob, json, math, os, shutil, subprocess, sys, time
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONDA = os.path.expanduser("~/miniconda3/bin/conda")


def name_from_video(video_path: str) -> str:
    """PXL_20260711_144634633.LS.mp4 -> pxl_144634 (pxl_<HHMMSS>). Parses the string only."""
    base = os.path.basename(video_path)
    parts = base.split("_")
    token = ""
    if len(parts) >= 3:
        token = "".join(c for c in parts[2] if c.isdigit())[:6]
    if len(token) < 6:
        raise ValueError(f"cannot derive pxl_<HHMMSS> name from {base!r}; pass --asset")
    return "pxl_" + token


def discover_video(asset: str, datasets_root: str) -> str:
    """Find the source clip for an asset by its HHMMSS token (pxl_<HHMMSS>)."""
    token = asset[4:] if asset.startswith("pxl_") else asset
    # anchor to the PXL_<date>_<HHMMSS> structure (token preceded by '_'), not a bare
    # substring — an unanchored match could silently pick the wrong clip.
    needle = "_" + token
    hits = sorted(
        p for p in glob.glob(os.path.join(datasets_root, "**", "*.mp4"), recursive=True)
        if needle in os.path.basename(p)
    )
    if not hits:
        raise FileNotFoundError(
            f"no clip matching token {token!r} under {datasets_root}; pass --video")
    if len(hits) > 1:
        sys.exit(f"[ingest] FAIL: ambiguous clip for token {token!r} "
                 f"({', '.join(os.path.basename(h) for h in hits)}); pass --video")
    return hits[0]


def _read_done(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _write_done(path, **data):
    with open(path, "w") as f:
        json.dump(data, f)


def run(cmd, tail=8):
    """Run a subprocess, stream a tail of its output, raise on nonzero."""
    print(f"[ingest] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True)
    for ln in r.stdout.splitlines()[-tail:]:
        print("   " + ln, flush=True)
    if r.returncode != 0:
        raise RuntimeError(f"command failed (rc={r.returncode}): {' '.join(cmd)}")
    return r.stdout


def _count_frames(d):
    return len(glob.glob(os.path.join(d, "frame_*.jpg")))


def parse_model_metrics(sparse_txt: str, raw_frame_count: int) -> dict:
    """Compute registration + track + reprojection metrics from a COLMAP TXT model.

    NOTE (deferred edge): registered-image count assumes exactly 2 data lines per image;
    an image with an empty POINTS2D line is rare here and would skew the //2 count.
    """
    img_lines = [l for l in open(os.path.join(sparse_txt, "images.txt"))
                 if l.strip() and not l.startswith("#")]
    registered = len(img_lines) // 2      # 2 lines per registered image
    errs, tracks = [], []
    for line in open(os.path.join(sparse_txt, "points3D.txt")):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        t = line.split()
        errs.append(float(t[7]))          # per-point mean reprojection error (px)
        tracks.append((len(t) - 8) // 2)  # (image_id, point2D_idx) pairs
    errs = np.asarray(errs, np.float64)
    mean_reproj = float(errs.mean()) if errs.size else float("nan")
    # Choose the denominator for registration_rate. If the raw frame set is gone
    # (model-only checkout) OR partial (fewer raw frames than the model registered —
    # contradictory), trust the model: total = registered (rate 1.0), never report > 1.
    raw_present = raw_frame_count > 0
    raw_partial = raw_present and registered > raw_frame_count
    total = raw_frame_count if (raw_present and not raw_partial) else registered
    return {
        "total_frames": int(total),
        "raw_frames_present": bool(raw_present),
        "raw_frames_partial": bool(raw_partial),
        "registered_frames": int(registered),
        "registration_rate": round(registered / total, 4) if total else 0.0,
        "points": int(errs.size),
        "mean_track_length": round(float(np.mean(tracks)), 3) if tracks else 0.0,
        "mean_reproj_error_px": round(mean_reproj, 4),
    }


def finalize(W, sparse_txt, dense_images, args, video, t0):
    """Compute metrics, write metrics_ingest.json, run the fail-closed guards."""
    m = parse_model_metrics(sparse_txt, _count_frames(os.path.join(W, "images")))
    dense_n = _count_frames(dense_images)
    m.update({
        "stage": "ingest", "asset": args.asset,
        "video": (os.path.relpath(video, REPO) if video and video.startswith(REPO) else video),
        "fps": args.fps, "camera_model": args.camera_model,
        "dense_images": dense_n,
        "wall_time_s": round(time.time() - t0, 1),
        "low_registration": None,   # set below once we know the rate
    })
    m["low_registration"] = bool(m["registration_rate"] < 0.5)

    mpath = os.path.join(W, "metrics_ingest.json")
    with open(mpath, "w") as f:
        json.dump(m, f, indent=2)

    print(f"[ingest] registered {m['registered_frames']}/{m['total_frames']} frames "
          f"({m['registration_rate']*100:.1f}%)  points={m['points']}  "
          f"track={m['mean_track_length']}  reproj={m['mean_reproj_error_px']} px  "
          f"dense_images={dense_n}", flush=True)
    print(f"[ingest] metrics -> {mpath}", flush=True)
    if m["low_registration"]:
        print(f"[ingest] WARNING: < 50% frames registered — DATA FINDING, weak footage; "
              f"re-validate on known-good clip per task fallback.", flush=True)

    # --- fail-closed guards (explicit exits, NOT asserts: survive python -O) ---
    if m["registered_frames"] == 0:
        sys.exit("[ingest] FAIL: COLMAP registered zero frames")
    # train_base consumes dense/images — it MUST match the registered set
    if dense_n != m["registered_frames"]:
        sys.exit(f"[ingest] FAIL: dense/images count {dense_n} != registered "
                 f"{m['registered_frames']} (train_base would break on this set)")
    if not math.isfinite(m["mean_reproj_error_px"]):
        sys.exit("[ingest] FAIL: mean reprojection error is not finite")
    if m["mean_reproj_error_px"] >= 2.0:
        sys.exit(f"[ingest] FAIL: mean reproj error {m['mean_reproj_error_px']} px "
                 f">= 2.0 px budget")
    print(f"[ingest] DONE  {m['wall_time_s']}s  -> {sparse_txt}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", help="asset name (pxl_<HHMMSS>); derived from --video if omitted")
    ap.add_argument("--video", help="source clip; discovered from datasets/ by token if omitted")
    ap.add_argument("--workspace", help="ingest workspace dir (default assets/raw/<asset>)")
    ap.add_argument("--datasets-root", default=os.path.join(REPO, "datasets"))
    ap.add_argument("--fps", type=int, default=10, help="frame extraction rate")
    ap.add_argument("--overlap", type=int, default=10, help="sequential_matcher overlap")
    ap.add_argument("--camera-model", default="OPENCV")
    ap.add_argument("--gpu", type=int, default=0, help="colmap gpu_index (visible-device local)")
    ap.add_argument("--conda", default=DEFAULT_CONDA)
    args = ap.parse_args()

    if not args.asset and not args.video:
        sys.exit("[ingest] specify --asset and/or --video")
    if args.video and not args.asset:
        args.asset = name_from_video(args.video)

    W = args.workspace or os.path.join(REPO, "assets", "raw", args.asset)
    images = os.path.join(W, "images")
    colmap = os.path.join(W, "colmap")
    db = os.path.join(colmap, "database.db")
    sparse = os.path.join(colmap, "sparse")
    sparse0 = os.path.join(sparse, "0")
    dense = os.path.join(colmap, "dense")
    dense_sparse = os.path.join(dense, "sparse")
    dense_images = os.path.join(dense, "images")
    sparse_txt = os.path.join(dense, "sparse_txt")
    frames_done = os.path.join(W, ".frames.done")
    features_done = os.path.join(W, ".features.done")
    match_done = os.path.join(W, ".match.done")
    os.makedirs(images, exist_ok=True)
    os.makedirs(sparse, exist_ok=True)

    CR = [args.conda, "run", "--no-capture-output", "-n", "colmap"]
    gi = str(args.gpu)
    t0 = time.time()
    requested_video = os.path.abspath(args.video) if args.video else None
    # The final model being complete means ALL SfM work is done: no clip and no colmap
    # env are needed (e.g. the trader box has the built model but datasets/ is gitignored).
    model_complete = all(os.path.exists(os.path.join(sparse_txt, f))
                         for f in ("cameras.txt", "images.txt", "points3D.txt"))
    print(f"[ingest] asset={args.asset}  fps={args.fps}  workspace={W}"
          f"{'  (model complete — skip SfM)' if model_complete else ''}", flush=True)

    def resolve_video():
        """Lazily locate + validate the clip — only when extraction must actually run.
        Fails loud (clean nonzero exit) rather than proceeding on unverified frames."""
        v = requested_video
        if not v:
            try:
                v = os.path.abspath(discover_video(args.asset, args.datasets_root))
            except FileNotFoundError as e:
                sys.exit(f"[ingest] FAIL: {e}")
        if not os.path.isfile(v):
            sys.exit(f"[ingest] FAIL: video not found: {v}")
        return v

    resolved_video = requested_video     # for the metrics record; may be filled by extraction

    # 1. frames — sentinel-gated. Root question: are the on-disk frames BLESSED?
    #    Blessed = either a completed extraction is on record (.frames.done) OR a downstream
    #    stage already consumed them (model_complete, whose finalize guards vouch for it).
    #    Unblessed on-disk frames may be a truncated crash artifact — NEVER trust them.
    on_disk = _count_frames(images)
    sent = _read_done(frames_done)
    need_extract = False
    if sent is not None:
        # a completed extraction is on record — validate params, then count
        if args.fps != sent.get("fps"):
            sys.exit(f"[ingest] FAIL: .frames.done recorded fps {sent.get('fps')} but "
                     f"--fps is {args.fps}; use a fresh --asset or clear {W}")
        stored_video = sent.get("video")
        if requested_video and stored_video and requested_video != stored_video:
            sys.exit(f"[ingest] FAIL: .frames.done recorded video {stored_video!r} but "
                     f"--video is {requested_video!r}; use a fresh --asset or clear {W}")
        if requested_video and not stored_video:
            # recorded without a clip (backfill); adopt the now-provided one, don't refuse
            resolved_video = requested_video
            _write_done(frames_done, count=sent.get("count", on_disk),
                        fps=args.fps, video=requested_video)
        else:
            resolved_video = stored_video or resolved_video
        if on_disk != sent.get("count") and not model_complete:
            print(f"[ingest] frame count {on_disk} != sentinel {sent.get('count')} "
                  f"(partial extraction) — re-extracting", flush=True)
            need_extract = True
        else:
            print(f"[ingest] {on_disk} frames complete (sentinel) — skip extraction", flush=True)
    elif model_complete:
        # no sentinel, but SfM already consumed these frames and finalize vouches for the
        # result — trust + backfill; the clip is NOT required in this state.
        print(f"[ingest] model complete, no frame sentinel — backfilling .frames.done "
              f"({on_disk} frames)", flush=True)
        _write_done(frames_done, count=on_disk, fps=args.fps, video=requested_video)
    else:
        # no sentinel, not model_complete → any on-disk frames are UNBLESSED / possibly a
        # truncated crash artifact. Never build on them: (re)extract from the clip.
        if on_disk > 0:
            print(f"[ingest] {on_disk} unblessed frames (no sentinel, no model) — cannot trust "
                  f"a possibly-partial set; re-extracting from clip", flush=True)
        need_extract = True

    if need_extract:
        v = resolve_video()      # fail-loud BEFORE deleting anything (frames preserved on no-clip)
        # A forced re-extract invalidates ALL frame-derived downstream state: otherwise a
        # surviving db/sparse/dense would be backfilled as "done" and the shipped model would
        # be built from the OLD frames — internally consistent but inconsistent with the new
        # ones (silent wrong asset). Wipe it so feature/match/mapper/undistort/convert re-run.
        if os.path.exists(db):
            os.remove(db)
        for d in (sparse, dense):
            shutil.rmtree(d, ignore_errors=True)
        for s in (features_done, match_done):
            if os.path.exists(s):
                os.remove(s)
        os.makedirs(sparse, exist_ok=True)
        # clear any partial/stale frames so a shorter re-extract leaves no tail files
        for f in glob.glob(os.path.join(images, "frame_*.jpg")):
            os.remove(f)
        run(CR + ["ffmpeg", "-hide_banner", "-y", "-i", v,
                  "-vf", f"fps={args.fps}", "-qscale:v", "2", "-start_number", "1",
                  os.path.join(images, "frame_%04d.jpg")])
        on_disk = _count_frames(images)
        if on_disk == 0:
            sys.exit("[ingest] FAIL: frame extraction produced no frames")
        _write_done(frames_done, count=on_disk, fps=args.fps, video=v)
        resolved_video = v
        print(f"[ingest] extracted {on_disk} frames -> {images}", flush=True)
    if on_disk == 0 and not model_complete:
        # model_complete needs no raw frames (they may be cleaned on a model-only checkout)
        sys.exit("[ingest] FAIL: no frames available for SfM")

    # 2. feature_extractor — sentinel-gated (db appears at step START) -------------
    reco_ok = os.path.exists(os.path.join(sparse0, "cameras.bin"))
    # backfill: a complete reconstruction (or full model) proves extract+match finished
    if (reco_ok or model_complete) and not os.path.exists(features_done):
        _write_done(features_done, backfilled=True)
    if (reco_ok or model_complete) and not os.path.exists(match_done):
        _write_done(match_done, backfilled=True)

    if not os.path.exists(features_done):
        run(CR + ["colmap", "feature_extractor",
                  "--database_path", db, "--image_path", images,
                  "--ImageReader.single_camera", "1",
                  "--ImageReader.camera_model", args.camera_model,
                  "--FeatureExtraction.use_gpu", "1",
                  "--FeatureExtraction.gpu_index", gi])
        _write_done(features_done)
    else:
        print(f"[ingest] features complete (sentinel) — skip feature_extractor", flush=True)

    # 3. sequential_matcher — SEPARATE sentinel (do NOT gate on db existence) ------
    if not os.path.exists(match_done):
        run(CR + ["colmap", "sequential_matcher",
                  "--database_path", db,
                  "--FeatureMatching.use_gpu", "1",
                  "--FeatureMatching.gpu_index", gi,
                  "--SequentialMatching.overlap", str(args.overlap)])
        _write_done(match_done)
    else:
        print(f"[ingest] matches complete (sentinel) — skip sequential_matcher", flush=True)

    if model_complete:
        print(f"[ingest] model complete — skip mapper/undistort/convert", flush=True)
    else:
        # 4. mapper (resume on its own final output) -------------------------------
        if not os.path.exists(os.path.join(sparse0, "cameras.bin")):
            run(CR + ["colmap", "mapper",
                      "--database_path", db, "--image_path", images,
                      "--output_path", sparse])
        else:
            print(f"[ingest] sparse/0 exists — skip mapper", flush=True)
        if not os.path.exists(os.path.join(sparse0, "cameras.bin")):
            sys.exit("[ingest] FAIL: mapper produced no reconstruction (sparse/0)")

        # 5. undistort -> PINHOLE dense model --------------------------------------
        if not os.path.exists(os.path.join(dense_sparse, "cameras.bin")):
            run(CR + ["colmap", "image_undistorter",
                      "--image_path", images, "--input_path", sparse0,
                      "--output_path", dense, "--output_type", "COLMAP"])
        else:
            print(f"[ingest] dense/sparse exists — skip undistort", flush=True)

        # 6. model_converter -> TXT ------------------------------------------------
        if not os.path.exists(os.path.join(sparse_txt, "cameras.txt")):
            os.makedirs(sparse_txt, exist_ok=True)
            run(CR + ["colmap", "model_converter",
                      "--input_path", dense_sparse,
                      "--output_path", sparse_txt, "--output_type", "TXT"])
        else:
            print(f"[ingest] sparse_txt exists — skip model_converter", flush=True)

    finalize(W, sparse_txt, dense_images, args, resolved_video, t0)


if __name__ == "__main__":
    main()
