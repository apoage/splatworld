extends SceneTree
# M2a render gate (real GPU, DISPLAY=:0). Proves the relight compute pass actually
# shades the GDGS color buffer. Fixed camera + fixed light seeds + fixed settle
# frames per capture (reset between captures):
#   P0 raw        -> L_raw    (mode=RAW; pass writes albedo)
#   P1 relit obl  -> L_A       assert |L_A - L_raw| > tol   (pass rewrote color)
#   P2 relit graze-> L_B
#   P3 overhead   -> L_over    assert |L_over - L_B| > tol  (relighting responds to a
#                              REAL light-direction change), AND floor >= LUMA_FLOOR
#                              (ambient prevents black shadows)
# Directional-response check compares the OVERHEAD (straight-down) vs the GRAZING
# oblique angle ON PURPOSE: the real decomposed foliage asset has near-isotropic
# normals (‖mean-normal‖≈0.2, CLAUDE.md "foliage normals are noisy"), so the
# global-mean luminance is a coarse proxy that barely moves across a SMALL arc
# (two similar oblique angles differ by <0.004). A well-separated pair (overhead
# vs grazing, ~0.05 apart here) makes the assertion measure "did the light really
# move?" instead of the proxy's insensitivity — see the DIR_* note below.
# "floor" = robust low percentile (p2) of luminance over splat-covered pixels in the
# most-shadowed config; a raw per-pixel min is dominated by AA edge outliers.
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/relight_render_gate.gd
#   RELIGHT_SHOT_DIR=/abs/dir  -> also writes one PNG per phase (eyeball only).

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const ASSET_PATH := "res://gs_assets/pxl_144634.relightply"

const BG := Color(0.15, 0.0, 0.20)     # distinct hue vs green foliage, for coverage mask
const AMBIENT := 0.2
const WRAP_POWER := 2.0
const LIGHT_COLOR := Color(1.0, 1.0, 1.0)

const SETTLE := 40                     # frames to settle before each capture
const SAMPLE_STEP := 2                 # subsample stride for the readback scan
const HIST_BINS := 256
const COVER_EPS := 0.06                # L1 color distance from BG to count as covered
const MIN_COVERED := 5000              # splats must actually render
const DIFF_TOL := 0.01                 # luminance-mean difference threshold
const DEFAULT_LUMA_FLOOR := 0.01       # ambient floor (env RELIGHT_LUMA_FLOOR overrides)

# Fixed light TRAVEL directions (world). A = oblique, B = a shallower GRAZING angle,
# SHADOW = straight DOWN (light from directly overhead). The directional-response
# assertion deliberately compares OVERHEAD (DIR_SHADOW) vs GRAZING (DIR_B) because
# those are meaningfully separated: the real decomposed asset's near-isotropic
# foliage normals make the global-mean luminance proxy insensitive to a small angle
# change (A vs B differ by <0.004 — below any sane tol), while overhead-vs-grazing
# genuinely differs (~0.05 here). The floor is evaluated on whichever relit phase is
# empirically darkest, so it is robust to the exact world-normal orientation (export
# bias + GDGS's default -180 deg Z node correction) — note DIR_SHADOW is actually the
# BRIGHTEST config for this asset (its normals favour "up"), which is why the floor
# uses the darkest phase, not this one.
const DIR_A := Vector3(-0.4, -0.6, -0.5)
const DIR_B := Vector3(-0.85, -0.2, -0.45)
const DIR_SHADOW := Vector3(0.0, -1.0, 0.0)

var _phase := 0
var _frames := 0
var _res
var _shot_dir := ""
var _measures := []

# env-SH ambient: when a sidecar loads, phases 4-5 re-render with the recovered
# ambient (set_env_sh) so we can prove sidecar-ambient != flat-fallback (checksum)
# and that the ambient floor still holds under the light-behind config with env SH.
# No sidecar -> _n_phases stays 4 and the gate is the exact M2a flat-only gate.
var _env_coeffs := PackedFloat32Array()
var _has_env := false
var _n_phases := 4


func _luma_floor() -> float:
	var v := OS.get_environment("RELIGHT_LUMA_FLOOR")
	return float(v) if v.is_valid_float() else DEFAULT_LUMA_FLOOR


func _initialize() -> void:
	_shot_dir = _resolve_shot_dir()
	var root := get_root()
	root.size = Vector2i(1280, 960)

	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = BG
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.3, 0.3, 0.3)
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	root.add_child(we)

	_res = RelightPlyLoader.load(ASSET_PATH)
	if _res == null:
		push_error("[relight-gate] load failed: %s" % ASSET_PATH)
		_finish(false)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)

	_env_coeffs = RelightEnvSH.load_coeffs(ASSET_PATH)
	_has_env = _env_coeffs.size() == RelightEnvSH.N_COEFFS * 3
	_n_phases = 6 if _has_env else 4
	print("[relight-gate] env-SH sidecar: %s (%d coeffs) -> %d phases" % [
		("LOADED" if _has_env else "absent, flat-only"), _env_coeffs.size(), _n_phases])

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)

	var ab: AABB = _res.aabb
	var center := ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.6, 1.0)
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(center + Vector3(radius, radius * 0.4, radius), center, Vector3.UP)
	cam.current = true

	print("[relight-gate] splats=%d aabb=%s" % [_res.point_count, ab])


# Phases 0-3 are the M2a flat-ambient gate (env cleared -> shader uses pc.light_color.w).
# Phases 4-5 (only when a sidecar loaded) re-render with the recovered env-SH ambient.
func _apply_phase() -> void:
	match _phase:
		0:
			RelightPass.clear_env_sh()
			RelightPass.set_light(DIR_A.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RAW, false)
		1:
			RelightPass.clear_env_sh()
			RelightPass.set_light(DIR_A.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
		2:
			RelightPass.clear_env_sh()
			RelightPass.set_light(DIR_B.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
		3:
			RelightPass.clear_env_sh()
			RelightPass.set_light(DIR_SHADOW.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
		4:
			# relit A, but with the recovered env-SH ambient (vs flat phase 1).
			RelightPass.set_env_sh(_env_coeffs)
			RelightPass.set_light(DIR_A.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
		5:
			# light straight down, env-SH ambient -> ambient floor must still hold.
			RelightPass.set_env_sh(_env_coeffs)
			RelightPass.set_light(DIR_SHADOW.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)


func _process(_delta: float) -> bool:
	if _res == null:
		return true
	if _frames == 0:
		_apply_phase() # set light/env once per phase (avoids per-frame env churn)
	_frames += 1
	if _frames < SETTLE:
		return false

	var img := get_root().get_texture().get_image()
	if img == null or img.get_width() == 0:
		push_error("[relight-gate] empty viewport image (phase %d)" % _phase)
		_finish(false)
		return true

	var m := _measure(img)
	_measures.append(m)
	print("[relight-gate] phase %d: covered=%d mean=%.5f min=%.5f p2=%.5f" % [
		_phase, m["covered"], m["mean"], m["min"], m["p2"]])
	if not _shot_dir.is_empty():
		img.save_png(_shot_dir.path_join("relight_gate_p%d.png" % _phase))

	_phase += 1
	_frames = 0
	if _phase >= _n_phases:
		return _evaluate()
	return false


func _measure(img: Image) -> Dictionary:
	img.convert(Image.FORMAT_RGBAF)
	var w := img.get_width()
	var h := img.get_height()
	var covered := 0
	var lum_sum := 0.0
	var lum_min := INF
	var hist := PackedInt32Array()
	hist.resize(HIST_BINS)
	hist.fill(0)

	var x := 0
	while x < w:
		var y := 0
		while y < h:
			var c := img.get_pixel(x, y)
			var d := absf(c.r - BG.r) + absf(c.g - BG.g) + absf(c.b - BG.b)
			if d > COVER_EPS:
				var l := 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
				covered += 1
				lum_sum += l
				lum_min = minf(lum_min, l)
				var bin := clampi(int(l * HIST_BINS), 0, HIST_BINS - 1)
				hist[bin] += 1
			y += SAMPLE_STEP
		x += SAMPLE_STEP

	var mean := lum_sum / float(maxi(covered, 1))
	var p2 := 0.0
	var target := int(covered * 0.02)
	var acc := 0
	for b in HIST_BINS:
		acc += hist[b]
		if acc >= target:
			p2 = float(b) / float(HIST_BINS)
			break
	return {
		"covered": covered,
		"mean": mean,
		"min": (0.0 if lum_min == INF else lum_min),
		"p2": p2,
	}


func _evaluate() -> bool:
	var floor_thr := _luma_floor()
	var l_raw: float = _measures[0]["mean"]
	var l_a: float = _measures[1]["mean"]     # oblique
	var l_b: float = _measures[2]["mean"]     # grazing
	var l_over: float = _measures[3]["mean"]  # overhead (straight-down light)

	# Most-shadowed config = darkest relit phase (robust to world-normal orientation).
	var darkest := 1
	for i in [2, 3]:
		if float(_measures[i]["mean"]) < float(_measures[darkest]["mean"]):
			darkest = i
	var shadow_floor: float = _measures[darkest]["p2"]

	var problems: Array[String] = []
	for i in _n_phases:
		if int(_measures[i]["covered"]) < MIN_COVERED:
			problems.append("phase %d covered=%d < %d (splats did not render)" % [i, int(_measures[i]["covered"]), MIN_COVERED])

	if absf(l_a - l_raw) <= DIFF_TOL:
		problems.append("raw≈relit: |L_A-L_raw|=%.5f <= %.5f (pass did not rewrite color)" % [absf(l_a - l_raw), DIFF_TOL])
	# Directional response over a well-separated pair (overhead vs grazing). A small
	# arc (A vs B) is not usable here: near-isotropic foliage normals make the
	# global-mean proxy insensitive to it (see the DIR_* / header notes).
	var dir_delta := absf(l_over - l_b)
	if dir_delta <= DIFF_TOL:
		problems.append("overhead≈grazing: |L_over-L_B|=%.5f <= %.5f (relighting ignores light direction)" % [dir_delta, DIFF_TOL])
	if shadow_floor < floor_thr:
		problems.append("shadow floor p2=%.5f < %.5f (black shadows)" % [shadow_floor, floor_thr])

	print("[relight-gate] L_raw=%.5f L_A=%.5f L_B=%.5f L_over=%.5f darkest=phase%d(mean=%.5f) | |A-raw|=%.5f |over-B|=%.5f shadow_p2=%.5f floor=%.5f" % [
		l_raw, l_a, l_b, l_over, darkest, float(_measures[darkest]["mean"]), absf(l_a - l_raw), dir_delta, shadow_floor, floor_thr])

	# env-SH ambient vs flat-fallback proof (only when a sidecar loaded).
	if _has_env:
		var l_a_env: float = _measures[4]["mean"]   # relit A, recovered env-SH ambient
		var env_delta := absf(l_a_env - l_a)         # l_a == relit A, flat ambient (phase 1)
		var env_shadow_floor: float = _measures[5]["p2"]
		if env_delta <= DIFF_TOL:
			problems.append("env≈flat: |L_A_env-L_A_flat|=%.5f <= %.5f (sidecar ambient had no effect)" % [env_delta, DIFF_TOL])
		if env_shadow_floor < floor_thr:
			problems.append("env shadow floor p2=%.5f < %.5f (env ambient black shadows)" % [env_shadow_floor, floor_thr])
		print("[relight-gate] ENV-SH: L_A_flat=%.5f L_A_env=%.5f |env-flat|=%.5f (>%.5f) | env_shadow_p2=%.5f floor=%.5f" % [
			l_a, l_a_env, env_delta, DIFF_TOL, env_shadow_floor, floor_thr])

	if not problems.is_empty():
		for p in problems:
			push_error("[relight-gate] FAIL: %s" % p)
	_finish(problems.is_empty())
	return true


func _resolve_shot_dir() -> String:
	var d := OS.get_environment("RELIGHT_SHOT_DIR")
	if d.is_empty():
		var ua := OS.get_cmdline_user_args()
		if ua.size() > 0:
			d = ua[0]
	if d.is_empty():
		return ""
	var abs_dir := d
	if d.begins_with("res://") or d.begins_with("user://"):
		abs_dir = ProjectSettings.globalize_path(d)
	elif not d.is_absolute_path():
		abs_dir = ProjectSettings.globalize_path("res://".path_join(d))
	DirAccess.make_dir_recursive_absolute(abs_dir)
	return abs_dir


func _finish(ok: bool) -> void:
	print("RELIGHT_RENDER_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
