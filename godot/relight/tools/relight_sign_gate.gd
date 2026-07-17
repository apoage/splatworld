extends SceneTree
# D7 sign-agnostic prototype ANALYTIC gate (real GPU, DISPLAY=:0). Like
# relight_flashlight_gate.gd this builds a SYNTHETIC splat cluster with a KNOWN normal,
# kills ambient + back terms, and asserts the rendered luma equals the CLOSED-FORM
# direct lobe for each sign_mode (docs/d7-synthesis-2026-07-17.md). Because the material
# normal lives in OUR material buffer (not the GDGS geometry), each phase just re-registers
# the cluster with a new normal — one node, one camera. The node transform is NOT reset
# (see the NOTE at the add_child site): GDGS's default -PI Z node correction rotates about Z
# (±X/±Y flip, ±Z invariant), and ALL phases use ±Z normals + ±Z lights, so the correction
# leaves the closed form unaffected — keeping N = normal_obj exactly for the gate.
#
# Geometry: camera + view dir V on +Z at (0,0,CAM_DIST) aimed at origin. All normals +
# lights are on the ±Z axis (invariant under GDGS's -PI Z node correction). luma =
# ALBEDO * direct (light_color = white*1, ambient 0, trans 0). Phases + fault role:
#   P0 mode0 signed  N=+Z, L=+Z (front-lit)  -> direct=1                 baseline (signed still works)
#   P1 mode1 wrap    N=+Z, L=-Z (BACK-lit)   -> direct=1/(1+w)=0.714     FAULT: drop abs => dot<0 => 0 (dark)
#                                                                         FAULT: drop wrap-norm => plain abs => 1.0
#   P2 mode2 flip    N=-Z, L=+Z, V=+Z        -> flip N to +Z, direct=1   FAULT: drop flip => signed dot=-1 => 0 (dark)
#   P3 RAW  sign=2                            -> albedo                   raw invariant to sign_mode
#   P4 RAW  sign=1                            -> albedo                   raw invariant to sign_mode
#   P5 RAW  sign=0                            -> albedo == P3 == P4       raw invariant to sign_mode
# The BACK-lit / BACK-facing normals in P1/P2 are the discriminators: a signed lobe reads
# ZERO there, so breaking the abs (P1) or the flip (P2) makes the closed-form check fail.
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/relight_sign_gate.gd
#   RELIGHT_SHOT_DIR=/abs/dir  -> also writes one PNG per phase (eyeball only).

const RelightPass = preload("res://relight/relight_pass.gd")
const RelightGaussianResourceScript = preload("res://relight/relight_gaussian_resource.gd")
const GaussianResourceBuilder = preload("res://addons/gdgs/importers/builders/gaussian_resource_builder.gd")

const SH_C0 := 0.28209479177387814

# --- synthetic splat cluster (mirrors relight_flashlight_gate: many small splats fill a
# disk so the alpha composite saturates and the covered mean == splat color) ---
const N_SPLATS := 4000
const SPLAT_SCALE := 0.02
const SPLAT_SPREAD := 0.15
const SPLAT_SPREAD_Z := 0.005
const SPLAT_OPACITY := 0.9
const ALBEDO := 0.6
const ROUGH := 0.5

# --- camera / sign params (world) ---
const CAM_DIST := 1.0                 # camera + V on +Z axis, aimed at origin
const SIGN_WRAP_W := 0.4              # mode 1 wrap w (task default ~0.4)

const BG := Color(0.0, 0.0, 0.0)      # black -> composited color = splat_color * alpha
const SETTLE := 40                    # cold shader-pipeline cache warmup (matches other gates)
const WIN := 40                       # half-size of the central sampling window (px)
const MIN_COVERED := 400
const N_PHASES := 6

const TOL_ABS := 0.03                 # closed-form / albedo absolute tolerance
const TOL_RAW := 0.02                 # raw-invariance bound across sign modes

var _phase := 0
var _frames := 0
var _shot_dir := ""
var _measures := []
var _ready := false
var _res

# expected closed-form luma per phase (filled in _initialize)
var _expected := []


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

	_res = _build_synthetic()
	if _res == null:
		push_error("[sign-gate] synthetic asset build failed")
		_finish(false)
		return
	# initial material normal is set per-phase in _apply_phase; register something now.
	_set_material_normal(Vector3(0.0, 1.0, 0.0))
	RelightPass.clear_env_sh()
	RelightPass.clear_flashlight()
	RelightPass.set_camera_pos(Vector3(0.0, 0.0, CAM_DIST))
	RelightPass.set_sign_wrap(SIGN_WRAP_W)

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)
	# NOTE: like relight_flashlight_gate we do NOT reset the transform. GDGS applies its
	# default -PI Z node correction (rotation about Z: ±X/±Y flip, ±Z invariant). ALL
	# phases use ±Z normals + ±Z lights, which that rotation leaves invariant, so the
	# closed form is unaffected. (Resetting to IDENTITY after add_child does not rebuild
	# GDGS's already-built instance-transform buffer, so the correction still applied.)

	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(Vector3(0.0, 0.0, CAM_DIST), Vector3.ZERO, Vector3.UP)
	cam.current = true

	var wrap_front := clampf((1.0 + SIGN_WRAP_W) / (1.0 + SIGN_WRAP_W), 0.0, 1.0) / (1.0 + SIGN_WRAP_W)
	_expected = [
		ALBEDO * 1.0,          # P0 signed, front-lit
		ALBEDO * wrap_front,   # P1 wrap, back-lit (|dot|=1)
		ALBEDO * 1.0,          # P2 flip, back-facing camera -> flipped, direct=1
		ALBEDO,                # P3 raw sign=2
		ALBEDO,                # P4 raw sign=1
		ALBEDO,                # P5 raw sign=0
	]
	_ready = true
	print("[sign-gate] synthetic splats=%d albedo=%.3f wrap_w=%.2f | expected P1(wrap back)=%.4f" % [
		_res.point_count, ALBEDO, SIGN_WRAP_W, float(_expected[1])])


func _build_synthetic():
	var canonical := GaussianResourceBuilder.create_canonical(N_SPLATS)
	var positions: PackedVector3Array = canonical["positions"]
	var scales: PackedVector3Array = canonical["scales_linear"]
	var rotations: Array = canonical["rotations"]
	var opacities: PackedFloat32Array = canonical["opacities"]
	var sh: PackedFloat32Array = canonical["sh_coeffs"]
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

	var res := RelightGaussianResourceScript.new()
	res.point_count = base.point_count
	res.point_data_float = base.point_data_float
	res.point_data_byte = base.point_data_byte
	res.xyz = base.xyz
	res.aabb = base.aabb
	res.relight_schema_version = 1
	# attr filled by _set_material_normal (needs base.xyz for centered positions).
	res.attr_data_byte = PackedByteArray()
	return res


# Re-pack the material buffer with a uniform normal (albedo/rough/trans fixed). Only the
# normal changes between phases; the GDGS geometry stays put, so this is a cheap
# set_materials -> buffer_update (no pipeline rebuild).
func _set_material_normal(normal: Vector3) -> void:
	var centered: PackedVector3Array = _res.xyz
	var attr := PackedFloat32Array()
	attr.resize(N_SPLATS * 12)
	for i in N_SPLATS:
		var m := i * 12
		attr[m + 0] = ALBEDO
		attr[m + 1] = ALBEDO
		attr[m + 2] = ALBEDO
		attr[m + 3] = ROUGH
		attr[m + 4] = normal.x
		attr[m + 5] = normal.y
		attr[m + 6] = normal.z
		attr[m + 7] = 0.0            # trans
		attr[m + 8] = centered[i].x
		attr[m + 9] = centered[i].y
		attr[m + 10] = centered[i].z
		attr[m + 11] = 0.0           # label
	var bytes := attr.to_byte_array()
	_res.attr_data_byte = bytes
	RelightPass.set_materials(bytes, N_SPLATS)


func _apply_phase() -> void:
	var white := Color(1.0, 1.0, 1.0)  # energy 1 baked into light_color
	# All configs on the ±Z axis (invariant under GDGS's -PI Z node correction). L =
	# normalize(-light_dir_ws), so light_dir_ws=(0,0,-1) => L=+Z, (0,0,1) => L=-Z.
	match _phase:
		0: # signed, FRONT-lit (N=+Z, L=+Z): direct = dot = 1
			_set_material_normal(Vector3(0.0, 0.0, 1.0))
			RelightPass.set_sign_mode(0)
			RelightPass.set_light(Vector3(0.0, 0.0, -1.0), white, 2.0, 0.0, RelightPass.MODE_RELIT, false)
		1: # sign-free wrap, BACK-lit (N=+Z, L=-Z): |dot|=1 -> abs makes it visible
			_set_material_normal(Vector3(0.0, 0.0, 1.0))
			RelightPass.set_sign_mode(1)
			RelightPass.set_light(Vector3(0.0, 0.0, 1.0), white, 2.0, 0.0, RelightPass.MODE_RELIT, false)
		2: # flip-toward-camera, BACK-facing camera (N=-Z, V=+Z, L=+Z): flip lights it
			_set_material_normal(Vector3(0.0, 0.0, -1.0))
			RelightPass.set_sign_mode(2)
			RelightPass.set_light(Vector3(0.0, 0.0, -1.0), white, 2.0, 0.0, RelightPass.MODE_RELIT, false)
		3: # RAW with sign=2 -> plain albedo (raw invariant to sign_mode)
			_set_material_normal(Vector3(0.0, 0.0, -1.0))
			RelightPass.set_sign_mode(2)
			RelightPass.set_light(Vector3(0.0, 0.0, -1.0), white, 2.0, 0.0, RelightPass.MODE_RAW, false)
		4: # RAW with sign=1 -> plain albedo
			_set_material_normal(Vector3(0.0, 0.0, 1.0))
			RelightPass.set_sign_mode(1)
			RelightPass.set_light(Vector3(0.0, 0.0, 1.0), white, 2.0, 0.0, RelightPass.MODE_RAW, false)
		5: # RAW with sign=0 -> plain albedo (== P3 == P4)
			_set_material_normal(Vector3(0.0, 0.0, 1.0))
			RelightPass.set_sign_mode(0)
			RelightPass.set_light(Vector3(0.0, 0.0, -1.0), white, 2.0, 0.0, RelightPass.MODE_RAW, false)


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
		push_error("[sign-gate] empty viewport image (phase %d)" % _phase)
		_finish(false)
		return true

	var m := _measure(img)
	_measures.append(m)
	print("[sign-gate] phase %d: covered=%d luma=%.4f (expected=%.4f)" % [
		_phase, m["covered"], m["luma"], float(_expected[_phase])])
	if not _shot_dir.is_empty():
		img.save_png(_shot_dir.path_join("sign_gate_p%d.png" % _phase))

	_phase += 1
	_frames = 0
	if _phase >= N_PHASES:
		return _evaluate()
	return false


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
		"luma": 0.2126 * r + 0.7152 * g + 0.0722 * b,
		# window (unmasked) luma so a fully-dark frame (fault-injected) is measurable.
		"win_luma": win_lum / float(maxi(win_n, 1)),
	}


func _evaluate() -> bool:
	var problems: Array[String] = []
	for i in N_PHASES:
		if int(_measures[i]["covered"]) < MIN_COVERED and i < 3:
			# lit phases must render; raw phases (3-5) also render but assert on luma below.
			problems.append("phase %d covered=%d < %d (splat did not render)" % [i, int(_measures[i]["covered"]), MIN_COVERED])

	# Closed-form direct lobe per mode. The BACK-lit/back-facing P1/P2 are the
	# discriminators: a broken abs (P1) or a removed flip (P2) reads ~0 here.
	for i in 3:
		var err := absf(float(_measures[i]["luma"]) - float(_expected[i]))
		if err > TOL_ABS:
			problems.append("mode %d closed-form off: measured=%.4f expected=%.4f err=%.4f > %.4f" % [
				i, float(_measures[i]["luma"]), float(_expected[i]), err, TOL_ABS])

	# Raw invariance to sign_mode: RAW under sign=2/1/0 must all be plain albedo AND equal.
	for i in [3, 4, 5]:
		var err := absf(float(_measures[i]["luma"]) - ALBEDO)
		if err > TOL_ABS:
			problems.append("raw!=albedo (sign phase %d): measured=%.4f albedo=%.3f err=%.4f > %.4f" % [
				i, float(_measures[i]["luma"]), ALBEDO, err, TOL_ABS])
	var raw_spread := maxf(
		absf(float(_measures[3]["luma"]) - float(_measures[5]["luma"])),
		absf(float(_measures[4]["luma"]) - float(_measures[5]["luma"])))
	if raw_spread > TOL_RAW:
		problems.append("raw NOT invariant to sign_mode: spread=%.4f > %.4f (raw output depends on sign mode)" % [
			raw_spread, TOL_RAW])

	print("[sign-gate] CLOSED-FORM: P0 signed=%.4f (exp %.4f) | P1 wrap-back=%.4f (exp %.4f) | P2 flip-back=%.4f (exp %.4f)" % [
		float(_measures[0]["luma"]), float(_expected[0]),
		float(_measures[1]["luma"]), float(_expected[1]),
		float(_measures[2]["luma"]), float(_expected[2])])
	print("[sign-gate] RAW-INVARIANCE: sign2=%.4f sign1=%.4f sign0=%.4f albedo=%.3f spread=%.4f (<=%.4f)" % [
		float(_measures[3]["luma"]), float(_measures[4]["luma"]), float(_measures[5]["luma"]),
		ALBEDO, raw_spread, TOL_RAW])

	if not problems.is_empty():
		for p in problems:
			push_error("[sign-gate] FAIL: %s" % p)
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
	RelightPass.set_sign_mode(0)
	print("SIGN_GATE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
