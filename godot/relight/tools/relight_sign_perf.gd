extends SceneTree
# D7 sign-mode frame-time probe (real GPU, DISPLAY=:0). Renders the grounded hero asset
# (pxl_144634, ~2.4M splats) at 1080p with a FIXED camera and measures average ms/frame
# for each sign_mode (0 signed / 1 sign-free wrap / 2 flip-toward-camera). The lobe adds
# only a branch + (mode 2) a normalize on the already-computed splat world pos, so the
# expectation is "~free". Mirrors flashlight_perf's warm/measure windowing.
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/relight_sign_perf.gd
#   RELIGHT_ASSET=res://gs_assets/<name>.vply overrides the asset.

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const DEFAULT_ASSET := "res://gs_assets/pxl_144634.vply"
const WARMUP := 60
const MEASURE := 240

const WRAP_POWER := 2.0
const AMBIENT := 0.2
const LIGHT_COLOR := Color(1.0, 0.98, 0.92)
const SIGN_NAMES := ["signed", "sign-free wrap", "flip-to-cam"]

var _res
var _cam_pos := Vector3.ZERO
var _center := Vector3.ZERO
var _light_dir := Vector3(0.4, -0.7, 0.5).normalized()

var _mode_idx := 0                   # which sign mode we are timing (0..2)
var _stage := 0                      # 0 warm, 1 measure (per mode)
var _frames := 0
var _t0 := 0
var _ms := [0.0, 0.0, 0.0]


func _initialize() -> void:
	DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	var root := get_root()
	root.size = Vector2i(1920, 1080)

	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.10, 0.11, 0.14)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.35, 0.35, 0.38)
	env.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	root.add_child(we)

	var asset := OS.get_environment("RELIGHT_ASSET")
	if asset.is_empty():
		asset = DEFAULT_ASSET
	_res = RelightPlyLoader.load(asset)
	if _res == null:
		push_error("[sign-perf] load failed: %s" % asset)
		quit(1)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)
	RelightPass.set_env_sh(RelightEnvSH.load_coeffs(asset))
	RelightPass.clear_flashlight()

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)

	var ab: AABB = _res.aabb
	_center = ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.6, 1.0)
	_cam_pos = _center + Vector3(radius, radius * 0.4, radius)

	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(_cam_pos, _center, Vector3.UP)
	cam.current = true
	RelightPass.set_camera_pos(_cam_pos)
	RelightPass.set_sign_wrap(0.4)

	print("[sign-perf] asset=%s splats=%d res=1920x1080 measure=%d frames/mode" % [
		asset, _res.point_count, MEASURE])


func _process(_delta: float) -> bool:
	if _res == null:
		return true
	RelightPass.set_light(_light_dir, LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
	RelightPass.set_camera_pos(_cam_pos)
	RelightPass.set_sign_mode(_mode_idx)

	if _stage == 0:
		_frames += 1
		if _frames >= WARMUP:
			_frames = 0
			_t0 = Time.get_ticks_usec()
			_stage = 1
		return false

	_frames += 1
	if _frames < MEASURE:
		return false
	var ms := float(Time.get_ticks_usec() - _t0) / 1000.0 / float(MEASURE)
	_ms[_mode_idx] = ms
	print("[sign-perf] mode %d (%s): %.3f ms/frame (%.1f fps)" % [
		_mode_idx, SIGN_NAMES[_mode_idx], ms, 1000.0 / ms])
	_frames = 0
	_stage = 0
	_mode_idx += 1
	if _mode_idx >= SIGN_NAMES.size():
		print("[sign-perf] SUMMARY signed=%.3f wrap=%.3f flip=%.3f ms/frame | wrap-signed=%+.3f flip-signed=%+.3f" % [
			_ms[0], _ms[1], _ms[2], _ms[1] - _ms[0], _ms[2] - _ms[0]])
		RelightPass.clear_materials()
		RelightPass.clear_env_sh()
		RelightPass.set_sign_mode(0)
		quit(0)
		return true
	return false
