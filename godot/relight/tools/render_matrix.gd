extends SceneTree
# PASS — 10/10 checks (2026-07-15, dark-factory run #5). Passing gate: run on DISPLAY=:0
# (real renderer, NO --headless) and it emits godot/shots/lighting_stability/lighting_stability.json;
# every check passes with measured margin and exits 0 with `LIGHTING_STABILITY_RESULT PASS`.
# Two threshold calibrations are load-bearing and measured-then-set (not loosened to pass):
#   - raw_invariance / trans_inertness / azimuth_return compare TWO independently-rendered
#     frames; the GDGS GPU splat sort + framebuffer readback flip the draw order of ~1-4 of
#     ~1730 FOLIAGE-MASKED samples frame-to-frame (sphere excluded via the cov mask), capping
#     "identical" PSNR at a hardware noise floor (measured worst over 4 runs: raw 56.3 dB, trans
#     62.7 dB, azimuth ~58 dB; NOT reducible by more settle — verified across settle 12 and 40).
#     A REAL foliage leak shifts MANY pixels together: fault-injection confirms even a subtle ~2%
#     directional leak into the raw path reads 36 dB and a gross leak 4.5 dB. Floors sit between
#     (margin under the measured noise floor, far above a real leak): raw 50 dB, trans 55 dB,
#     azimuth 45 dB (see the PSNR-floor comment block).
#   - min_coverage is two-tier because "covered" (color distance from BG) is brightness-dependent:
#     dim relit conditions alpha-blend edge foliage toward BG (min 1301 at E=0.25) though the
#     splats DID render. RAW ignores light -> a rock-stable 1730 footprint proxy; footprint floor
#     runs on RAW, a low blank-frame floor on every condition (see MIN_COVERED / BLANK_MIN).
# No engine/convention finding surfaced: sphere_consistency exercises (n_px ~16.5k, min dot ~0.31
# > 0), so our light_dir_ws agrees in sign with the engine DirectionalLight3D.
#
# lighting-stability matrix render tool (real GPU, DISPLAY=:0, NO --headless).
# Generalizes render_orbit.gd: a FIXED camera renders a bounded condition matrix of
# the M2 relight pass on the grounded phase-D asset (pxl_144634) and emits per-check
# pass/fail into <out>/lighting_stability.json. Exits nonzero on ANY hard-assert
# failure and prints ONE greppable line: `LIGHTING_STABILITY_RESULT PASS|FAIL`.
#
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/render_matrix.gd
#   LIGHTING_OUT_DIR=/abs/dir      -> output root (default res://shots/lighting_stability,
#                                     gitignored). PNG per condition + lighting_stability.json.
#   LIGHTING_SETTLE_INITIAL=40     -> warm-up frames before the first capture.
#   LIGHTING_SETTLE_COND=12        -> render frames per condition (kills readback lag AND
#                                     doubles as a settle validator: if too low, RAW renders
#                                     differ across conditions and raw-invariance FAILS).
#   RELIGHT_NO_ENV_SH=1            -> force flat-ambient fallback (RelightEnvSH honours it).
#
# WHAT IT PROVES (Approach §2/§3 of tasks/2026-07-14-lighting-stability.md):
#   - no NaN/inf pixels anywhere;
#   - every RELIT (nominal-energy) condition mean luma in (LUMA_LO, LUMA_HI);
#   - RAW invariance: MODE_RAW writes albedo only, so the foliage region is identical
#     across ALL light conditions (energy/ambient/color/direction/env on|off);
#   - trans inertness: RELIT == RELIT+trans_on while asset trans==0 (pre-M3);
#   - azimuth 360deg return: az=0 vs az=360 (same dir) PSNR > 45 dB (no state drift);
#   - energy linearity: RELIT luma(2E)/luma(E) ~= 2 on the non-saturated band (env off,
#     ambient=0 -> color = albedo*(direct+back)*light_color scales linearly);
#   - elevation smoothness: mean-luma curve over elevation has no adjacent jump > thr;
#   - ambient floor: flat ambient=0.5 relit, darkest percentile of foliage >= floor;
#   - engine cross-model: a gray Lambert sphere lit by a DirectionalLight3D whose -Z basis
#     equals the travel_dir passed to set_light -> its bright-pixel centroid is offset from
#     the sphere center TOWARD the screen projection of -travel_dir (dot > 0). Catches a
#     sign/space error between our light_dir_ws and the engine's light model.
#
# The relight pass is UNIFORM-driven (no DirectionalLight3D); the sphere is the only
# engine-lit object and is placed ABOVE the foliage (no screen overlap) so foliage stats
# exclude the sphere's screen bbox and vice-versa (bbox is a fixed dead-zone for foliage).
#
# D3 rule (load-bearing for the sphere agreement): after add_child(gs) we set
# gs.transform = Transform3D.IDENTITY so GDGS's conditional -180deg Z correction (meant
# for raw y-down 3DGS plys, fired in _enter_tree on identity-ish nodes) does NOT flip our
# already-Godot-convention .relightply. render_orbit/relight_render_gate lack this and are
# orientation-agnostic; this tool must NOT be. (ref relight_controller.gd:43-50.)

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const ASSET_PATH := "res://gs_assets/pxl_144634.relightply"

const RES := Vector2i(1280, 720)
const BG := Color(0.06, 0.07, 0.09)     # dark neutral; distinct from foliage + gray sphere
const WRAP_POWER := 2.0

# --- mode axis: the SINGLE extension point (deliverable 5). Mode B (PRT-lite basis
# blend, CLAUDE.md M5) is NOT implemented; when it lands, add MODE_B here + its
# RelightPass mapping in _mode_of() and it flows through the whole matrix. ---
enum MVar { RAW, RELIT, RELIT_TRANS }  # + MODE_B (M5 stretch — do NOT implement now)
const MODE_VARIANTS := [MVar.RAW, MVar.RELIT, MVar.RELIT_TRANS]

# --- matrix axes (Approach §1) ---
const GRID_EL := [5.0, 30.0, 60.0, 85.0]
const GRID_AZ := [0.0, 90.0, 180.0, 270.0]
const SWEEP_ENERGY := [0.25, 0.5, 1.0, 2.0, 4.0]
const SWEEP_AMBIENT := [0.0, 0.2, 0.5]
const COLOR_WHITE := [1.0, 1.0, 1.0]
const COLOR_WARM := [1.0, 0.8, 0.6]
const COLOR_COOL := [0.6, 0.8, 1.0]

# sweep defaults: a fixed oblique light direction (non-degenerate shading)
const DEF_EL := 45.0
const DEF_AZ := 45.0
const DEF_AMBIENT := 0.2                 # flat-ambient default (grid fallback if no sidecar)

const SAMPLE_STEP := 4                   # subsample stride for the foliage luma scan
const HIST_BINS := 256
const COVER_EPS := 0.05                  # L1 color distance from BG to count as covered
const GRAY_EPS := 0.16                   # |r-g|,|g-b| < this => a gray (sphere) pixel

# --- thresholds (task item 2: measured first, floors set with margin; measured value
# is recorded beside each threshold in the JSON so a reviewer sees headroom) ---
const LUMA_LO := 0.01                    # task-fixed: no blackout
const LUMA_HI := 0.98                    # task-fixed: no blowout (nominal-energy conditions)
const NOMINAL_ENERGY_MAX := 1.0          # energies > this are DELIBERATE over-drive (linearity
                                         # stress) -> excluded from the blowout bound, reported info.
# PSNR floors for the three "two separate renders should match" checks. These compare
# two independently-rendered frames of a 2.4M-splat alpha-blended cloud; the GDGS GPU
# splat sort + framebuffer readback flip the draw order of a HANDFUL of overlapping-splat
# pixels frame-to-frame (measured: ~1-4 of ~1730 FOLIAGE-MASKED samples differ; the engine-lit
# sphere is excluded via the cov mask), which caps the "identical" PSNR at a hardware noise floor.
# That floor is NOT reducible by settling (verified: settle_cond 12 and 40 both land in the same
# band). A REAL leak (light into the raw path, or trans into the relit path) shifts MANY foliage
# pixels together: fault-injection into the raw path measured a subtle ~2% directional leak at
# 36 dB and a gross leak at 4.5 dB — far below any noise floor. Floors are set between: comfortably
# above a real leak, comfortably below the MEASURED worst (recorded in the JSON), so a clean run is
# repeatable, not a coin flip.
const AZ_RETURN_PSNR_MIN := 45.0         # task-fixed >45; measured 58-68 dB (same two-frame sort-noise phenomenon)
const RAW_PSNR_MIN := 50.0               # foliage-masked; measured worst 56.3 dB (spread 0.6); injected 2% leak=36 dB
const TRANS_PSNR_MIN := 55.0             # trans==0 -> identical math; measured worst 62.7 dB over 4 runs (few-px sort noise)
const ENERGY_RATIO_TOL := 0.15           # median luma(2E)/luma(E) within [2-tol, 2+tol]
const ENERGY_BAND_LO := 0.05             # E-pixel luma floor (avoid ratio noise near black)
const ENERGY_BAND_HI := 0.90             # 2E-pixel luma ceiling (must stay below saturation)
const ENERGY_MIN_PIX := 200              # min qualifying pixels to assert a pair
const ELEV_JUMP_MAX := 0.12              # tuned from data: max adjacent |dmean| over elevation
const AMBIENT_FLOOR := 0.015             # tuned from data: p2 at flat ambient=0.5 measured ~0.031
const AMBIENT_FLOOR_PCT := 0.02          # darkest 2% percentile
const SPHERE_DOT_MIN := 0.0              # loose: bright centroid toward -travel_dir (convention)
# min-coverage is two-tier because "covered" (color L1 distance from BG) is brightness-
# dependent: deliberately-dim relit conditions (low energy, ambient 0) alpha-blend edge
# foliage toward BG so fewer samples clear COVER_EPS (measured min 1301 at E=0.25) even
# though the splats DID render. RAW mode ignores the light (writes albedo) so its coverage
# is a rock-stable, brightness-independent footprint proxy (measured 1730 every condition).
const MIN_COVERED := 1500                # FOOTPRINT floor on brightness-stable RAW conds (raw ~1730, 230 margin)
const BLANK_MIN := 800                   # BLANK-frame floor on EVERY cond (dimmest legit=1301; a blanked frame ~0)

var _settle_initial := 24
var _settle_cond := 7

var _out_dir := ""
var _res
var _has_env := false
var _env_coeffs := PackedFloat32Array()
var _trans_max := 0.0

var _light: DirectionalLight3D
var _cam: Camera3D

# fixed sphere screen geometry (computed once)
var _sph_center_w := Vector3.ZERO
var _sph_r_w := 1.0
var _sph_sx := 0.0
var _sph_sy := 0.0
var _sph_sr := 1.0                       # screen-space bbox radius (with margin)
var _sph_ready := false                  # sphere screen geometry computed once, on first live frame

var _conds: Array = []
var _cidx := -1
var _settle := 0
var _warmed := false

var _measure_by_id := {}                 # id -> measure dict (scalars)
var _luma_by_id := {}                    # id -> PackedFloat32Array (subsampled foliage luma)
var _cov_by_id := {}                     # id -> PackedByteArray (1 = foliage sample)
var _sphere_by_id := {}                  # id -> sphere-centroid dict


func _envi(name: String, dflt: int) -> int:
	var v := OS.get_environment(name)
	return int(v) if v.is_valid_int() else dflt


func _initialize() -> void:
	_settle_initial = maxi(_envi("LIGHTING_SETTLE_INITIAL", 40), 2)
	_settle_cond = maxi(_envi("LIGHTING_SETTLE_COND", 12), 1)
	_out_dir = _resolve_out_dir()

	var root := get_root()
	root.size = RES

	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = BG
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.08, 0.08, 0.08)   # low: keep the sphere's Lambert gradient strong
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR    # linear framebuffer for energy linearity
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	root.add_child(we)

	_res = RelightPlyLoader.load(ASSET_PATH)
	if _res == null:
		push_error("[matrix] load failed: %s" % ASSET_PATH)
		_finish(false)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)

	# provenance: prove the pre-M3 trans==0 contract that makes trans-inertness meaningful.
	for t in _res.trans:
		_trans_max = maxf(_trans_max, absf(t))

	_env_coeffs = RelightEnvSH.load_coeffs(ASSET_PATH)
	_has_env = _env_coeffs.size() == RelightEnvSH.N_COEFFS * 3
	print("[matrix] env-SH ambient: %s | trans_max=%.6f" % [
		("env-SH sidecar" if _has_env else "FLAT fallback (no/invalid sidecar)"), _trans_max])

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)
	gs.transform = Transform3D.IDENTITY   # D3 rule: suppress GDGS's conditional -180deg Z flip

	var ab: AABB = _res.aabb
	var center := ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.7, 1.0)

	_cam = Camera3D.new()
	root.add_child(_cam)
	_cam.look_at_from_position(center + Vector3(radius, radius * 0.45, radius), center, Vector3.UP)
	_cam.current = true

	# gray Lambert reference sphere, placed ABOVE the foliage (no screen overlap).
	_sph_center_w = center + Vector3(0.0, radius * 0.85, 0.0)
	_sph_r_w = radius * 0.22
	var mesh := SphereMesh.new()
	mesh.radius = _sph_r_w
	mesh.height = _sph_r_w * 2.0
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.6, 0.6, 0.6)
	mat.roughness = 1.0
	mat.metallic = 0.0
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = mat
	mi.position = _sph_center_w
	root.add_child(mi)

	# one DirectionalLight3D — the ONLY engine-lit source (relight pass ignores it).
	_light = DirectionalLight3D.new()
	_light.light_energy = 1.0
	_light.light_color = Color(1.0, 1.0, 1.0)
	root.add_child(_light)

	# sphere screen geometry (camera + sphere fixed for the whole matrix) is computed
	# LAZILY on the first live frame in _process: Camera3D.unproject_position needs the
	# viewport to have rendered at least once, which has NOT happened yet in _initialize
	# ("Camera is not inside scene"). See _compute_sphere_screen().

	_conds = _build_conditions()
	print("[matrix] splats=%d aabb=%s conditions=%d out=%s" % [_res.point_count, ab, _conds.size(), _out_dir])


func _mode_of(mvar: int) -> Array:
	# -> [RelightPass mode, trans_on]. Extend HERE for MODE_B (M5).
	match mvar:
		MVar.RAW: return [RelightPass.MODE_RAW, false]
		MVar.RELIT: return [RelightPass.MODE_RELIT, false]
		MVar.RELIT_TRANS: return [RelightPass.MODE_RELIT, true]
	return [RelightPass.MODE_RELIT, false]


func _mode_name(mvar: int) -> String:
	match mvar:
		MVar.RAW: return "raw"
		MVar.RELIT: return "relit"
		MVar.RELIT_TRANS: return "relit_trans"
	return "?"


func _num(v: float) -> String:
	var s := String.num(v, 2)
	if s.ends_with(".00"):
		s = s.substr(0, s.length() - 3)
	elif s.ends_with("0") and s.contains("."):
		s = s.substr(0, s.length() - 1)
	return s


func _cond(id: String, group: String, mvar: int, el: float, az: float,
		energy: float, color: Array, ambient: float, env: bool, sphere: bool) -> Dictionary:
	return {
		"id": id, "group": group, "mvar": mvar, "el": el, "az": az,
		"energy": energy, "color": color, "ambient": ambient, "env": env, "sphere_check": sphere,
	}


func _build_conditions() -> Array:
	var out: Array = []
	# A. elevation x azimuth grid (RELIT, env-SH ambient, energy 1, white) + sphere check.
	for el in GRID_EL:
		for az in GRID_AZ:
			var id := "grid_el%02d_az%03d" % [int(el), int(az)]
			out.append(_cond(id, "grid", MVar.RELIT, el, az, 1.0, COLOR_WHITE, DEF_AMBIENT, true, true))
	# B. energy sweep x modes (env OFF, ambient=0 -> clean linearity).
	for e in SWEEP_ENERGY:
		for mv in MODE_VARIANTS:
			var id := "energy_e%s_%s" % [_num(e), _mode_name(mv)]
			out.append(_cond(id, "energy", mv, DEF_EL, DEF_AZ, e, COLOR_WHITE, 0.0, false, false))
	# C. ambient sweep x modes (env OFF, flat ambient).
	for a in SWEEP_AMBIENT:
		for mv in MODE_VARIANTS:
			var id := "ambient_a%s_%s" % [_num(a), _mode_name(mv)]
			out.append(_cond(id, "ambient", mv, DEF_EL, DEF_AZ, 1.0, COLOR_WHITE, a, false, false))
	# D. color sweep x modes (env OFF, flat ambient 0.2).
	for cpair in [["white", COLOR_WHITE], ["warm", COLOR_WARM], ["cool", COLOR_COOL]]:
		for mv in MODE_VARIANTS:
			var id := "color_%s_%s" % [cpair[0], _mode_name(mv)]
			out.append(_cond(id, "color", mv, DEF_EL, DEF_AZ, 1.0, cpair[1], DEF_AMBIENT, false, false))
	# E. extra RAW renders (env ON + off-default directions) -> raw invariance must hold
	#    even with env-SH active and across light directions (env/dir must not leak into raw).
	out.append(_cond("rawx_oblique_env", "raw_extra", MVar.RAW, DEF_EL, DEF_AZ, 1.0, COLOR_WHITE, DEF_AMBIENT, true, false))
	out.append(_cond("rawx_el05_az000_env", "raw_extra", MVar.RAW, 5.0, 0.0, 1.0, COLOR_WHITE, DEF_AMBIENT, true, false))
	out.append(_cond("rawx_el85_az180_env", "raw_extra", MVar.RAW, 85.0, 180.0, 1.0, COLOR_WHITE, DEF_AMBIENT, true, false))
	# F. azimuth 360deg return: re-render grid el=30/az=0 LAST as az=360 (state-drift probe).
	out.append(_cond("return_el30_az360", "return", MVar.RELIT, 30.0, 0.0, 1.0, COLOR_WHITE, DEF_AMBIENT, true, false))
	return out


func _travel_from(el_deg: float, az_deg: float) -> Vector3:
	var el := deg_to_rad(el_deg)
	var az := deg_to_rad(az_deg)
	var from := Vector3(cos(el) * cos(az), sin(el), cos(el) * sin(az))  # light comes FROM
	return -from                                                        # travel dir


func _safe_up(dirn: Vector3) -> Vector3:
	return Vector3(0.0, 0.0, 1.0) if absf(dirn.normalized().y) > 0.99 else Vector3.UP


func _apply_condition(c: Dictionary) -> void:
	var travel := _travel_from(c["el"], c["az"]).normalized()
	# Orient the engine light so -Z basis == travel_dir (ref relight_controller.gd:79-83),
	# then read light_dir_ws from that SAME basis and hand it to set_light: one source of
	# truth for the convention the sphere cross-check verifies.
	_light.look_at_from_position(Vector3.ZERO, travel, _safe_up(travel))
	var light_dir_ws := -_light.global_transform.basis.z

	if c["env"] and _has_env:
		RelightPass.set_env_sh(_env_coeffs)
	else:
		RelightPass.clear_env_sh()

	var col: Array = c["color"]
	var e: float = c["energy"]
	var light_color := Color(col[0] * e, col[1] * e, col[2] * e)
	var mt := _mode_of(c["mvar"])
	RelightPass.set_light(light_dir_ws, light_color, WRAP_POWER, c["ambient"], mt[0], mt[1])


func _process(_delta: float) -> bool:
	if _res == null:
		return true

	if not _warmed:
		if _cidx == -1:
			_cidx = 0
			_apply_condition(_conds[0])
		_settle += 1
		if _settle < _settle_initial:
			return false
		_warmed = true
		_settle = 0
	else:
		_settle += 1
		if _settle < _settle_cond:
			return false
		_settle = 0

	var img := get_root().get_texture().get_image()
	if img == null or img.get_width() == 0:
		push_error("[matrix] empty viewport image (cond %d) -- forgot DISPLAY=:0 / passed --headless?" % _cidx)
		_finish(false)
		return true

	# sphere screen geometry: compute once, now that the viewport has rendered a frame
	# (unproject_position is invalid until then — see _initialize note).
	if not _sph_ready:
		_compute_sphere_screen()
		_sph_ready = true
		print("[matrix] sphere screen center=(%.1f,%.1f) bbox_r=%.1f (res=%s)" % [_sph_sx, _sph_sy, _sph_sr, RES])

	var c: Dictionary = _conds[_cidx]
	var id: String = c["id"]
	var m := _measure(img)
	_measure_by_id[id] = m["scalars"]
	_luma_by_id[id] = m["luma"]
	_cov_by_id[id] = m["cov"]
	if c["sphere_check"]:
		_sphere_by_id[id] = _sphere_centroid(img, _travel_from(c["el"], c["az"]).normalized())

	var fpath := _out_dir.path_join(id + ".png")
	var err := img.save_png(fpath)
	if err != OK or not FileAccess.file_exists(fpath):
		push_error("[matrix] save_png FAILED err=%d -> %s" % [err, fpath])
		_finish(false)
		return true

	var sc: Dictionary = m["scalars"]
	print("[matrix] %-24s %-11s el=%2d az=%3d E=%-4s covered=%d mean=%.5f p2=%.5f nan=%d" % [
		id, _mode_name(c["mvar"]), int(c["el"]), int(c["az"]), _num(c["energy"]),
		int(sc["covered"]), sc["mean_cov"], sc["p_low"], int(sc["nan_inf"])])

	_cidx += 1
	if _cidx >= _conds.size():
		return _evaluate()
	_apply_condition(_conds[_cidx])
	return false


func _compute_sphere_screen() -> void:
	# camera + sphere are fixed for the whole matrix, so project once (needs a live frame).
	_sph_sx = _cam.unproject_position(_sph_center_w).x
	_sph_sy = _cam.unproject_position(_sph_center_w).y
	var edge := _cam.unproject_position(_sph_center_w + _cam.global_transform.basis.x * _sph_r_w)
	_sph_sr = maxf((edge - Vector2(_sph_sx, _sph_sy)).length() * 1.30, 4.0)


func _measure(img: Image) -> Dictionary:
	img.convert(Image.FORMAT_RGBAF)
	var w := img.get_width()
	var h := img.get_height()
	var covered := 0
	var lum_sum := 0.0
	var r_sum := 0.0
	var g_sum := 0.0
	var b_sum := 0.0
	var nan_inf := 0
	var luma := PackedFloat32Array()
	var cov := PackedByteArray()
	var hist := PackedInt32Array()
	hist.resize(HIST_BINS)
	hist.fill(0)
	var sr2 := _sph_sr * _sph_sr
	var x := 0
	while x < w:
		var y := 0
		while y < h:
			var pc := img.get_pixel(x, y)
			if not (is_finite(pc.r) and is_finite(pc.g) and is_finite(pc.b)):
				nan_inf += 1
			var l := 0.2126 * pc.r + 0.7152 * pc.g + 0.0722 * pc.b
			luma.append(l)
			# foliage sample = non-BG AND outside the sphere's fixed screen bbox.
			var in_sphere := ((x - _sph_sx) * (x - _sph_sx) + (y - _sph_sy) * (y - _sph_sy)) <= sr2
			var d := absf(pc.r - BG.r) + absf(pc.g - BG.g) + absf(pc.b - BG.b)
			if d > COVER_EPS and not in_sphere:
				covered += 1
				lum_sum += l
				r_sum += pc.r
				g_sum += pc.g
				b_sum += pc.b
				hist[clampi(int(l * HIST_BINS), 0, HIST_BINS - 1)] += 1
				cov.append(1)
			else:
				cov.append(0)
			y += SAMPLE_STEP
		x += SAMPLE_STEP
	# darkest percentile over foliage (ambient floor).
	var p_low := 0.0
	var target := int(covered * AMBIENT_FLOOR_PCT)
	var acc := 0
	for bidx in HIST_BINS:
		acc += hist[bidx]
		if acc >= target:
			p_low = float(bidx) / float(HIST_BINS)
			break
	var cf := float(maxi(covered, 1))
	return {
		"scalars": {
			"covered": covered,
			"mean_cov": lum_sum / cf,
			"mean_rgb": [r_sum / cf, g_sum / cf, b_sum / cf],
			"p_low": p_low,
			"nan_inf": nan_inf,
		},
		"luma": luma,
		"cov": cov,
	}


# Bright-pixel centroid of the engine-lit gray sphere within its fixed screen bbox.
func _sphere_centroid(img: Image, travel: Vector3) -> Dictionary:
	var w := img.get_width()
	var h := img.get_height()
	var x0 := maxi(int(_sph_sx - _sph_sr), 0)
	var x1 := mini(int(_sph_sx + _sph_sr), w - 1)
	var y0 := maxi(int(_sph_sy - _sph_sr), 0)
	var y1 := mini(int(_sph_sy + _sph_sr), h - 1)
	var sr2 := _sph_sr * _sph_sr
	var wsum := 0.0
	var cx := 0.0
	var cy := 0.0
	var n := 0
	var contam := 0
	for x in range(x0, x1 + 1):
		for y in range(y0, y1 + 1):
			if ((x - _sph_sx) * (x - _sph_sx) + (y - _sph_sy) * (y - _sph_sy)) > sr2:
				continue
			var pc := img.get_pixel(x, y)
			var d := absf(pc.r - BG.r) + absf(pc.g - BG.g) + absf(pc.b - BG.b)
			if d <= COVER_EPS:
				continue  # background
			if absf(pc.r - pc.g) > GRAY_EPS or absf(pc.g - pc.b) > GRAY_EPS:
				contam += 1  # non-gray -> stray foliage in the bbox (not the sphere)
				continue
			var l := 0.2126 * pc.r + 0.7152 * pc.g + 0.0722 * pc.b
			wsum += l
			cx += l * float(x)
			cy += l * float(y)
			n += 1
	# screen projection of -travel_dir (= L, direction light comes FROM).
	var c2 := _cam.unproject_position(_sph_center_w)
	var l2 := _cam.unproject_position(_sph_center_w + (-travel) * _sph_r_w)
	var from_scr := l2 - c2
	var res := {
		"n": n, "contam": contam,
		"center": [c2.x, c2.y],
		"from_screen": [from_scr.x, from_scr.y],
		"dot": -2.0, "centroid": [0.0, 0.0], "pass": false,
	}
	if n <= 0 or wsum <= 0.0 or from_scr.length() < 1e-4:
		return res
	var centroid := Vector2(cx / wsum, cy / wsum)
	var offset := centroid - c2
	res["centroid"] = [centroid.x, centroid.y]
	if offset.length() < 1e-4:
		res["dot"] = 0.0
		return res
	var dot := offset.normalized().dot(from_scr.normalized())
	res["dot"] = dot
	res["pass"] = dot > SPHERE_DOT_MIN
	return res


func _psnr(ida: String, idb: String) -> Dictionary:
	var a: PackedFloat32Array = _luma_by_id[ida]
	var b: PackedFloat32Array = _luma_by_id[idb]
	var ca: PackedByteArray = _cov_by_id[ida]
	var cb: PackedByteArray = _cov_by_id[idb]
	var se := 0.0
	var n := 0
	var maxd := 0.0
	for k in a.size():
		if ca[k] != 0 and cb[k] != 0:
			var dd := a[k] - b[k]
			se += dd * dd
			n += 1
			maxd = maxf(maxd, absf(dd))
	if n == 0:
		return {"psnr": 0.0, "n": 0, "maxd": 0.0}
	var mse := se / float(n)
	var psnr := 99.0 if mse <= 1e-12 else 10.0 * log(1.0 / mse) / log(10.0)
	return {"psnr": psnr, "n": n, "maxd": maxd}


func _median(v: Array) -> float:
	if v.is_empty():
		return 0.0
	v.sort()
	var mid := v.size() / 2
	return v[mid] if v.size() % 2 == 1 else 0.5 * (v[mid - 1] + v[mid])


func _ids_where(pred: Callable) -> Array:
	var out: Array = []
	for c in _conds:
		if pred.call(c):
			out.append(c["id"])
	return out


func _evaluate() -> bool:
	var checks := {}
	var problems: Array[String] = []

	# --- 1. no NaN/inf pixels anywhere -----------------------------------------
	var total_nan := 0
	var worst_nan := ""
	for id in _measure_by_id:
		var nn: int = _measure_by_id[id]["nan_inf"]
		total_nan += nn
		if nn > 0 and worst_nan == "":
			worst_nan = id
	checks["no_nan_inf"] = {"pass": total_nan == 0, "total_nan_inf": total_nan, "threshold": 0, "first_offender": worst_nan}
	if total_nan != 0:
		problems.append("no_nan_inf: %d non-finite pixels (first=%s)" % [total_nan, worst_nan])

	# --- min coverage: splats actually rendered every condition ----------------
	# Two guards (see MIN_COVERED / BLANK_MIN): (a) the brightness-stable RAW footprint
	# must clear MIN_COVERED (catches a culled/shrunk asset); (b) EVERY condition must
	# clear BLANK_MIN (catches a dropped/blank frame in any single condition, robust to
	# the deliberate darkness that legitimately shrinks relit "covered" via alpha-blend to BG).
	var raw_min_cov := 1 << 30
	var raw_min_id := ""
	var any_min_cov := 1 << 30
	var any_min_id := ""
	for c in _conds:
		var cc: int = _measure_by_id[c["id"]]["covered"]
		if cc < any_min_cov:
			any_min_cov = cc
			any_min_id = c["id"]
		if _mode_of(c["mvar"])[0] == RelightPass.MODE_RAW and cc < raw_min_cov:
			raw_min_cov = cc
			raw_min_id = c["id"]
	var cov_ok := raw_min_cov >= MIN_COVERED and any_min_cov >= BLANK_MIN
	checks["min_coverage"] = {
		"pass": cov_ok,
		"raw_min_covered": raw_min_cov, "raw_min_condition": raw_min_id, "footprint_threshold": MIN_COVERED,
		"any_min_covered": any_min_cov, "any_min_condition": any_min_id, "blank_threshold": BLANK_MIN,
		"note": "footprint floor on brightness-stable RAW; blank floor on every condition (dim relit alpha-blends toward BG)",
	}
	if raw_min_cov < MIN_COVERED:
		problems.append("min_coverage: RAW footprint %s covered=%d < %d (asset culled/not rendered)" % [raw_min_id, raw_min_cov, MIN_COVERED])
	if any_min_cov < BLANK_MIN:
		problems.append("min_coverage: %s covered=%d < %d (blank/dropped frame)" % [any_min_id, any_min_cov, BLANK_MIN])

	# --- 2. relit mean-luma bounds (nominal energy only; over-drive is reported) -
	var relit_lo := INF
	var relit_hi := -INF
	var lo_id := ""
	var hi_id := ""
	var overdrive := {}
	for c in _conds:
		if _mode_of(c["mvar"])[0] != RelightPass.MODE_RELIT:
			continue
		var mean: float = _measure_by_id[c["id"]]["mean_cov"]
		if c["energy"] > NOMINAL_ENERGY_MAX:
			overdrive[c["id"]] = mean   # deliberate saturation stress; excluded from the bound
			continue
		if mean < relit_lo:
			relit_lo = mean; lo_id = c["id"]
		if mean > relit_hi:
			relit_hi = mean; hi_id = c["id"]
	var bounds_ok := relit_lo > LUMA_LO and relit_hi < LUMA_HI
	checks["relit_luma_bounds"] = {
		"pass": bounds_ok, "min_mean": relit_lo, "min_condition": lo_id,
		"max_mean": relit_hi, "max_condition": hi_id,
		"lo_threshold": LUMA_LO, "hi_threshold": LUMA_HI,
		"note": "energy>%s excluded (deliberate over-drive for linearity)" % _num(NOMINAL_ENERGY_MAX),
		"overdrive_means": overdrive,
	}
	if not bounds_ok:
		problems.append("relit_luma_bounds: min=%.5f(%s) max=%.5f(%s) outside (%.2f,%.2f)" % [relit_lo, lo_id, relit_hi, hi_id, LUMA_LO, LUMA_HI])

	# --- 3. RAW invariance: foliage identical across ALL raw conditions ---------
	var raw_ids := _ids_where(func(c): return _mode_of(c["mvar"])[0] == RelightPass.MODE_RAW)
	var raw_min_psnr := INF
	var raw_max_diff := 0.0
	var raw_pair := ""
	if raw_ids.size() >= 2:
		var ref: String = raw_ids[0]
		for i in range(1, raw_ids.size()):
			var pr := _psnr(ref, raw_ids[i])
			if pr["psnr"] < raw_min_psnr:
				raw_min_psnr = pr["psnr"]; raw_pair = "%s|%s" % [ref, raw_ids[i]]
			raw_max_diff = maxf(raw_max_diff, pr["maxd"])
	else:
		raw_min_psnr = 99.0
	var raw_ok := raw_min_psnr >= RAW_PSNR_MIN
	checks["raw_invariance"] = {
		"pass": raw_ok, "n_raw": raw_ids.size(), "min_psnr_db": raw_min_psnr,
		"max_abs_pixel_diff": raw_max_diff, "threshold_db": RAW_PSNR_MIN, "worst_pair": raw_pair,
	}
	if not raw_ok:
		problems.append("raw_invariance: min_psnr=%.2f dB < %.2f (%s) maxdiff=%.5f" % [raw_min_psnr, RAW_PSNR_MIN, raw_pair, raw_max_diff])

	# --- 4. trans inertness: RELIT == RELIT+trans_on (trans==0) -----------------
	var trans_min_psnr := INF
	var trans_max_diff := 0.0
	var trans_pair := ""
	var trans_pairs := 0
	for c in _conds:
		if c["mvar"] != MVar.RELIT:
			continue
		var tid: String = String(c["id"]).replace("_relit", "_relit_trans")
		if tid == String(c["id"]):
			continue  # grid_*/return_* RELIT ids have no "_relit" suffix -> no trans partner (skip self-compare)
		if not _luma_by_id.has(tid):
			continue
		trans_pairs += 1
		var pr := _psnr(c["id"], tid)
		if pr["psnr"] < trans_min_psnr:
			trans_min_psnr = pr["psnr"]; trans_pair = "%s|%s" % [c["id"], tid]
		trans_max_diff = maxf(trans_max_diff, pr["maxd"])
	if trans_pairs == 0:
		trans_min_psnr = 0.0
	var trans_ok := trans_pairs > 0 and trans_min_psnr >= TRANS_PSNR_MIN
	checks["trans_inertness"] = {
		"pass": trans_ok, "n_pairs": trans_pairs, "min_psnr_db": trans_min_psnr,
		"max_abs_pixel_diff": trans_max_diff, "threshold_db": TRANS_PSNR_MIN,
		"worst_pair": trans_pair, "asset_trans_max": _trans_max,
	}
	if not trans_ok:
		problems.append("trans_inertness: pairs=%d min_psnr=%.2f dB < %.2f (%s)" % [trans_pairs, trans_min_psnr, TRANS_PSNR_MIN, trans_pair])

	# --- 5. azimuth 360deg return -----------------------------------------------
	var az_ok := false
	var az_psnr := 0.0
	if _luma_by_id.has("grid_el30_az000") and _luma_by_id.has("return_el30_az360"):
		var pr := _psnr("grid_el30_az000", "return_el30_az360")
		az_psnr = pr["psnr"]
		az_ok = az_psnr > AZ_RETURN_PSNR_MIN
		checks["azimuth_return"] = {"pass": az_ok, "psnr_db": az_psnr, "threshold_db": AZ_RETURN_PSNR_MIN, "max_abs_pixel_diff": pr["maxd"]}
	else:
		checks["azimuth_return"] = {"pass": false, "psnr_db": 0.0, "threshold_db": AZ_RETURN_PSNR_MIN, "error": "missing az=0/az=360 renders"}
	if not az_ok:
		problems.append("azimuth_return: psnr=%.2f dB <= %.2f (state drift over a full orbit)" % [az_psnr, AZ_RETURN_PSNR_MIN])

	# --- 6. energy linearity: luma(2E)/luma(E) ~= 2 on non-saturated band -------
	var pairs: Array = []
	var lin_ok := true
	var asserted := 0
	for i in range(SWEEP_ENERGY.size() - 1):
		var e1: float = SWEEP_ENERGY[i]
		var e2: float = SWEEP_ENERGY[i + 1]
		if absf(e2 - 2.0 * e1) > 1e-6:
			continue  # only true doubling pairs
		var idA := "energy_e%s_relit" % _num(e1)
		var idB := "energy_e%s_relit" % _num(e2)
		if not (_luma_by_id.has(idA) and _luma_by_id.has(idB)):
			continue
		var la: PackedFloat32Array = _luma_by_id[idA]
		var lb: PackedFloat32Array = _luma_by_id[idB]
		var ca: PackedByteArray = _cov_by_id[idA]
		var cb: PackedByteArray = _cov_by_id[idB]
		var ratios: Array = []
		for k in la.size():
			if ca[k] != 0 and cb[k] != 0 and la[k] > ENERGY_BAND_LO and lb[k] < ENERGY_BAND_HI and la[k] > 1e-4:
				ratios.append(lb[k] / la[k])
		var med := _median(ratios)
		var pair_ok := true
		if ratios.size() >= ENERGY_MIN_PIX:
			pair_ok = absf(med - 2.0) <= ENERGY_RATIO_TOL
			asserted += 1
			if not pair_ok:
				lin_ok = false
		pairs.append({"E": e1, "2E": e2, "median_ratio": med, "n_pixels": ratios.size(), "asserted": ratios.size() >= ENERGY_MIN_PIX, "pass": pair_ok})
	if asserted == 0:
		lin_ok = false
	checks["energy_linearity"] = {
		"pass": lin_ok, "target_ratio": 2.0, "tolerance": ENERGY_RATIO_TOL,
		"band_lo": ENERGY_BAND_LO, "band_hi": ENERGY_BAND_HI, "min_pixels": ENERGY_MIN_PIX, "pairs": pairs,
	}
	if not lin_ok:
		problems.append("energy_linearity: a doubling pair off 2x by > %.2f (or no pair had >= %d band pixels)" % [ENERGY_RATIO_TOL, ENERGY_MIN_PIX])

	# --- 7. elevation smoothness: no adjacent mean-luma jump above threshold -----
	var max_jump := 0.0
	var jump_at := ""
	var per_az := {}
	for az in GRID_AZ:
		var seq: Array = []
		for el in GRID_EL:
			var gid := "grid_el%02d_az%03d" % [int(el), int(az)]
			seq.append(_measure_by_id[gid]["mean_cov"])
		per_az["az%03d" % int(az)] = seq
		for i in range(1, seq.size()):
			var j: float = absf(seq[i] - seq[i - 1])
			if j > max_jump:
				max_jump = j
				jump_at = "az%03d el%d->%d" % [int(az), int(GRID_EL[i - 1]), int(GRID_EL[i])]
	var elev_ok := max_jump < ELEV_JUMP_MAX
	checks["elevation_smoothness"] = {
		"pass": elev_ok, "max_adjacent_jump": max_jump, "threshold": ELEV_JUMP_MAX,
		"jump_at": jump_at, "elevations": GRID_EL, "mean_by_azimuth": per_az,
	}
	if not elev_ok:
		problems.append("elevation_smoothness: max jump %.5f (%s) >= %.5f" % [max_jump, jump_at, ELEV_JUMP_MAX])

	# --- 8. ambient floor: flat ambient=0.5 relit, darkest percentile >= floor --
	var floor_id := "ambient_a0.5_relit"
	var floor_ok := false
	var floor_val := 0.0
	if _measure_by_id.has(floor_id):
		floor_val = _measure_by_id[floor_id]["p_low"]
		floor_ok = floor_val >= AMBIENT_FLOOR
		checks["ambient_floor"] = {"pass": floor_ok, "p_low": floor_val, "percentile": AMBIENT_FLOOR_PCT, "floor": AMBIENT_FLOOR, "condition": floor_id}
	else:
		checks["ambient_floor"] = {"pass": false, "floor": AMBIENT_FLOOR, "error": "missing %s" % floor_id}
	if not floor_ok:
		problems.append("ambient_floor: p%d=%.5f < %.5f (black shadows at ambient 0.5)" % [int(AMBIENT_FLOOR_PCT * 100), floor_val, AMBIENT_FLOOR])

	# --- 9. engine cross-model sphere consistency -------------------------------
	var sph_min_dot := INF
	var sph_worst := ""
	var sph_records: Array = []
	var sph_n := 0
	var sph_ok := true
	for id in _sphere_by_id:
		var s: Dictionary = _sphere_by_id[id]
		sph_n += 1
		sph_records.append({"id": id, "dot": s["dot"], "n_px": s["n"], "contam": s["contam"], "pass": s["pass"]})
		if s["dot"] < sph_min_dot:
			sph_min_dot = s["dot"]; sph_worst = id
		if not s["pass"]:
			sph_ok = false
	if sph_n == 0:
		sph_ok = false
	checks["sphere_consistency"] = {
		"pass": sph_ok, "n_checked": sph_n, "min_dot": sph_min_dot, "worst_condition": sph_worst,
		"dot_threshold": SPHERE_DOT_MIN, "records": sph_records,
	}
	if not sph_ok:
		problems.append("sphere_consistency: min_dot=%.4f (%s) <= %.4f OR no sphere pixels (engine/convention mismatch)" % [sph_min_dot, sph_worst, SPHERE_DOT_MIN])

	# --- write JSON + summary ---------------------------------------------------
	var conditions_out: Array = []
	for c in _conds:
		var sc: Dictionary = _measure_by_id[c["id"]]
		var rec := {
			"id": c["id"], "group": c["group"], "mode": _mode_name(c["mvar"]),
			"el_deg": c["el"], "az_deg": c["az"], "energy": c["energy"],
			"color": c["color"], "ambient": c["ambient"], "env_sh": c["env"] and _has_env,
			"covered": sc["covered"], "mean_luma": sc["mean_cov"], "mean_rgb": sc["mean_rgb"],
			"p_low": sc["p_low"], "nan_inf": sc["nan_inf"],
		}
		if _sphere_by_id.has(c["id"]):
			rec["sphere_dot"] = _sphere_by_id[c["id"]]["dot"]
		conditions_out.append(rec)

	var all_pass := problems.is_empty()
	var doc := {
		"tool": "render_matrix.gd",
		"asset": ASSET_PATH,
		"resolution": [RES.x, RES.y],
		"env_sh_active": _has_env,
		"asset_trans_max": _trans_max,
		"settle": {"initial": _settle_initial, "per_condition": _settle_cond},
		"n_conditions": _conds.size(),
		"sphere": {"screen_center": [_sph_sx, _sph_sy], "screen_bbox_radius": _sph_sr, "world_radius": _sph_r_w},
		"checks": checks,
		"conditions": conditions_out,
		"result": "PASS" if all_pass else "FAIL",
	}
	var jpath := _out_dir.path_join("lighting_stability.json")
	var jf := FileAccess.open(jpath, FileAccess.WRITE)
	if jf != null:
		jf.store_string(JSON.stringify(doc, "  "))
		jf.close()
		print("[matrix] wrote %s" % jpath)
	else:
		push_error("[matrix] failed to write %s" % jpath)

	print("[matrix] === CHECKS ===")
	for name in checks:
		print("[matrix]   %-22s %s" % [name, "PASS" if checks[name]["pass"] else "FAIL"])
	if not all_pass:
		for p in problems:
			push_error("[matrix] FAIL: %s" % p)

	_finish(all_pass)
	return true


func _resolve_out_dir() -> String:
	var d := OS.get_environment("LIGHTING_OUT_DIR")
	if d.is_empty():
		var ua := OS.get_cmdline_user_args()
		if ua.size() > 0:
			d = ua[0]
	if d.is_empty():
		d = "res://shots/lighting_stability"
	var abs_dir := d
	if d.begins_with("res://") or d.begins_with("user://"):
		abs_dir = ProjectSettings.globalize_path(d)
	elif not d.is_absolute_path():
		abs_dir = ProjectSettings.globalize_path("res://".path_join(d))
	DirAccess.make_dir_recursive_absolute(abs_dir)
	return abs_dir


func _finish(ok: bool) -> void:
	print("LIGHTING_STABILITY_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
