"""Binary PLY reader/writer — THE only place that touches PLY bytes (CLAUDE.md).

Handles two formats:
  * the extended `splat_relight_schema N` asset (read/write) — our contract;
  * vanilla 3DGS PLY (read only) — to ingest train_base / third-party splats
    (f_dc/f_rest/opacity/scale/rot) into `decompose`.

Also the single home of the COLMAP->Godot coordinate conversion. Per CLAUDE.md
the conversion is *applied* exactly once (in `export`) but its matrix is
*documented and implemented* here.

Pure numpy; no third-party PLY lib, so the on-disk header is exactly ours.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from . import schema
# SH degree-0 helpers live in gaussmath (single home); re-exported here so the
# long-standing `ply_io.sh0_to_rgb` / `ply_io.SH_C0` call sites keep working.
from .gaussmath import SH_C0, sh0_to_rgb, rgb2sh  # noqa: F401

# --- PLY <-> numpy type maps --------------------------------------------------
_PLY_TO_NP = {
    "float": "<f4", "float32": "<f4", "f4": "<f4",
    "double": "<f8", "float64": "<f8",
    "uchar": "|u1", "uint8": "|u1", "u1": "|u1",
    "int": "<i4", "int32": "<i4",
    "uint": "<u4", "uint32": "<u4",
    "short": "<i2", "ushort": "<u2",
}
_NP_KIND_TO_PLY = {"f4": "float", "u1": "uchar", "f8": "double", "i4": "int", "u4": "uint"}


def _ply_prop_name(np_type: str) -> str:
    return _NP_KIND_TO_PLY[np_type]


# --- COLMAP -> Godot coordinate conversion ------------------------------------
# COLMAP/OpenCV world : x-right, y-down, z-forward.
# Godot/OpenGL world  : x-right, y-up,   z-back (-Z is forward).
# The change of basis is a sign flip on Y and Z:
#
#     M = diag(1, -1, -1)
#
# det(M) = +1, so M is a PROPER rotation (180 deg about X). That matters:
#   * positions / normals: p' = M @ p
#   * covariance rotation quaternions transform cleanly by left-multiplying with
#     the quaternion of M (a reflection, det=-1, could not). q(M) = (w=0,x=1,y=0,z=0).
# NOTE (verified 2026-07-12, see docs/decisions.md for the full analysis):
# This matrix is the PURE COLMAP->Godot change of basis and is the ONLY conversion
# applied to exported data. GDGS layers two of its own transforms at IMPORT/NODE
# time that we do NOT (and mostly cannot) compensate for here:
#   * centering: the importer subtracts the point-cloud centroid and discards it
#     (gaussian_resource_builder.gd) — a rigid translation. The asset's absolute
#     world position is therefore lost; the GaussianSplatNode transform is
#     authoritative for placement (benign for M4 carpet scatter, which sets node
#     transforms explicitly).
#   * a default -180 deg Z correction (gaussian_splat_node.gd) applied to a node
#     ONLY while its basis is identity, and SKIPPED once a scatter/rotation basis
#     is set. With this export matrix + that default correction on an identity
#     node the net COLMAP->render map is diag(-1,1,-1) (180 deg about Y): UP is
#     preserved (foliage renders upright, matching the M1 eyeball renders) but
#     azimuth is yaw-flipped 180 deg — invisible under orbit, but an inconsistency
#     between identity-basis and scatter-basis instances that M4 must resolve on
#     the Godot node side (explicit transforms), not by re-deriving this matrix.
# No export-time compensation is applied or needed for M1; do NOT patch Godot-side.
COLMAP_TO_GODOT = np.diag([1.0, -1.0, -1.0]).astype(np.float32)
_Q_M = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)  # (w,x,y,z) of 180 deg about X


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of (...,4) quats in (w,x,y,z) order."""
    aw, ax, ay, az = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bw, bx, by, bz = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], axis=-1)


def colmap_to_godot(xyz: np.ndarray, normal: np.ndarray | None, rot_wxyz: np.ndarray | None):
    """Apply M once. Returns (xyz', normal', rot') with the same shapes given."""
    xyz_g = xyz @ COLMAP_TO_GODOT.T
    normal_g = None if normal is None else (normal @ COLMAP_TO_GODOT.T)
    rot_g = None
    if rot_wxyz is not None:
        q = np.broadcast_to(_Q_M, rot_wxyz.shape)
        rot_g = _quat_mul(q, rot_wxyz)
    return xyz_g, normal_g, rot_g


# --- Extended asset container -------------------------------------------------
@dataclass
class AssetGaussians:
    xyz: np.ndarray        # (N,3) f32
    scale: np.ndarray      # (N,3) f32  (3DGS log-scale)
    rot: np.ndarray        # (N,4) f32  (w,x,y,z)
    opacity: np.ndarray    # (N,)  f32  (3DGS logit)
    albedo: np.ndarray     # (N,3) f32  (linear, SH deg0 only)
    normal: np.ndarray     # (N,3) f32  (unit)
    rough: np.ndarray      # (N,)  f32  [0,1]
    trans: np.ndarray      # (N,)  f32  [0,1]
    label: np.ndarray      # (N,)  u8
    basis: np.ndarray | None = None   # (N, n_basis, 3) f32 or None

    @property
    def count(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def n_basis(self) -> int:
        return 0 if self.basis is None else int(self.basis.shape[1])


# --- header helpers -----------------------------------------------------------
def _parse_header(f):
    """Read PLY header from a binary file at position 0. Returns
    (props:list[(name,np_type)], n_vertex:int, data_offset:int, comments:list[str]).
    Comments are collected (decoded, sans the leading `comment` keyword) so callers
    can validate provenance markers such as `splat_relight_schema N`."""
    line = f.readline()
    if line.strip() != b"ply":
        raise ValueError("not a PLY file")
    fmt = f.readline().strip()
    if fmt != b"format binary_little_endian 1.0":
        raise ValueError(f"unsupported PLY format: {fmt!r} (need binary_little_endian 1.0)")
    props: list[tuple[str, str]] = []
    comments: list[str] = []
    n_vertex = 0
    in_vertex = False
    while True:
        raw = f.readline()
        if not raw:
            raise ValueError("unexpected EOF in PLY header")
        parts = raw.split()
        kw = parts[0]
        if kw == b"comment":
            comments.append(b" ".join(parts[1:]).decode("ascii", "replace"))
            continue
        if kw == b"element":
            in_vertex = (parts[1] == b"vertex")
            if in_vertex:
                n_vertex = int(parts[2])
        elif kw == b"property" and in_vertex:
            if parts[1] == b"list":
                raise ValueError("list properties unsupported in vertex element")
            ply_type = parts[1].decode()
            name = parts[2].decode()
            props.append((name, _PLY_TO_NP[ply_type]))
        elif kw == b"end_header":
            break
    return props, n_vertex, f.tell(), comments


def _read_structured(path: str):
    with open(path, "rb") as f:
        props, n, offset, comments = _parse_header(f)
        dt = np.dtype([(name, npt) for name, npt in props])
        f.seek(offset)
        arr = np.fromfile(f, dtype=dt, count=n)
    if arr.shape[0] != n:
        raise ValueError(f"expected {n} vertices, read {arr.shape[0]}")
    return arr, [p[0] for p in props], comments


def _schema_version_from_comments(comments) -> int | None:
    """Return N from a `splat_relight_schema N` header comment, or None if absent.
    Raises ValueError if the marker is present but malformed."""
    for c in comments:
        parts = c.split()
        if parts and parts[0] == "splat_relight_schema":
            if len(parts) != 2:
                raise ValueError(f"malformed schema header comment: {c!r}")
            try:
                return int(parts[1])
            except ValueError:
                raise ValueError(f"malformed schema version in header comment: {c!r}")
    return None


# --- extended asset: write ----------------------------------------------------
def write_asset_ply(path: str, g: AssetGaussians) -> None:
    layout = schema.field_layout(g.n_basis)  # [(name, "f4"|"u1"), ...]
    dt = np.dtype([(name, "<f4" if t == "f4" else "|u1") for name, t in layout])
    out = np.empty(g.count, dtype=dt)

    out["x"], out["y"], out["z"] = g.xyz[:, 0], g.xyz[:, 1], g.xyz[:, 2]
    out["scale_0"], out["scale_1"], out["scale_2"] = g.scale[:, 0], g.scale[:, 1], g.scale[:, 2]
    for i in range(4):
        out[f"rot_{i}"] = g.rot[:, i]
    out["opacity"] = g.opacity
    out["albedo_r"], out["albedo_g"], out["albedo_b"] = g.albedo[:, 0], g.albedo[:, 1], g.albedo[:, 2]
    out["nx"], out["ny"], out["nz"] = g.normal[:, 0], g.normal[:, 1], g.normal[:, 2]
    out["rough"] = g.rough
    out["trans"] = g.trans
    out["label"] = g.label.astype(np.uint8)
    for b in range(g.n_basis):
        out[f"b{b}_r"] = g.basis[:, b, 0]
        out[f"b{b}_g"] = g.basis[:, b, 1]
        out[f"b{b}_b"] = g.basis[:, b, 2]

    header = ["ply", "format binary_little_endian 1.0", f"comment {schema.HEADER_COMMENT}",
              f"element vertex {g.count}"]
    for name, t in layout:
        header.append(f"property {_ply_prop_name(t)} {name}")
    header.append("end_header\n")
    with open(path, "wb") as f:
        f.write(("\n".join(header)).encode("ascii"))
        f.write(out.tobytes(order="C"))


# --- extended asset: read -----------------------------------------------------
def read_asset_ply(path: str) -> AssetGaussians:
    arr, names, comments = _read_structured(path)
    # provenance gate: this must be one of OUR extended assets, at OUR schema
    # version. A foreign / version-mismatched PLY must fail loudly, not load
    # silently with the wrong field semantics.
    ver = _schema_version_from_comments(comments)
    if ver is None:
        raise ValueError(
            f"{path}: not a splat_relight asset PLY "
            f"(missing '{schema.HEADER_COMMENT}' header comment)")
    if ver != schema.SCHEMA_VERSION:
        raise ValueError(
            f"{path}: schema version mismatch — file is v{ver}, "
            f"this code expects v{schema.SCHEMA_VERSION}")
    n_basis = sum(1 for nm in names if nm.startswith("b") and nm.endswith("_r") and nm[1:-2].isdigit())
    def col(*ns):
        return np.stack([arr[n] for n in ns], axis=-1).astype(np.float32)
    basis = None
    if n_basis:
        basis = np.stack(
            [np.stack([arr[f"b{b}_r"], arr[f"b{b}_g"], arr[f"b{b}_b"]], axis=-1) for b in range(n_basis)],
            axis=1,
        ).astype(np.float32)
    return AssetGaussians(
        xyz=col("x", "y", "z"),
        scale=col("scale_0", "scale_1", "scale_2"),
        rot=col("rot_0", "rot_1", "rot_2", "rot_3"),
        opacity=arr["opacity"].astype(np.float32),
        albedo=col("albedo_r", "albedo_g", "albedo_b"),
        normal=col("nx", "ny", "nz"),
        rough=arr["rough"].astype(np.float32),
        trans=arr["trans"].astype(np.float32),
        label=arr["label"].astype(np.uint8),
        basis=basis,
    )


# --- vanilla 3DGS: read -------------------------------------------------------
def read_standard_3dgs_ply(path: str) -> dict:
    """Read a vanilla 3DGS PLY. Returns dict of numpy arrays:
    xyz (N,3), f_dc (N,3), f_rest (N,K) [K=0 if absent], opacity (N,),
    scale (N,3), rot (N,4 wxyz)."""
    arr, names, _comments = _read_structured(path)
    nameset = set(names)

    # Validate the full required field set BEFORE accessing any column — otherwise
    # a missing field surfaces as a bare KeyError from `need(...)` and the helpful
    # ValueError below is unreachable.
    required = {"x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"}
    missing = required - nameset
    if missing:
        raise ValueError(f"not a standard 3DGS PLY, missing {sorted(missing)}")

    def need(*ns):
        return np.stack([arr[n] for n in ns], axis=-1).astype(np.float32)

    f_rest_names = sorted([n for n in names if n.startswith("f_rest_")],
                          key=lambda s: int(s.split("_")[-1]))
    return {
        "xyz": need("x", "y", "z"),
        "f_dc": need("f_dc_0", "f_dc_1", "f_dc_2"),
        "f_rest": (np.stack([arr[n] for n in f_rest_names], axis=-1).astype(np.float32)
                   if f_rest_names else np.zeros((arr.shape[0], 0), np.float32)),
        "opacity": arr["opacity"].astype(np.float32),
        "scale": need("scale_0", "scale_1", "scale_2"),
        "rot": need("rot_0", "rot_1", "rot_2", "rot_3"),
    }


# --- vanilla 3DGS: write ------------------------------------------------------
def write_standard_3dgs_ply(path, xyz, sh0, shN, opacity, scales, quats):
    """Write a vanilla 3DGS PLY readable by GDGS and other tools.

    Layout: x,y,z, f_dc_0..2, f_rest_0..(3*Krest-1), opacity, scale_0..2, rot_0..3.
    Uses the ORIGINAL-3DGS channel-major f_rest ordering (all R coeffs, then G,
    then B). Inputs (numpy):
      xyz (N,3); sh0 (N,1,3) or (N,3); shN (N,Krest,3) [may be empty];
      opacity (N,) [logit]; scales (N,3) [log]; quats (N,4) [w,x,y,z].
    """
    xyz = np.asarray(xyz, np.float32).reshape(-1, 3)
    n = xyz.shape[0]
    sh0 = np.asarray(sh0, np.float32).reshape(n, 3)
    shN = np.asarray(shN, np.float32).reshape(n, -1, 3) if np.size(shN) else np.zeros((n, 0, 3), np.float32)
    krest = shN.shape[1]
    opacity = np.asarray(opacity, np.float32).reshape(n)
    scales = np.asarray(scales, np.float32).reshape(n, 3)
    quats = np.asarray(quats, np.float32).reshape(n, 4)
    quats = quats / np.linalg.norm(quats, axis=1, keepdims=True)

    names = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2"]
    names += [f"f_rest_{i}" for i in range(3 * krest)]
    names += ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    dt = np.dtype([(nm, "<f4") for nm in names])
    out = np.empty(n, dt)
    out["x"], out["y"], out["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    out["f_dc_0"], out["f_dc_1"], out["f_dc_2"] = sh0[:, 0], sh0[:, 1], sh0[:, 2]
    for c in range(3):                    # channel-major: R(0..K-1), G, B
        for k in range(krest):
            out[f"f_rest_{c * krest + k}"] = shN[:, k, c]
    out["opacity"] = opacity
    out["scale_0"], out["scale_1"], out["scale_2"] = scales[:, 0], scales[:, 1], scales[:, 2]
    for i in range(4):
        out[f"rot_{i}"] = quats[:, i]

    header = ["ply", "format binary_little_endian 1.0", f"element vertex {n}"]
    header += [f"property float {nm}" for nm in names] + ["end_header\n"]
    with open(path, "wb") as f:
        f.write("\n".join(header).encode("ascii"))
        f.write(out.tobytes(order="C"))
