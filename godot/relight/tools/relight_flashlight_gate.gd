extends SceneTree
# Flashlight (local point/spot light) ANALYTIC gate (real GPU, DISPLAY=:0). Unlike
# relight_render_gate.gd (real foliage asset, near-isotropic normals -> only relative
# checks), this builds a SYNTHETIC splat at a KNOWN position with a KNOWN normal and
# albedo, kills the directional + ambient terms (energy 0, ambient 0), and asserts the
# rendered color matches the CLOSED-FORM point-light term: albedo * direct * falloff *
# cone. Phases:
#   P0 relit, flashlight ON on-axis, near-full range -> mean == closed form (cone=1)
#   P1 relit, flashlight ON aimed AWAY   -> mean ~= 0 (cone term kills the contribution)
#   P2 RAW,   flashlight ON              -> mean == albedo (local light must NOT leak into raw)
#   P3 RAW,   flashlight OFF             -> mean == albedo, == P2 (raw invariance)
#   P4 relit, on-axis, NON-trivial range -> mean == closed form (range_win ~=0.31; exercises range term)
#   P5 relit, on-axis, OUT of range      -> mean ~= 0 (range clamp cuts the light beyond range)
# P4/P5 exist because P0 alone is fail-OPEN on the range term (range_win ~=0.98 there hides
# a removed clamp under tol); P4 makes the range multiplier load-bearing and P5 is a hard
# discriminator (a dropped clamp would light an out-of-range splat).
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/relight_flashlight_gate.gd
#   RELIGHT_SHOT_DIR=/abs/dir  -> also writes one PNG per phase (eyeball only).
#
# Closed form MUST match relight.glsl's flashlight block and RelightPass.set_flashlight
# (inverse-square with a smooth range window, smoothstep spot cone). If the shader math
# drifts, P0's absolute check fails.

const RelightPass = preload("res://relight/relight_pass.gd")
const RelightGaussianResourceScript = preload("res://relight/relight_gaussian_resource.gd")
const GaussianResourceBuilder = preload("res://addons/gdgs/importers/builders/gaussian_resource_builder.gd")

const SH_C0 := 0.28209479177387814

# --- synthetic splat ---
const N_SPLATS := 4000               # many small splats densely fill a disk (mirrors real-asset profile;
                                     #  a few huge splats overflow the tile-sort cap and drop)
const SPLAT_SCALE := 0.02            # isotropic std dev (world units), like the real decomposed asset
const SPLAT_SPREAD := 0.15           # lateral (XY) cloud radius (<< CAM_DIST)
const SPLAT_SPREAD_Z := 0.005        # near-flat in depth: every splat sits ~CAM_DIST from the light,
                                     #  so the alpha composite is NOT biased toward closer/brighter splats
const SPLAT_OPACITY := 0.9
const ALBEDO := 0.6                  # gray
const ROUGH := 0.5
const NORMAL := Vector3(0.0, 0.0, 1.0)  # faces +Z (toward the camera + flashlight)

# --- camera / flashlight geometry (world) ---
const CAM_DIST := 1.0                # camera + flashlight on +Z axis, aimed at origin (dist to splat)
const FLASH_ENERGY := 1.5            # keeps the closed-form result mid-range (no clip at 1.0)
const FLASH_RANGE := 8.0             # >> dist -> range_win ~= 0.98 (near-full range)
# The range window MUST be exercised where it is NON-trivial, else the gate is fail-OPEN:
# at dist=1 with range=8 the window is ~0.98, so deleting it (falloff=inv_sq) shifts the
# result <2% and slips under tol. FLASH_RANGE_NEAR gives range_win ~= 0.31 (a removed term
# would then read ~3.2x too bright), and FLASH_RANGE_OUT < dist puts the splat OUT of range
# (window == 0) so a dropped clamp would light it -> a hard discriminator.
const FLASH_RANGE_NEAR := 1.2        # dist=1 -> range_win = 1 - 1/1.44 = 0.3056
const FLASH_RANGE_OUT := 0.5         # dist=1 > 0.5 -> range_win clamps to 0 (out of range)
const FLASH_INNER_DEG := 14.0
const FLASH_OUTER_DEG := 24.0

const BG := Color(0.0, 0.0, 0.0)     # black -> composited color = splat_color * alpha
const SETTLE := 40                   # match relight_render_gate: cold shader-pipeline cache
                                     #  needs ~this many frames to warm (flash_delta reads 0 until then)
const WIN := 40                      # half-size of the central sampling window (px)
const MIN_COVERED := 400             # synthetic splat must actually render
const N_PHASES := 6

const TOL_ABS := 0.03                # closed-form / albedo absolute tolerance (warm err measured ~0.002)
const TOL_ZERO := 0.03               # cone-miss / out-of-range "near zero" bound
const TOL_RAW := 0.02                # |raw(flash on) - raw(flash off)| bound

var _phase := 0
var _frames := 0
var _shot_dir := ""
var _measures := []
var _ready := false


func _initialize() -> void:
	_shot_dir = _resolve_shot_dir()
	var root := get_root()
	root.size = Vector2i(1280, 960)

	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = BG
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.0, 0.0, 0.0)
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	root.add_child(we)

	var res = _build_synthetic()
	if res == null:
		push_error("[flash-gate] synthetic asset build failed")
		_finish(false)
		return
	RelightPass.set_materials(res.attr_data_byte, res.point_count)
	RelightPass.clear_env_sh()

	var gs := GaussianSplatNode.new()
	gs.gaussian = res
	root.add_child(gs)
	# NOTE: unlike the interactive controller we do NOT reset the transform to IDENTITY.
	# GDGS applies its default -PI Z node correction (rotation about Z); the closed-form
	# check is entirely on the +Z axis (normal, light, camera), which that rotation
	# leaves invariant, so the analytic result is unaffected. (Matches relight_render_gate.)

	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(Vector3(0.0, 0.0, CAM_DIST), Vector3.ZERO, Vector3.UP)
	cam.current = true

	_ready = true
	print("[flash-gate] synthetic splats=%d scale=%.3f albedo=%.3f normal=%s aabb=%s" % [
		res.point_count, SPLAT_SCALE, ALBEDO, str(NORMAL), str(res.aabb)])


# Build a cluster of identical splats at the origin (centered geometry -> world pos 0),
# facing +Z, with a known albedo/normal packed into the 3-vec4 material buffer.
func _build_synthetic():
	var canonical := GaussianResourceBuilder.create_canonical(N_SPLATS)
	var positions: PackedVector3Array = canonical["positions"]
	var scales: PackedVector3Array = canonical["scales_linear"]
	var rotations: Array = canonical["rotations"]
	var opacities: PackedFloat32Array = canonical["opacities"]
	var sh: PackedFloat32Array = canonical["sh_coeffs"]
	# Tiny deterministic spread around the origin so the AABB is non-degenerate (a
	# zero-size AABB gets frustum-culled -> nothing renders). << CAM_DIST, so the
	# closed-form distance is CAM_DIST within tolerance.
	var rng := RandomNumberGenerator.new()
	rng.seed = 12345
	for i in N_SPLATS:
		positions[i] = Vector3(
			rng.randf_range(-SPLAT_SPREAD, SPLAT_SPREAD),
			rng.randf_range(-SPLAT_SPREAD, SPLAT_SPREAD),
			rng.randf_range(-SPLAT_SPREAD_Z, SPLAT_SPREAD_Z))
		scales[i] = Vector3(SPLAT_SCALE, SPLAT_SCALE, SPLAT_SCALE)
		rotations[i] = Quaternion.IDENTITY
		opacities[i] = SPLAT_OPACITY
		var sb := i * 48
		sh[sb + 0] = (ALBEDO - 0.5) / SH_C0
		sh[sb + 1] = (ALBEDO - 0.5) / SH_C0
		sh[sb + 2] = (ALBEDO - 0.5) / SH_C0
	var build := GaussianResourceBuilder.build(canonical)
	if not build.get("ok", false):
		return null
	var base: GaussianResource = build["resource"]

	# Material buffer: 3 vec4 / splat (albedo_rough, normal_trans, pos_label). Position
	# from the builder's centered geometry (base.xyz == 0 here).
	var attr := PackedFloat32Array()
	attr.resize(N_SPLATS * 12)
	var centered: PackedVector3Array = base.xyz
	for i in N_SPLATS:
		var m := i * 12
		attr[m + 0] = ALBEDO
		attr[m + 1] = ALBEDO
		attr[m + 2] = ALBEDO
		attr[m + 3] = ROUGH
		attr[m + 4] = NORMAL.x
		attr[m + 5] = NORMAL.y
		attr[m + 6] = NORMAL.z
		attr[m + 7] = 0.0            # trans
		attr[m + 8] = centered[i].x
		attr[m + 9] = centered[i].y
		attr[m + 10] = centered[i].z
		attr[m + 11] = 0.0           # label

	var res := RelightGaussianResourceScript.new()
	res.point_count = base.point_count
	res.point_data_float = base.point_data_float
	res.point_data_byte = base.point_data_byte
	res.xyz = base.xyz
	res.aabb = base.aabb
	res.attr_data_byte = attr.to_byte_array()
	res.relight_schema_version = 1
	return res


func _apply_phase() -> void:
	# No directional / ambient contribution: color(0,0,0), ambient 0 -> only the flashlight.
	var no_sun := Color(0.0, 0.0, 0.0)
	match _phase:
		0: # relit, flashlight ON, on-axis (cone = 1)
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RELIT, false)
			RelightPass.set_flashlight(true, Vector3(0.0, 0.0, CAM_DIST), Vector3(0.0, 0.0, -1.0),
				Color(1.0, 1.0, 1.0), FLASH_ENERGY, FLASH_RANGE, FLASH_INNER_DEG, FLASH_OUTER_DEG)
		1: # relit, flashlight ON but aimed AWAY (splat outside the cone -> contribution 0)
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RELIT, false)
			RelightPass.set_flashlight(true, Vector3(0.0, 0.0, CAM_DIST), Vector3(0.0, -1.0, 0.0),
				Color(1.0, 1.0, 1.0), FLASH_ENERGY, FLASH_RANGE, FLASH_INNER_DEG, FLASH_OUTER_DEG)
		2: # RAW, flashlight ON -> must be plain albedo (no leak)
			RelightPass.set_flashlight(true, Vector3(0.0, 0.0, CAM_DIST), Vector3(0.0, 0.0, -1.0),
				Color(1.0, 1.0, 1.0), FLASH_ENERGY, FLASH_RANGE, FLASH_INNER_DEG, FLASH_OUTER_DEG)
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RAW, false)
		3: # RAW, flashlight OFF -> plain albedo, must equal phase 2
			RelightPass.clear_flashlight()
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RAW, false)
		4: # relit, on-axis, NON-trivial range window (range_win ~= 0.31) -> exercises the range term
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RELIT, false)
			RelightPass.set_flashlight(true, Vector3(0.0, 0.0, CAM_DIST), Vector3(0.0, 0.0, -1.0),
				Color(1.0, 1.0, 1.0), FLASH_ENERGY, FLASH_RANGE_NEAR, FLASH_INNER_DEG, FLASH_OUTER_DEG)
		5: # relit, on-axis, splat OUT of range (dist > range) -> contribution must be ~0
			RelightPass.set_light(Vector3(0.0, -1.0, 0.0), no_sun, 2.0, 0.0, RelightPass.MODE_RELIT, false)
			RelightPass.set_flashlight(true, Vector3(0.0, 0.0, CAM_DIST), Vector3(0.0, 0.0, -1.0),
				Color(1.0, 1.0, 1.0), FLASH_ENERGY, FLASH_RANGE_OUT, FLASH_INNER_DEG, FLASH_OUTER_DEG)


func _process(_delta: float) -> bool:
	if not _ready:
		return true
	if _frames == 0:
		_apply_phase()
	_frames += 1
	if _frames < SETTLE:
		return false

	var img := get_root().get_texture().get_image()
	if img == null or img.get_width() == 0:
		push_error("[flash-gate] empty viewport image (phase %d)" % _phase)
		_finish(false)
		return true

	var m := _measure(img)
	_measures.append(m)
	print("[flash-gate] phase %d: covered=%d rgb=(%.4f,%.4f,%.4f) luma=%.4f" % [
		_phase, m["covered"], m["r"], m["g"], m["b"], m["luma"]])
	if not _shot_dir.is_empty():
		img.save_png(_shot_dir.path_join("flash_gate_p%d.png" % _phase))

	_phase += 1
	_frames = 0
	if _phase >= N_PHASES:
		return _evaluate()
	return false


# Closed-form flashlight luma for an on-axis splat at CAM_DIST with the given range
# (direct = 1, cone = 1). MUST mirror relight.glsl: inverse-square * smooth range window.
func _expected_luma(range: float) -> float:
	var dist := CAM_DIST
	var inv_sq := 1.0 / (1.0 + dist * dist)
	var range_win := clampf(1.0 - (dist * dist) / (range * range), 0.0, 1.0)
	return ALBEDO * FLASH_ENERGY * inv_sq * range_win


# Central-window mean color. For the cone-miss / raw checks we also report the window's
# raw (unmasked) mean luma so a fully-black frame is measurable (covered==0 there).
func _measure(img: Image) -> Dictionary:
	img.convert(Image.FORMAT_RGBAF)
	var w := img.get_width()
	var h := img.get_height()
	var cx := w / 2
	var cy := h / 2
	var covered := 0
	var sum_r := 0.0
	var sum_g := 0.0
	var sum_b := 0.0
	var win_lum := 0.0
	var win_n := 0
	var x := cx - WIN
	while x <= cx + WIN:
		var y := cy - WIN
		while y <= cy + WIN:
			if x >= 0 and y >= 0 and x < w and y < h:
				var c := img.get_pixel(x, y)
				win_lum += 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
				win_n += 1
				var d := absf(c.r - BG.r) + absf(c.g - BG.g) + absf(c.b - BG.b)
				if d > 0.02:
					covered += 1
					sum_r += c.r
					sum_g += c.g
					sum_b += c.b
			y += 1
		x += 1
	var n := maxi(covered, 1)
	var r := sum_r / n
	var g := sum_g / n
	var b := sum_b / n
	return {
		"covered": covered,
		"r": r, "g": g, "b": b,
		"luma": 0.2126 * r + 0.7152 * g + 0.0722 * b,
		"win_luma": win_lum / float(maxi(win_n, 1)),
	}


func _evaluate() -> bool:
	var p0: Dictionary = _measures[0]  # relit, on-axis, near-full range (range=8)
	var p1: Dictionary = _measures[1]  # relit, aimed away (cone miss)
	var p2: Dictionary = _measures[2]  # raw, flashlight on
	var p3: Dictionary = _measures[3]  # raw, flashlight off
	var p4: Dictionary = _measures[4]  # relit, on-axis, NON-trivial range window (range=1.2)
	var p5: Dictionary = _measures[5]  # relit, on-axis, OUT of range (range=0.5 < dist)

	var expected0 := _expected_luma(FLASH_RANGE)       # range_win ~= 0.98
	var expected4 := _expected_luma(FLASH_RANGE_NEAR)  # range_win ~= 0.31 (exercises the range term)

	var problems: Array[String] = []
	if int(p0["covered"]) < MIN_COVERED:
		problems.append("phase 0 covered=%d < %d (synthetic splat did not render)" % [int(p0["covered"]), MIN_COVERED])
	if int(p2["covered"]) < MIN_COVERED:
		problems.append("phase 2 covered=%d < %d (synthetic splat did not render)" % [int(p2["covered"]), MIN_COVERED])

	# (1) closed-form point-light term, near-full range.
	var err0 := absf(float(p0["luma"]) - expected0)
	if err0 > TOL_ABS:
		problems.append("point-light term off (near range): measured=%.4f expected=%.4f err=%.4f > %.4f" % [
			float(p0["luma"]), expected0, err0, TOL_ABS])
	# (1b) closed-form with a NON-trivial range window -> a removed/broken range term
	# (falloff=inv_sq) would read ~%.2fx too bright here and blow past tol.
	var err4 := absf(float(p4["luma"]) - expected4)
	if err4 > TOL_ABS:
		problems.append("range window wrong: measured=%.4f expected=%.4f err=%.4f > %.4f (range_win term broken)" % [
			float(p4["luma"]), expected4, err4, TOL_ABS])
	# (1c) OUT-OF-RANGE hard discriminator: dist > range -> window==0 -> contribution ~0.
	# A dropped range clamp would light this splat (inv_sq alone ~= %.3f).
	if float(p5["win_luma"]) > TOL_ZERO:
		problems.append("out-of-range leak: window luma=%.4f > %.4f (range clamp did not cut the light beyond range)" % [
			float(p5["win_luma"]), TOL_ZERO])
	# (2) cone term: aimed away -> ~0.
	if float(p1["win_luma"]) > TOL_ZERO:
		problems.append("cone leak: aimed-away window luma=%.4f > %.4f (spot cone did not gate the light)" % [
			float(p1["win_luma"]), TOL_ZERO])
	# (3) raw must be plain albedo AND flashlight must not leak into raw.
	var raw_err := absf(float(p2["luma"]) - ALBEDO)
	if raw_err > TOL_ABS:
		problems.append("raw != albedo: measured=%.4f albedo=%.4f err=%.4f > %.4f" % [
			float(p2["luma"]), ALBEDO, raw_err, TOL_ABS])
	var raw_leak := absf(float(p2["luma"]) - float(p3["luma"]))
	if raw_leak > TOL_RAW:
		problems.append("flashlight leaks into RAW: |raw_on-raw_off|=%.4f > %.4f" % [raw_leak, TOL_RAW])

	var inv_sq_only := ALBEDO * FLASH_ENERGY * (1.0 / (1.0 + CAM_DIST * CAM_DIST))
	print("[flash-gate] CLOSED-FORM near-range: P0 luma=%.4f expected=%.4f (err=%.4f<=%.4f)" % [
		float(p0["luma"]), expected0, err0, TOL_ABS])
	print("[flash-gate] RANGE-WINDOW: P4 luma=%.4f expected=%.4f (err=%.4f<=%.4f) | inv_sq-only would read %.4f" % [
		float(p4["luma"]), expected4, err4, TOL_ABS, inv_sq_only])
	print("[flash-gate] OUT-OF-RANGE: P5 window luma=%.4f (<=%.4f) | inv_sq-only would read %.4f" % [
		float(p5["win_luma"]), TOL_ZERO, inv_sq_only])
	print("[flash-gate] CONE-MISS: P1 window luma=%.4f (<=%.4f)" % [float(p1["win_luma"]), TOL_ZERO])
	print("[flash-gate] RAW: P2(flash on)=%.4f P3(flash off)=%.4f albedo=%.3f raw_err=%.4f raw_leak=%.4f" % [
		float(p2["luma"]), float(p3["luma"]), ALBEDO, raw_err, raw_leak])

	if not problems.is_empty():
		for p in problems:
			push_error("[flash-gate] FAIL: %s" % p)
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
	RelightPass.clear_materials()
	RelightPass.clear_flashlight()
	print("FLASH_GATE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
