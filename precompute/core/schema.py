"""Per-Gaussian asset schema — THE CONTRACT (see CLAUDE.md).

This module is the single source of truth for the extended Gaussian-splat
schema written to `assets/built/<name>/asset.ply`. It holds *only* field
names, dtypes, versions and label semantics — the actual binary read/write
lives in `ply_io.py`, which imports from here.

Rules (from CLAUDE.md, do not re-litigate):
- albedo_* is SH degree 0 ONLY (light-free base color). Never bake higher SH.
- Any schema change bumps SCHEMA_VERSION and updates BOTH the exporter and the
  Godot importer in the same commit, and gets an entry in docs/decisions.md.
- Binary little-endian PLY; header carries the comment `splat_relight_schema N`.
"""

SCHEMA_VERSION = 1
HEADER_COMMENT = f"splat_relight_schema {SCHEMA_VERSION}"

# --- Standard 3DGS geometry (kept verbatim from vanilla 3DGS) -----------------
# Conventions (enforced/documented in ply_io.py):
#   position  : world units, Godot convention in the *built* asset (Y-up, -Z fwd)
#   scale_*   : 3DGS log-scale (stored pre-exp), as gsplat emits
#   rot_*     : quaternion, order (w, x, y, z), normalized
#   opacity   : 3DGS logit (stored pre-sigmoid), as gsplat emits
GEOMETRY_FIELDS = [
    ("x", "f4"), ("y", "f4"), ("z", "f4"),
    ("scale_0", "f4"), ("scale_1", "f4"), ("scale_2", "f4"),
    ("rot_0", "f4"), ("rot_1", "f4"), ("rot_2", "f4"), ("rot_3", "f4"),
    ("opacity", "f4"),
]

# --- Extended material attributes (this project's additions) ------------------
# NOTE: color is represented by albedo_* here, NOT by 3DGS f_dc_*/f_rest_*.
# The runtime shades albedo directly; higher SH orders are forbidden in exports.
MATERIAL_FIELDS = [
    ("albedo_r", "f4"), ("albedo_g", "f4"), ("albedo_b", "f4"),  # linear, SH deg0
    ("nx", "f4"), ("ny", "f4"), ("nz", "f4"),                    # unit normal
    ("rough", "f4"),                                             # [0,1]
    ("trans", "f4"),                                             # [0,1] transmission
]

LABEL_FIELD = ("label", "u1")  # u8

# --- Label semantics ----------------------------------------------------------
LABELS = {
    0: "ground",
    1: "grass",
    2: "leaf",
    3: "bark",
}
LABEL_IDS = {v: k for k, v in LABELS.items()}


def basis_fields(n_basis: int):
    """Mode-B optional baked lighting-basis coefficients: b{i}_r/g/b (f32)."""
    fields = []
    for i in range(n_basis):
        fields += [(f"b{i}_r", "f4"), (f"b{i}_g", "f4"), (f"b{i}_b", "f4")]
    return fields


def field_layout(n_basis: int = 0):
    """Full ordered field list for the built asset PLY.

    n_basis > 0 only for mode-B (PRT-lite) assets; default export is mode-A.
    """
    return GEOMETRY_FIELDS + MATERIAL_FIELDS + [LABEL_FIELD] + basis_fields(n_basis)


# Attribute range / sanity expectations used by metrics.json validation.
# (min, max) inclusive; None = unbounded. NaN/Inf is always a failure.
# NOTE: the albedo upper bound is deliberately GENEROUS (4.0). Pre-decompose
# albedo is baked SH-DC appearance, NOT true reflectance, so it can legitimately
# exceed 1 (live assets peak ~1.82). Export is faithful (no clamp), so the bound
# is a garbage-catcher for NaN/negative/absurd only. M2/decompose will TIGHTEN the
# albedo bound to [0,1] once albedo becomes real reflectance.
FIELD_RANGES = {
    "albedo_r": (0.0, 4.0), "albedo_g": (0.0, 4.0), "albedo_b": (0.0, 4.0),
    "rough": (0.0, 1.0),
    "trans": (0.0, 1.0),
    "opacity": (None, None),  # logit space, unbounded
}


def validate_ranges(field_arrays: dict, albedo_max: float = 4.0) -> list[str]:
    """Check field arrays against FIELD_RANGES. Returns a list of human-readable
    violation messages (empty == all good).

    `field_arrays` maps a schema field name (e.g. "albedo_r", "rough", "trans",
    "opacity") to its numpy array. Fields not present in FIELD_RANGES are ignored;
    fields in FIELD_RANGES but absent from the mapping are skipped. NaN/Inf is
    always a violation regardless of the declared bounds.

    `albedo_max` tightens the albedo upper bound: the M1 neutral path keeps the
    generous 4.0 (baked SH-DC appearance can exceed 1), but the decompose path
    passes 1.0 because albedo there is real reflectance in [0,1].

    This is the consumer FIELD_RANGES always promised to have: export drives it and
    asserts the result, so an out-of-contract attribute fails the stage.
    """
    import numpy as np
    ranges = dict(FIELD_RANGES)
    for ch in ("albedo_r", "albedo_g", "albedo_b"):
        lo, _ = ranges[ch]
        ranges[ch] = (lo, albedo_max)
    problems: list[str] = []
    for name, (lo, hi) in ranges.items():
        if name not in field_arrays:
            continue
        a = np.asarray(field_arrays[name])
        if a.size == 0:
            continue
        if bool(np.isnan(a).any()) or bool(np.isinf(a).any()):
            problems.append(f"{name}: NaN/Inf present")
            continue
        amin, amax = float(np.min(a)), float(np.max(a))
        if lo is not None and amin < lo:
            problems.append(f"{name}: min {amin:.4f} < {lo}")
        if hi is not None and amax > hi:
            problems.append(f"{name}: max {amax:.4f} > {hi}")
    return problems
