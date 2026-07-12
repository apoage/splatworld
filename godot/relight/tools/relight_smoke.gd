extends SceneTree
# M2a data gate (headless). Loads the extended asset through RelightPlyLoader and
# asserts the importer produced well-formed GPU + material buffers. No rendering
# (headless = dummy driver); the shading/relight proof is relight_render_gate.gd.
#   ~/godot/godot --path godot --headless --script res://relight/tools/relight_smoke.gd
#
# Overridable via env: SMOKE_ASSET, SMOKE_MIN_COUNT.

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const DEFAULT_ASSET := "res://gs_assets/pxl_144634.relightply"
const DEFAULT_MIN_COUNT := 1000000    # pxl_144634 has 2,394,584 splats

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
	var asset := _asset()
	var min_count := _min_count()

	var res: RelightGaussianResource = RelightPlyLoader.load(asset)
	if res == null:
		push_error("[relight-smoke] load returned null for %s" % asset)
		_finish(false)
		return

	var problems: Array[String] = []

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


func _finish(ok: bool) -> void:
	print("RELIGHT_SMOKE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
