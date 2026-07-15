extends SceneTree
# M2a data gate (headless). Loads the extended asset through RelightPlyLoader and
# asserts the importer produced well-formed GPU + material buffers. No rendering
# (headless = dummy driver); the shading/relight proof is relight_render_gate.gd.
#   ~/godot/godot --path godot --headless --script res://relight/tools/relight_smoke.gd
#
# Overridable via env: SMOKE_ASSET, SMOKE_MIN_COUNT.

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")
const RelightPass = preload("res://relight/relight_pass.gd")

const DEFAULT_ASSET := "res://gs_assets/pxl_144634.relightply"
const DEFAULT_MIN_COUNT := 1000000    # pxl_144634 has 2,394,584 splats

# Real degree-2 SH basis (mirrors relight.glsl / core.sh_env; comment-locked by the
# pytest data gate). Used by the env-SH DC-normalization check below to evaluate
# ambient_sh(N) on the CPU. Rec.709 luma weights match relight.glsl / set_env_sh.
const SH_C0 := 0.28209479177387814
const SH_C1 := 0.4886025119029199
const SH_C2a := 1.0925484305920792
const SH_C2b := 0.31539156525252005
const SH_C2c := 0.5462742152960396
const LUMA_R := 0.2126
const LUMA_G := 0.7152
const LUMA_B := 0.0722
const NORM_TOL := 1e-4                # unit sphere-mean luma tolerance

const FLOATS_PER_SPLAT := 60          # GDGS std430 struct
const BYTES_PER_SPLAT := 240
const MATERIAL_BYTES := 32            # 2 x vec4
const SCHEMA_VERSION := 1


func _asset() -> String:
	var a := OS.get_environment("SMOKE_ASSET")
	return a if not a.is_empty() else DEFAULT_ASSET


func _min_count() -> int:
	var m := OS.get_environment("SMOKE_MIN_COUNT")
	return int(m) if m.is_valid_int() else DEFAULT_MIN_COUNT


func _initialize() -> void:
	var problems: Array[String] = []

	# relit-energy data gate: set_env_sh must DC-normalize the env so ambient_sh(N)
	# has UNIT sphere-mean luma. Pure-CPU; runs first (independent of the asset).
	_check_env_sh_norm(problems)

	var asset := _asset()
	var min_count := _min_count()

	var res: RelightGaussianResource = RelightPlyLoader.load(asset)
	if res == null:
		push_error("[relight-smoke] load returned null for %s" % asset)
		_finish(false)
		return

	var is_gs := res is GaussianResource
	if not is_gs:
		problems.append("not a GaussianResource")
	if res.relight_schema_version != SCHEMA_VERSION:
		problems.append("schema_version=%d (want %d)" % [res.relight_schema_version, SCHEMA_VERSION])

	var count: int = res.point_count
	print("[relight-smoke] point_count=%d  is_gs=%s  schema=%d" % [count, is_gs, res.relight_schema_version])
	if count <= min_count:
		problems.append("point_count %d <= min %d" % [count, min_count])

	# Buffer sizes.
	if res.point_data_byte.size() != count * BYTES_PER_SPLAT:
		problems.append("point_data_byte=%d (want %d)" % [res.point_data_byte.size(), count * BYTES_PER_SPLAT])
	if res.point_data_float.size() != count * FLOATS_PER_SPLAT:
		problems.append("point_data_float=%d (want %d)" % [res.point_data_float.size(), count * FLOATS_PER_SPLAT])
	if res.attr_data_byte.size() != count * MATERIAL_BYTES:
		problems.append("attr_data_byte=%d (want %d)" % [res.attr_data_byte.size(), count * MATERIAL_BYTES])
	if res.xyz.size() != count:
		problems.append("xyz=%d (want %d)" % [res.xyz.size(), count])
	if res.albedo_rgb.size() != count * 3:
		problems.append("albedo_rgb=%d (want %d)" % [res.albedo_rgb.size(), count * 3])
	if res.normal_xyz.size() != count * 3:
		problems.append("normal_xyz=%d (want %d)" % [res.normal_xyz.size(), count * 3])
	if res.rough.size() != count:
		problems.append("rough=%d (want %d)" % [res.rough.size(), count])
	if res.trans.size() != count:
		problems.append("trans=%d (want %d)" % [res.trans.size(), count])
	if res.label.size() != count:
		problems.append("label=%d (want %d)" % [res.label.size(), count])

	# Ranges + finiteness over every splat (single pass).
	var albedo_min := INF
	var albedo_max := -INF
	var rough_min := INF
	var rough_max := -INF
	var trans_min := INF
	var trans_max := -INF
	var normal_err_max := 0.0
	var label_max := 0
	var bad := 0

	if problems.is_empty():
		var alb := res.albedo_rgb
		var nrm := res.normal_xyz
		var rgh := res.rough
		var trn := res.trans
		var lbl := res.label
		for i in count:
			var a3 := i * 3
			var ar := alb[a3 + 0]
			var ag := alb[a3 + 1]
			var ab := alb[a3 + 2]
			var nx := nrm[a3 + 0]
			var ny := nrm[a3 + 1]
			var nz := nrm[a3 + 2]
			var ro := rgh[i]
			var tr := trn[i]
			if not (is_finite(ar) and is_finite(ag) and is_finite(ab) \
					and is_finite(nx) and is_finite(ny) and is_finite(nz) \
					and is_finite(ro) and is_finite(tr)):
				bad += 1
				continue
			albedo_min = minf(albedo_min, minf(ar, minf(ag, ab)))
			albedo_max = maxf(albedo_max, maxf(ar, maxf(ag, ab)))
			rough_min = minf(rough_min, ro)
			rough_max = maxf(rough_max, ro)
			trans_min = minf(trans_min, tr)
			trans_max = maxf(trans_max, tr)
			var nlen := sqrt(nx * nx + ny * ny + nz * nz)
			normal_err_max = maxf(normal_err_max, absf(nlen - 1.0))
			var l := int(lbl[i])
			label_max = maxi(label_max, l)
			if l > 3:
				bad += 1

		print("[relight-smoke] albedo=[%.4f,%.4f]  rough=[%.4f,%.4f]  trans=[%.4f,%.4f]" % [
			albedo_min, albedo_max, rough_min, rough_max, trans_min, trans_max])
		print("[relight-smoke] normal_unit_err_max=%.9f  label_max=%d  nonfinite/bad_label=%d" % [
			normal_err_max, label_max, bad])

		# albedo bound is GENEROUS [0,4]: pre-decompose placeholder albedo is baked
		# SH-DC appearance (peaks ~1.82), not reflectance (schema.py FIELD_RANGES).
		if albedo_min < 0.0 or albedo_max > 4.0:
			problems.append("albedo out of [0,4]")
		if rough_min < 0.0 or rough_max > 1.0:
			problems.append("rough out of [0,1]")
		if trans_min < 0.0 or trans_max > 1.0:
			problems.append("trans out of [0,1]")
		if normal_err_max > 1e-3:
			problems.append("normals not unit (err %.3e)" % normal_err_max)
		if label_max > 3:
			problems.append("label > 3")
		if bad > 0:
			problems.append("%d non-finite / bad-label splats" % bad)

	# Deterministic checksum over first / mid / last splat (material + geometry).
	var checksum := 0.0
	if problems.is_empty() and count > 0:
		for idx in [0, int(count / 2), count - 1]:
			var si := int(idx)
			var a3 := si * 3
			checksum += res.albedo_rgb[a3] + res.albedo_rgb[a3 + 1] + res.albedo_rgb[a3 + 2]
			checksum += res.normal_xyz[a3] + res.normal_xyz[a3 + 1] + res.normal_xyz[a3 + 2]
			checksum += res.rough[si] + res.trans[si] + float(res.label[si])
			checksum += res.point_data_float[si * FLOATS_PER_SPLAT] # centered pos.x
	print("[relight-smoke] checksum=%.6f" % checksum)

	# --- ambient env-SH sidecar (env-runtime data gate) ---------------------
	# A sidecar next to the asset MUST parse to 9x3 finite coeffs; its ABSENCE is
	# a valid flat-ambient fallback (placeholder assets), not a failure. The
	# runtime shader evaluates ambient_sh(N) from exactly these coeffs — the
	# constant/basis-order match against core.sh_env is checked by the pytest
	# data gate (precompute/tests/test_godot_env_sh_constants.py).
	if OS.get_environment(RelightEnvSH.DISABLE_ENV_VAR) == "1":
		print("[relight-smoke] %s=1 -> env-SH sidecar check skipped" % RelightEnvSH.DISABLE_ENV_VAR)
	else:
		var sidecar := RelightEnvSH.sidecar_path(asset)
		if FileAccess.file_exists(sidecar):
			var coeffs := RelightEnvSH.load_coeffs(asset)
			var want := RelightEnvSH.N_COEFFS * 3
			if coeffs.size() != want:
				problems.append("env-SH sidecar %s present but did not parse to %d finite coeffs" % [sidecar, want])
			else:
				print("[relight-smoke] env-SH sidecar OK: %d coeffs finite, DC=(%.4f,%.4f,%.4f)" % [
					coeffs.size(), coeffs[0], coeffs[1], coeffs[2]])
		else:
			print("[relight-smoke] no env-SH sidecar (%s) -> flat ambient fallback (OK)" % sidecar)

	if not problems.is_empty():
		for p in problems:
			push_error("[relight-smoke] FAIL: %s" % p)
	_finish(problems.is_empty())


# --- relit-energy: env-SH DC-normalization gate -----------------------------
# set_env_sh must scale the recovered env so ambient_sh(N) has UNIT sphere-mean luma
# (the shader then multiplies by the ambient slider, matching the flat fallback's
# energy budget instead of applying the full capture illumination at weight 1.0 —
# the "bloom with extra saturation" bug). Checks the coeffs AS BOUND
# (RelightPass._env_padded -> exactly the bytes shipped to the GPU) for a
# representative synthetic env AND the asset's real sidecar when present.
func _check_env_sh_norm(problems: Array[String]) -> void:
	# representative env: bright warm-ish DC + nonzero l=1/l=2 directional lobes.
	var rep := PackedFloat32Array([
		0.80, 0.70, 0.50,
		0.20, 0.15, 0.10,
		-0.10, -0.05, 0.02,
		0.05, 0.10, 0.15,
		0.03, 0.01, -0.03,
		-0.02, 0.02, 0.01,
		-0.04, 0.01, 0.02,
		0.01, -0.02, 0.00,
		0.02, 0.00, -0.01,
	])
	_assert_unit_sphere_mean(rep, "synthetic", problems)

	# the asset's real sidecar too (if present) -> proves real capture coeffs normalize.
	var side := RelightEnvSH.load_coeffs(_asset())
	if side.size() == RelightEnvSH.N_COEFFS * 3:
		_assert_unit_sphere_mean(side, "sidecar", problems)
	else:
		print("[relight-smoke] env-SH norm: no usable sidecar coeffs -> synthetic-only")


# Sphere-mean of ambient_sh is computed EXACTLY (not sampled) via the 6-point
# octahedral quadrature: averaging any degree-<=2 polynomial over the +-x/+-y/+-z
# axes equals its spherical average, so every l=1,2 SH band cancels and only the DC
# (SH_C0*c00) survives — the exact quantity set_env_sh normalizes to unit luma.
func _assert_unit_sphere_mean(coeffs_rgb: PackedFloat32Array, tag: String, problems: Array[String]) -> void:
	RelightPass.set_env_sh(coeffs_rgb)
	var bound := RelightPass._env_padded()
	if bound.size() != RelightPass.ENV_SH_BYTES:
		problems.append("env-SH norm[%s]: bound buffer %d bytes (want %d)" % [tag, bound.size(), RelightPass.ENV_SH_BYTES])
		RelightPass.clear_env_sh()
		return
	var c := PackedFloat32Array()
	c.resize(RelightPass.ENV_SH_COEFFS * 3)
	for i in RelightPass.ENV_SH_COEFFS:
		var o := i * 16
		c[i * 3 + 0] = bound.decode_float(o + 0)
		c[i * 3 + 1] = bound.decode_float(o + 4)
		c[i * 3 + 2] = bound.decode_float(o + 8)
	var axes := [
		Vector3(1, 0, 0), Vector3(-1, 0, 0),
		Vector3(0, 1, 0), Vector3(0, -1, 0),
		Vector3(0, 0, 1), Vector3(0, 0, -1),
	]
	var mean := Vector3.ZERO
	for a in axes:
		mean += _eval_ambient_sh(c, a)
	mean /= float(axes.size())
	var luma := LUMA_R * mean.x + LUMA_G * mean.y + LUMA_B * mean.z
	# analytic cross-check: spherical mean == SH_C0 * bound DC (independent of quadrature).
	var dc_luma := SH_C0 * (LUMA_R * c[0] + LUMA_G * c[1] + LUMA_B * c[2])
	print("[relight-smoke] env-SH norm[%s]: sphere-mean rgb=(%.5f,%.5f,%.5f) luma=%.6f (analytic SH_C0*DC luma=%.6f)" % [
		tag, mean.x, mean.y, mean.z, luma, dc_luma])
	if absf(luma - 1.0) > NORM_TOL:
		problems.append("env-SH norm[%s]: sphere-mean luma=%.6f != 1.0 (set_env_sh DC-normalization broken)" % [tag, luma])
	if absf(luma - dc_luma) > NORM_TOL:
		problems.append("env-SH norm[%s]: numeric mean luma=%.6f != analytic SH_C0*DC luma=%.6f (basis/quadrature drift)" % [tag, luma, dc_luma])
	RelightPass.clear_env_sh()


# GDScript mirror of relight.glsl ambient_sh(N): sum_lm c_lm * Y_lm(N).
func _eval_ambient_sh(c: PackedFloat32Array, n: Vector3) -> Vector3:
	var x := n.x
	var y := n.y
	var z := n.z
	var col := _coeff(c, 0) * SH_C0
	col += _coeff(c, 1) * (SH_C1 * y)
	col += _coeff(c, 2) * (SH_C1 * z)
	col += _coeff(c, 3) * (SH_C1 * x)
	col += _coeff(c, 4) * (SH_C2a * x * y)
	col += _coeff(c, 5) * (SH_C2a * y * z)
	col += _coeff(c, 6) * (SH_C2b * (3.0 * z * z - 1.0))
	col += _coeff(c, 7) * (SH_C2a * x * z)
	col += _coeff(c, 8) * (SH_C2c * (x * x - y * y))
	return col


func _coeff(c: PackedFloat32Array, i: int) -> Vector3:
	return Vector3(c[i * 3 + 0], c[i * 3 + 1], c[i * 3 + 2])


func _finish(ok: bool) -> void:
	print("RELIGHT_SMOKE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
