extends SceneTree
# Flashlight frame-time probe (real GPU, DISPLAY=:0). Renders the grounded hero asset
# (pxl_144634, ~2.4M splats) at 1080p with a FIXED camera and measures average
# frame time with the flashlight OFF then ON — the point-light term doubles the
# per-splat shading work, so this is the first datapoint for the Moon-Stone fireball
# budget. Reports ms/frame (wall-clock over a fixed window, vsync disabled, matching
# the viewer HUD's fps->ms) for both, and the delta.
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/flashlight_perf.gd
#   RELIGHT_ASSET=res://gs_assets/<name>.relightply overrides the asset.

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightEnvSH = preload("res://relight/relight_env_sh.gd")

const DEFAULT_ASSET := "res://gs_assets/pxl_144634.relightply"
const WARMUP := 60                   # frames to settle before each measurement window
const MEASURE := 240                 # frames per measurement window

const WRAP_POWER := 2.0
const AMBIENT := 0.2
const LIGHT_COLOR := Color(1.0, 0.98, 0.92)
const FLASH_COLOR := Color(1.0, 0.95, 0.86)
const FLASH_INNER_DEG := 14.0
const FLASH_OUTER_DEG := 24.0

var _res
var _cam_pos := Vector3.ZERO
var _center := Vector3.ZERO
var _light_dir := Vector3(0.4, -0.7, 0.5).normalized()
var _flash_pos := Vector3.ZERO
var _flash_dir := Vector3.FORWARD
var _flash_energy := 10.0
var _flash_range := 10.0

var _stage := 0                      # 0 warm(off) 1 meas(off) 2 warm(on) 3 meas(on) 4 done
var _frames := 0
var _t0 := 0
var _ms_off := 0.0
var _ms_on := 0.0


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
		push_error("[flash-perf] load failed: %s" % asset)
		quit(1)
		return
	RelightPass.set_materials(_res.attr_data_byte, _res.point_count)
	RelightPass.set_env_sh(RelightEnvSH.load_coeffs(asset))

	var gs := GaussianSplatNode.new()
	gs.gaussian = _res
	root.add_child(gs)

	var ab: AABB = _res.aabb
	_center = ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.6, 1.0)
	_cam_pos = _center + Vector3(radius, radius * 0.4, radius)
	_flash_pos = _cam_pos
	_flash_dir = (_center - _cam_pos).normalized()
	var d := _cam_pos.distance_to(_center)
	_flash_energy = 2.5 * (1.0 + d * d)
	_flash_range = maxf(d * 4.0, 10.0)

	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(_cam_pos, _center, Vector3.UP)
	cam.current = true

	print("[flash-perf] asset=%s splats=%d res=1920x1080 measure=%d frames/window" % [
		asset, _res.point_count, MEASURE])


func _process(_delta: float) -> bool:
	if _res == null:
		return true
	var flash_on := _stage >= 2
	RelightPass.set_light(_light_dir, LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)
	RelightPass.set_flashlight(flash_on, _flash_pos, _flash_dir, FLASH_COLOR, _flash_energy,
		_flash_range, FLASH_INNER_DEG, FLASH_OUTER_DEG)

	# Warm-up stages (0, 2): just settle, then start the timer.
	if _stage == 0 or _stage == 2:
		_frames += 1
		if _frames >= WARMUP:
			_frames = 0
			_t0 = Time.get_ticks_usec()
			_stage += 1
		return false

	# Measurement stages (1, 3): time a fixed window of frames.
	_frames += 1
	if _frames < MEASURE:
		return false
	var elapsed_us := Time.get_ticks_usec() - _t0
	var ms := float(elapsed_us) / 1000.0 / float(MEASURE)
	if _stage == 1:
		_ms_off = ms
		print("[flash-perf] flashlight OFF: %.3f ms/frame (%.1f fps)" % [ms, 1000.0 / ms])
		_frames = 0
		_stage = 2
		return false
	else:
		_ms_on = ms
		print("[flash-perf] flashlight ON : %.3f ms/frame (%.1f fps)" % [ms, 1000.0 / ms])
		print("[flash-perf] DELTA: +%.3f ms/frame (%.1f%%) for the point-light term" % [
			_ms_on - _ms_off, 100.0 * (_ms_on - _ms_off) / maxf(_ms_off, 1e-3)])
		RelightPass.clear_materials()
		RelightPass.clear_env_sh()
		RelightPass.clear_flashlight()
		quit(0)
		return true
