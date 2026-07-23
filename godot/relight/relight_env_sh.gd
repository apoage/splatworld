@tool
extends RefCounted
class_name RelightEnvSH

# Reads the recovered ambient environment written by `export` as a JSON sidecar
# next to the extended asset (assets/built/<name>/asset_env_sh.json, mirrored into
# gs_assets/ as <asset-stem>_env_sh.json).
#
# The sidecar is ALREADY in the Godot post-flip frame (`frame: godot_post_flip`)
# with the Lambertian band factors folded in (c_lm = (A_l/pi)*L_lm). The runtime
# therefore evaluates ambient_sh(N) = sum_lm c_lm * Y_lm(N) and NOTHING ELSE:
#   - do NOT re-apply the COLMAP->Godot flip (export did it exactly once), and
#   - do NOT re-apply A_l/pi (already folded).
# The SH basis order / normalization used to evaluate Y_lm lives in the shader
# (relight.glsl) and is comment-locked to precompute/core/sh_env.py — the single
# source of truth. This reader only marshals the 9x3 coefficients to the GPU.
#
# Convention (documented): sidecar path = <asset path with extension stripped>
# + "_env_sh.json". e.g. res://gs_assets/pxl_144634.vply ->
# res://gs_assets/pxl_144634_env_sh.json. Mirrors the built-asset naming
# (asset.ply -> asset_env_sh.json).
#
# Any problem (missing / unreadable / bad JSON / wrong frame / wrong shape /
# non-finite) is a SOFT fallback to the flat ambient constant: returns an empty
# array and logs ONCE loudly via push_warning. Never crashes.

const N_COEFFS := 9
const EXPECTED_FRAME := "godot_post_flip"
# Set RELIGHT_NO_ENV_SH=1 to force the flat-ambient fallback (ignore any sidecar).
# Used by the render gate to toggle the sidecar off for the sidecar-vs-flat proof.
const DISABLE_ENV_VAR := "RELIGHT_NO_ENV_SH"


# Sidecar path for an asset path (whether or not the file exists).
static func sidecar_path(asset_path: String) -> String:
	return asset_path.get_basename() + "_env_sh.json"


# Returns 27 floats [c0.r,c0.g,c0.b, c1.r,c1.g,c1.b, ...] (9 coeffs x RGB), or an
# EMPTY array to signal "use flat ambient". Every failure path warns once.
static func load_coeffs(asset_path: String) -> PackedFloat32Array:
	if OS.get_environment(DISABLE_ENV_VAR) == "1":
		push_warning("[relight] %s=1 -> ignoring env-SH sidecar, flat ambient" % DISABLE_ENV_VAR)
		return PackedFloat32Array()

	var path := sidecar_path(asset_path)
	if not FileAccess.file_exists(path):
		push_warning("[relight] no env-SH sidecar at %s -> flat ambient fallback" % path)
		return PackedFloat32Array()

	var text := FileAccess.get_file_as_string(path)
	if text.is_empty():
		push_warning("[relight] env-SH sidecar %s unreadable/empty -> flat ambient fallback" % path)
		return PackedFloat32Array()

	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("[relight] env-SH sidecar %s: not a JSON object -> flat ambient fallback" % path)
		return PackedFloat32Array()

	# Refuse anything not already flipped into the Godot frame: consuming a
	# colmap_pre_flip sidecar here would silently re-introduce the flip (the #1
	# correctness trap). Missing/other frame -> flat fallback.
	var frame := String(parsed.get("frame", ""))
	if frame != EXPECTED_FRAME:
		push_warning("[relight] env-SH sidecar %s: frame='%s' (want '%s') -> flat ambient fallback (refusing to re-flip)" % [path, frame, EXPECTED_FRAME])
		return PackedFloat32Array()

	var arr: Variant = parsed.get("ambient_sh", null)
	if typeof(arr) != TYPE_ARRAY or (arr as Array).size() != N_COEFFS:
		push_warning("[relight] env-SH sidecar %s: ambient_sh not a %d-row array -> flat ambient fallback" % [path, N_COEFFS])
		return PackedFloat32Array()

	var out := PackedFloat32Array()
	out.resize(N_COEFFS * 3)
	for i in N_COEFFS:
		var row: Variant = (arr as Array)[i]
		if typeof(row) != TYPE_ARRAY or (row as Array).size() != 3:
			push_warning("[relight] env-SH sidecar %s: row %d is not an RGB triple -> flat ambient fallback" % [path, i])
			return PackedFloat32Array()
		for j in 3:
			var v := float((row as Array)[j])
			if not is_finite(v):
				push_warning("[relight] env-SH sidecar %s: non-finite coeff at [%d][%d] -> flat ambient fallback" % [path, i, j])
				return PackedFloat32Array()
			out[i * 3 + j] = v
	return out
