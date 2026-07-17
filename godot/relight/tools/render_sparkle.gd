extends SceneTree
# DIAGNOSTIC sparkle-capture tool (NEW; sibling to render_orbit.gd, added for the
# normal-quality DIAGNOSIS task 2026-07-13). Renders a SINGLE-MODE full orbit so RAW
# and RELIT sequences are comparable frame-for-frame, then quits. This tool does NO
# measurement / pass-fail gate: it is a pure PNG frame dumper. The sparkle metric is
# computed OFFLINE in Python over the PNGs (can run headless/CPU); see
# docs/validation-normal-quality-diagnosis-2026-07-14.md.
#
# WHY a new tool instead of render_orbit.gd: render_orbit does a 30-frame-RAW-then-
# 150-frame-RELIT split with a tuned pass/fail summary (std / cut_mad floors). For the
# attribution we need each variant to be a FULL orbit in ONE mode with an IDENTICAL
# light path, and no gate. Rather than mutate the gated demo tool, this borrows its
# proven GPU/scene setup (WorldEnvironment + GaussianCompositorEffect + RelightPass
# wiring + settle cadence) verbatim.
#
# MUST run on the real GPU (NO --headless; --headless = dummy renderer = empty
# viewport). The camera is STATIC; only the light orbits — so a RAW capture (baked,
# light-independent appearance) is pixel-identical every frame EXCEPT for any renderer
# non-determinism (sort ties / readback jitter). That makes RAW the sort/aliasing
# baseline and RELIT-minus-RAW the shading-induced sparkle.
#
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/render_sparkle.gd
#   RELIGHT_ASSET=res://gs_assets/foo.relightply  -> asset to load (default pxl_144634).
#                                                    Absolute OS paths also accepted.
#   RELIGHT_SPARKLE_MODE=raw|relit                -> single render mode (default relit).
#   RELIGHT_SHOT_DIR=/abs/dir                     -> frames -> frame_%04d.png (required).
#   RELIGHT_ORBIT_FRAMES=72                        -> total frames = one azimuth turn.
#   RELIGHT_NO_ENV_SH=1                            -> force flat-ambient (RelightEnvSH honours it).

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const DEFAULT_ASSET := "res://gs_assets/pxl_144634.relightply"

const RES := Vector2i(1280, 720)       # match render_orbit framing exactly
const BG := Color(0.06, 0.07, 0.09)    # dark neutral; same coverage-mask reference
const AMBIENT := 0.2                    # flat-ambient fallback (only if no env-SH sidecar)
const WRAP_POWER := 2.0
const LIGHT_COLOR := Color(1.0, 1.0, 1.0)

const DEFAULT_N := 72                   # one full azimuth turn (5deg steps)
const SETTLE_INITIAL := 40              # warm-up frames before the first capture
const SETTLE_PER_FRAME := 3             # render frames per light change (kills readback lag)

# Same elevation sweep as render_orbit so the RELIT capture matches the demo the owner
# saw sparkling: azimuth completes one 360deg turn WHILE elevation rises grazing->
# overhead->grazing once.
const EL_MID := 45.0
const EL_AMP := 35.0

var _asset_path := DEFAULT_ASSET
var _mode := RelightPass.MODE_RELIT
var _mode_name := "relit"
var _n := DEFAULT_N

var _res
var _shot_dir := ""
var _has_env := false
var _env_coeffs := PackedFloat32Array()

var _idx := -1
var _settle := 0
var _warmed := false


func _envi(name: String, dflt: int) -> int:
	var v := OS.get_environment(name)
	return int(v) if v.is_valid_int() else dflt


func _initialize() -> void:
	_n = maxi(_envi("RELIGHT_ORBIT_FRAMES", DEFAULT_N), 3)  # need >=3 for a 2nd difference

	var mode_env := OS.get_environment("RELIGHT_SPARKLE_MODE").strip_edges().to_lower()
	if mode_env == "raw":
		_mode = RelightPass.MODE_RAW
		_mode_name = "raw"
	else:
		_mode = RelightPass.MODE_RELIT
		_mode_name = "relit"

	var a := OS.get_environment("RELIGHT_ASSET").strip_edges()
	if not a.is_empty():
		_asset_path = a

	_shot_dir = _resolve_shot_dir()
	if _shot_dir.is_empty():
		push_error("[sparkle] no RELIGHT_SHOT_DIR / output dir given")
		quit(1)
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

	_res = RelightPlyLoader.load(_asset_path)
	if _res == null:
		push_error("[sparkle] load failed: %s" % _asset_path)
		quit(1)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)

	# env-SH ambient (set ONCE; RAW ignores it in-shader, RELIT consumes it).
	_env_coeffs = RelightEnvSH.load_coeffs(_asset_path)
	_has_env = _env_coeffs.size() == RelightEnvSH.N_COEFFS * 3
	if _has_env:
		RelightPass.set_env_sh(_env_coeffs)
	else:
		RelightPass.clear_env_sh()
	print("[sparkle] env-SH ambient: %s" % ("env-SH sidecar" if _has_env else "FLAT fallback (no/invalid sidecar)"))

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)
	gs.transform = Transform3D.IDENTITY   # D3 rule: suppress GDGS's conditional -180deg Z flip on our
	                                      # already-Godot-convention .relightply (else grounded assets render upside down)

	var ab: AABB = _res.aabb
	var center := ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.7, 1.0)
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(center + Vector3(radius, radius * 0.45, radius), center, Vector3.UP)
	cam.current = true

	print("[sparkle] asset=%s splats=%d aabb=%s mode=%s N=%d out=%s" % [
		_asset_path, _res.point_count, ab, _mode_name, _n, _shot_dir])


# Light-TRAVEL direction (world) for frame i, orbiting over the FULL [0, N) range so
# frame i has the same light in RAW and RELIT captures (RAW ignores it anyway).
func _travel_dir(i: int) -> Vector3:
	var t := float(i) / float(_n)                     # 0 .. just under 1
	var az := TAU * t
	var el := deg_to_rad(EL_MID) - deg_to_rad(EL_AMP) * cos(TAU * t)
	var from := Vector3(cos(el) * cos(az), sin(el), cos(el) * sin(az))  # where light comes FROM
	return -from


func _apply_frame(i: int) -> void:
	RelightPass.set_light(_travel_dir(i).normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, _mode, false)


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
		push_error("[sparkle] empty viewport image (frame %d) -- forgot DISPLAY=:0 / passed --headless?" % _idx)
		quit(1)
		return true

	var fpath := _shot_dir.path_join("frame_%04d.png" % _idx)
	var err := img.save_png(fpath)
	if err != OK or not FileAccess.file_exists(fpath):
		push_error("[sparkle] save_png FAILED err=%d -> %s" % [err, fpath])
		quit(1)
		return true

	print("[sparkle] frame %04d mode=%s" % [_idx, _mode_name])

	_idx += 1
	if _idx >= _n:
		print("SPARKLE_CAPTURE_DONE frames=%d mode=%s out=%s" % [_idx, _mode_name, _shot_dir])
		quit(0)
		return true
	_apply_frame(_idx)
	return false


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
