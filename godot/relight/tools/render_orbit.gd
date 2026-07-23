extends SceneTree
# relight-orbit-video render tool (real GPU, DISPLAY=:0, NO --headless).
# Renders a single-take demo of the M2 relight pass on the REAL phase-D decomposed
# asset (pxl_144634) with the recovered env-SH ambient:
#   frames 0..RAW_FRAMES-1   -> MODE_RAW   (baked appearance, light-independent)
#   frames RAW_FRAMES..N-1   -> MODE_RELIT (one full 360deg directional-light orbit)
# The RAW->RELIT cut itself demonstrates that relighting is happening; the orbit
# then shows the shading respond to a moving light.
#
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/render_orbit.gd
#   RELIGHT_SHOT_DIR=/abs/dir   -> frames written there (frame_%04d.png); required in
#                                  practice (default res://shots is gitignored anyway).
#   RELIGHT_ORBIT_FRAMES=180    -> total frame count N (default 180 @ 30 fps = 6 s).
#   RELIGHT_ORBIT_RAW_FRAMES=30 -> leading RAW frames (~1 s).
#   RELIGHT_ORBIT_STD_FLOOR=... -> relit mean-luma std pass floor (default 0.003).
#   RELIGHT_NO_ENV_SH=1         -> force flat-ambient fallback (RelightEnvSH honours it).
#
# ORBIT SHAPE — why elevation sweeps, not just azimuth:
# the real decomposed foliage has near-isotropic normals (CLAUDE.md "foliage normals
# are noisy"), so the global-mean luminance barely moves as the light AZIMUTH changes
# at fixed elevation (the render gate measured two oblique azimuths <0.004 apart) but
# moves ~0.05 between OVERHEAD and GRAZING elevation. A pure azimuth orbit would thus
# read as a near-static video. So the light does one full 360deg azimuth turn WHILE its
# elevation rises grazing->overhead->grazing once (staying above the horizon). Azimuth
# still completes exactly one loop; the elevation sweep is what makes the relighting
# visibly respond (this is the data behind DECISIONS D5 — see the ORBIT_SUMMARY line).

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const ASSET_PATH := "res://gs_assets/pxl_144634.vply"

const RES := Vector2i(1280, 720)       # 16:9, even dims for yuv420p h264
const BG := Color(0.06, 0.07, 0.09)    # dark neutral; distinct enough for a coverage mask
const AMBIENT := 0.2                    # flat-ambient fallback (only if no env-SH sidecar)
const WRAP_POWER := 2.0
const LIGHT_COLOR := Color(1.0, 1.0, 1.0)

const DEFAULT_N := 180                  # total frames
const DEFAULT_RAW := 30                 # leading RAW frames (~1 s @ 30 fps)
const SETTLE_INITIAL := 40              # warm-up frames before the first capture
const SETTLE_PER_FRAME := 3             # render frames per light change (kills readback lag)

const SAMPLE_STEP := 6                  # subsample stride for the per-frame luma scan
const COVER_EPS := 0.05                 # L1 color distance from BG to count as covered
const DIFF_TOL := 0.01                  # raw->relit mean-luma cut-delta (informational)
const CUT_MAD_FLOOR := 0.02             # raw->relit per-pixel MAD pass floor (spatial change)
const DEFAULT_STD_FLOOR := 0.003        # relit mean-luma std pass floor

# Elevation sweep of the light-FROM direction (degrees). Range = MID +/- AMP.
const EL_MID := 45.0
const EL_AMP := 35.0                    # -> grazing 10deg .. near-overhead 80deg

var _n := DEFAULT_N
var _raw := DEFAULT_RAW
var _std_floor := DEFAULT_STD_FLOOR

var _res
var _shot_dir := ""
var _has_env := false
var _env_coeffs := PackedFloat32Array()

var _idx := -1
var _settle := 0
var _warmed := false

var _mean_cov := PackedFloat32Array()   # per-frame covered-pixel mean luma
var _mean_all := PackedFloat32Array()   # per-frame whole-frame mean luma
var _cover := PackedInt32Array()        # per-frame covered sample count

# raw->relit cut: cache the LAST raw frame's per-sample luma + coverage so the first
# relit frame can be diffed against it per pixel (a spatial "did the frame change"
# measure; the global mean can coincide across a flat-albedo vs shaded pair).
var _cut_ref_luma := PackedFloat32Array()
var _cut_ref_cov := PackedByteArray()
var _cut_mad := -1.0                     # mean |dL| over pixels covered in the last raw frame


func _envi(name: String, dflt: int) -> int:
	var v := OS.get_environment(name)
	return int(v) if v.is_valid_int() else dflt


func _envf(name: String, dflt: float) -> float:
	var v := OS.get_environment(name)
	return float(v) if v.is_valid_float() else dflt


func _initialize() -> void:
	_n = maxi(_envi("RELIGHT_ORBIT_FRAMES", DEFAULT_N), 2)
	_raw = clampi(_envi("RELIGHT_ORBIT_RAW_FRAMES", DEFAULT_RAW), 1, _n - 1)
	_std_floor = _envf("RELIGHT_ORBIT_STD_FLOOR", DEFAULT_STD_FLOOR)
	_shot_dir = _resolve_shot_dir()
	if _shot_dir.is_empty():
		push_error("[orbit] no RELIGHT_SHOT_DIR / output dir given")
		_finish(false)
		return

	var root := get_root()
	root.size = RES

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
		push_error("[orbit] load failed: %s" % ASSET_PATH)
		_finish(false)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)

	# env-SH ambient (task: USE it, note fallback if absent). Set ONCE: RAW frames
	# ignore ambient in-shader, RELIT frames consume it -> no per-frame env churn.
	_env_coeffs = RelightEnvSH.load_coeffs(ASSET_PATH)
	_has_env = _env_coeffs.size() == RelightEnvSH.N_COEFFS * 3
	if _has_env:
		RelightPass.set_env_sh(_env_coeffs)
	else:
		RelightPass.clear_env_sh()
	print("[orbit] env-SH ambient: %s" % ("env-SH sidecar" if _has_env else "FLAT fallback (no/invalid sidecar)"))

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)
	gs.transform = Transform3D.IDENTITY   # D3 rule: suppress GDGS's conditional -180deg Z flip on our
	                                      # already-Godot-convention .vply (else grounded assets orbit upside down)

	var ab: AABB = _res.aabb
	var center := ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.7, 1.0)
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(center + Vector3(radius, radius * 0.45, radius), center, Vector3.UP)
	cam.current = true

	print("[orbit] splats=%d aabb=%s N=%d raw=%d relit=%d out=%s" % [
		_res.point_count, ab, _n, _raw, _n - _raw, _shot_dir])


# Light-TRAVEL direction (world) for frame i. RAW frames get a fixed placeholder
# (the shader ignores it). RELIT frames orbit: azimuth completes one 360deg turn while
# elevation rises grazing->overhead->grazing once (see header note).
func _travel_dir(i: int) -> Vector3:
	if i < _raw:
		return Vector3(0.0, -1.0, 0.0)
	var t := float(i - _raw) / float(_n - _raw)       # 0 .. just under 1 over the relit run
	var az := TAU * t
	var el := deg_to_rad(EL_MID) - deg_to_rad(EL_AMP) * cos(TAU * t)  # t=0 -> EL_MID-EL_AMP (grazing)
	var from := Vector3(cos(el) * cos(az), sin(el), cos(el) * sin(az))  # where light comes FROM
	return -from                                       # travel dir = toward the scene


func _apply_frame(i: int) -> void:
	var mode: int = RelightPass.MODE_RAW if i < _raw else RelightPass.MODE_RELIT
	RelightPass.set_light(_travel_dir(i).normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, mode, false)


func _process(_delta: float) -> bool:
	if _res == null:
		return true

	if not _warmed:
		if _idx == -1:
			_idx = 0
			_apply_frame(0)
		_settle += 1
		if _settle < SETTLE_INITIAL:
			return false
		_warmed = true
		_settle = 0
	else:
		_settle += 1
		if _settle < SETTLE_PER_FRAME:
			return false
		_settle = 0

	var img := get_root().get_texture().get_image()
	if img == null or img.get_width() == 0:
		push_error("[orbit] empty viewport image (frame %d) -- did you forget DISPLAY=:0 / pass --headless?" % _idx)
		_finish(false)
		return true

	var m := _measure(img)
	_mean_cov.append(m["mean_cov"])
	_mean_all.append(m["mean_all"])
	_cover.append(int(m["covered"]))

	# Cache the last raw frame; diff the first relit frame against it per pixel.
	if _idx == _raw - 1:
		_cut_ref_luma = m["luma"]
		_cut_ref_cov = m["cov"]
	elif _idx == _raw and _cut_ref_luma.size() == (m["luma"] as PackedFloat32Array).size():
		var rel: PackedFloat32Array = m["luma"]
		var acc := 0.0
		var n := 0
		for k in _cut_ref_cov.size():
			if _cut_ref_cov[k] != 0:
				acc += absf(rel[k] - _cut_ref_luma[k])
				n += 1
		_cut_mad = acc / float(maxi(n, 1))

	var fpath := _shot_dir.path_join("frame_%04d.png" % _idx)
	var err := img.save_png(fpath)
	if err != OK or not FileAccess.file_exists(fpath):
		push_error("[orbit] save_png FAILED err=%d -> %s" % [err, fpath])
		_finish(false)
		return true

	print("[orbit] frame %04d %s covered=%d mean_cov=%.5f mean_all=%.5f" % [
		_idx, ("RAW" if _idx < _raw else "RELIT"), int(m["covered"]), m["mean_cov"], m["mean_all"]])

	_idx += 1
	if _idx >= _n:
		return _summarize()
	_apply_frame(_idx)
	return false


func _measure(img: Image) -> Dictionary:
	img.convert(Image.FORMAT_RGBAF)
	var w := img.get_width()
	var h := img.get_height()
	var covered := 0
	var samples := 0
	var lum_cov := 0.0
	var lum_all := 0.0
	var luma := PackedFloat32Array()
	var cov := PackedByteArray()
	var x := 0
	while x < w:
		var y := 0
		while y < h:
			var c := img.get_pixel(x, y)
			var l := 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
			lum_all += l
			samples += 1
			luma.append(l)
			var d := absf(c.r - BG.r) + absf(c.g - BG.g) + absf(c.b - BG.b)
			if d > COVER_EPS:
				covered += 1
				lum_cov += l
				cov.append(1)
			else:
				cov.append(0)
			y += SAMPLE_STEP
		x += SAMPLE_STEP
	return {
		"covered": covered,
		"mean_cov": lum_cov / float(maxi(covered, 1)),
		"mean_all": lum_all / float(maxi(samples, 1)),
		"luma": luma,
		"cov": cov,
	}


func _std(vals: PackedFloat32Array, lo: int, hi: int) -> Dictionary:
	# population std + min/max over vals[lo..hi).
	var n := hi - lo
	if n <= 0:
		return {"std": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
	var s := 0.0
	var vmin := INF
	var vmax := -INF
	for i in range(lo, hi):
		var v := vals[i]
		s += v
		vmin = minf(vmin, v)
		vmax = maxf(vmax, v)
	var mean := s / float(n)
	var acc := 0.0
	for i in range(lo, hi):
		acc += (vals[i] - mean) * (vals[i] - mean)
	return {"std": sqrt(acc / float(n)), "min": vmin, "max": vmax, "mean": mean}


func _summarize() -> bool:
	var relit := _std(_mean_cov, _raw, _n)
	var relit_all := _std(_mean_all, _raw, _n)
	var cut_delta_cov := absf(_mean_cov[_raw - 1] - _mean_cov[_raw])
	var cut_delta_all := absf(_mean_all[_raw - 1] - _mean_all[_raw])

	var min_cover := 1 << 30
	for c in _cover:
		min_cover = mini(min_cover, c)

	print("[orbit] ORBIT_SUMMARY frames=%d raw=%d relit=%d env_sh=%s" % [
		_n, _raw, _n - _raw, ("yes" if _has_env else "flat")])
	print("[orbit] ORBIT_SUMMARY relit_mean_cov=%.5f relit_std_cov=%.5f relit_min_cov=%.5f relit_max_cov=%.5f" % [
		relit["mean"], relit["std"], relit["min"], relit["max"]])
	print("[orbit] ORBIT_SUMMARY relit_std_all=%.5f relit_min_all=%.5f relit_max_all=%.5f" % [
		relit_all["std"], relit_all["min"], relit_all["max"]])
	print("[orbit] ORBIT_SUMMARY cut_mad=%.5f cut_delta_cov=%.5f cut_delta_all=%.5f min_covered_samples=%d std_floor=%.5f" % [
		_cut_mad, cut_delta_cov, cut_delta_all, min_cover, _std_floor])

	var ok := true
	if _mean_cov.size() != _n:
		push_error("[orbit] captured %d frames, expected %d" % [_mean_cov.size(), _n])
		ok = false
	if relit["std"] < _std_floor:
		push_error("[orbit] relit std_cov=%.5f < floor %.5f (light orbit barely changes shading -- D5 WEAK)" % [relit["std"], _std_floor])
		ok = false
	# Cut proof = per-pixel spatial change (mean luma can coincide across a flat-albedo
	# vs shaded pair, as it nearly does at the grazing orbit start).
	if _cut_mad < CUT_MAD_FLOOR:
		push_error("[orbit] raw->relit cut_mad=%.5f < %.5f (cut did not change the frame spatially)" % [_cut_mad, CUT_MAD_FLOOR])
		ok = false
	if min_cover <= 0:
		push_error("[orbit] a frame had 0 covered samples (splats did not render)")
		ok = false

	_finish(ok)
	return true


func _resolve_shot_dir() -> String:
	var d := OS.get_environment("RELIGHT_SHOT_DIR")
	if d.is_empty():
		var ua := OS.get_cmdline_user_args()
		if ua.size() > 0:
			d = ua[0]
	if d.is_empty():
		d = "res://shots"   # repo-relative default (gitignored)
	var abs_dir := d
	if d.begins_with("res://") or d.begins_with("user://"):
		abs_dir = ProjectSettings.globalize_path(d)
	elif not d.is_absolute_path():
		abs_dir = ProjectSettings.globalize_path("res://".path_join(d))
	DirAccess.make_dir_recursive_absolute(abs_dir)
	return abs_dir


func _finish(ok: bool) -> void:
	print("RELIGHT_ORBIT_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
