extends "res://relight/relight_controller.gd"

# Lighting-lab viewer on top of the M2a demo controller.
# Camera: left-drag orbits, wheel zooms.
# Light:  right-drag places the sun manually (pauses the auto orbit),
#         SPACE pauses/resumes the auto orbit, C runs a sunrise->sunset day cycle,
#         1-4 condition presets (noon / golden hour / overcast / moonlight),
#         5 = backlit (sun opposite the camera — the M3 transmission pose),
#         +/- light energy, [ ] ambient, , . wrap power, R reset to defaults.
# The base class's UI toggles (raw/relit, transmission) keep working. Launch:
#   DISPLAY=:0 ~/godot/godot --path godot res://scenes/viewer.tscn

const DAY_CYCLE_SECONDS := 24.0

# Camera-attached flashlight (F). Warm white, tight-ish spot. Energy scales with the
# orbit distance so the lit focal point stays roughly constant brightness as you zoom
# (inverse-square falloff -> energy ~ (1 + d^2)). Cone: full inside inner, fades to 0
# by outer. The reference orb's engine SpotLight3D mirrors these exact params.
const FLASH_COLOR := Color(1.0, 0.95, 0.86)
const FLASH_INNER_DEG := 14.0
const FLASH_OUTER_DEG := 24.0
const FLASH_BRIGHTNESS := 2.5

# Reference orb (O): a gray Lambert sphere, engine-lit by the SAME DirectionalLight3D,
# a live cross-model reference for the eyeball. Offset from the AABB center.
const ORB_ALBEDO := Color(0.5, 0.5, 0.5)
const ORB_ROUGHNESS := 0.8

const PRESETS := {
	KEY_1: {"name": "noon", "el": 1.2, "color": Color(1.0, 1.0, 1.0), "energy": 1.0, "amb": 0.25},
	KEY_2: {"name": "golden hour", "el": 0.15, "color": Color(1.0, 0.62, 0.35), "energy": 1.1, "amb": 0.12},
	KEY_3: {"name": "overcast", "el": 0.9, "color": Color(0.75, 0.78, 0.82), "energy": 0.5, "amb": 0.5},
	KEY_4: {"name": "moonlight", "el": 0.7, "color": Color(0.55, 0.65, 0.9), "energy": 0.15, "amb": 0.06},
}

var _cam: Camera3D
var _center := Vector3.ZERO
var _dist := 3.0
var _yaw := 0.6
var _pitch := 0.35
var _dragging := false

var _light_paused := false
var _light_dragging := false
var _day_cycle := false
var _cycle_t := 0.0
var _condition := "orbit"
var _sun_az := 0.0
var _sun_el := 0.6
var _energy := 1.0
var _amb := AMBIENT
var _wrap := WRAP_POWER
var _color := LIGHT_COLOR

# D7 sign-agnostic prototype (key N cycles): 0 signed (shipped) / 1 sign-free wrap /
# 2 flip-toward-camera. Mode 3 (confidence blend) is SKIPPED — the pass cannot reach
# per-splat covariance scales without extending the material buffer (task Gate: do not
# extend the buffer for a prototype). `_sign_wrap` is mode 1's wrap w (,/. tweak it live
# while in mode 1; otherwise ,/. keep adjusting the back-term wrap_power as before).
const SIGN_NAMES := ["signed", "sign-free wrap", "flip-to-cam"]
var _sign_mode := 0
var _sign_wrap := 0.4

# Diagnostic isolation toggles (owner debugging of the relit energy budget):
# V = env-SH ambient on/off (off -> flat AMBIENT fallback), A = sun off
# (ambient term only), D = ambient off (direct sun term only).
var _env_coeffs := PackedFloat32Array()
var _env_on := true
var _sun_off := false
var _amb_off := false

# Flashlight (F) + reference orb (O).
var _flash_on := false
var _flash_range := 6.0
var _orb: MeshInstance3D
var _orb_light: SpotLight3D


func _ready() -> void:
	super()
	for c in get_children():
		if c is Camera3D:
			_cam = c
	if _cam != null and _splat != null:
		var ab: AABB = _splat.gaussian.aabb
		_center = ab.position + ab.size * 0.5
		_dist = maxf(ab.size.length() * 0.9, 1.0)
		_flash_range = maxf(ab.size.length() * 2.0, 6.0)
		_update_cam()
		_build_orb(ab)
		_build_flash_engine_light()
	# Cache the sidecar coeffs (same path logic as the controller) so V can
	# re-bind after a clear. Empty => no sidecar => V is a no-op.
	var asset_path := OS.get_environment("RELIGHT_ASSET")
	if asset_path.is_empty():
		asset_path = ASSET_PATH
	_env_coeffs = RelightEnvSH.load_coeffs(asset_path)
	_env_on = not _env_coeffs.is_empty()


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton:
		match e.button_index:
			MOUSE_BUTTON_LEFT:
				_dragging = e.pressed
			MOUSE_BUTTON_RIGHT:
				_light_dragging = e.pressed
				if e.pressed:
					_hold_light("manual")
			MOUSE_BUTTON_WHEEL_UP:
				if e.pressed:
					_dist = maxf(_dist * 0.9, 0.2)
					_update_cam()
			MOUSE_BUTTON_WHEEL_DOWN:
				if e.pressed:
					_dist *= 1.1
					_update_cam()
	elif e is InputEventMouseMotion:
		if _dragging:
			_yaw -= e.relative.x * 0.008
			_pitch = clampf(_pitch + e.relative.y * 0.008, -1.45, 1.45)
			_update_cam()
		elif _light_dragging:
			_sun_az -= e.relative.x * 0.008
			_sun_el = clampf(_sun_el - e.relative.y * 0.008, 0.03, 1.45)
	elif e is InputEventKey and e.pressed:
		match e.keycode:
			KEY_SPACE:
				_day_cycle = false
				_light_paused = not _light_paused
				_condition = "paused" if _light_paused else "orbit"
			KEY_C:
				_day_cycle = not _day_cycle
				if not _day_cycle:
					_light_paused = true
					_condition = "paused"
			KEY_R:
				_day_cycle = false
				_light_paused = false
				_condition = "orbit"
				_sun_el = 0.6
				_energy = 1.0
				_amb = AMBIENT
				_wrap = WRAP_POWER
				_color = LIGHT_COLOR
				_sun_off = false
				_amb_off = false
				_sign_mode = 0
				_sign_wrap = 0.4
				RelightPass.set_sign_mode(0)
				if not _env_on and not _env_coeffs.is_empty():
					RelightPass.set_env_sh(_env_coeffs)
					_env_on = true
			KEY_V:
				if _env_coeffs.is_empty():
					_condition = "no env sidecar"
				else:
					_env_on = not _env_on
					if _env_on and not _amb_off:
						RelightPass.set_env_sh(_env_coeffs)
					else:
						RelightPass.clear_env_sh()
			KEY_A:
				_sun_off = not _sun_off
			KEY_D:
				_amb_off = not _amb_off
				if _amb_off:
					RelightPass.clear_env_sh()
				elif _env_on and not _env_coeffs.is_empty():
					RelightPass.set_env_sh(_env_coeffs)
			KEY_F:
				_flash_on = not _flash_on
			KEY_O:
				if _orb != null:
					_orb.visible = not _orb.visible
			KEY_N:
				# D7: cycle the sign-agnostic shading mode live (HUD shows it).
				_sign_mode = (_sign_mode + 1) % SIGN_NAMES.size()
				RelightPass.set_sign_mode(_sign_mode)
			KEY_5:
				# Backlit: sun directly opposite the camera, low over the horizon.
				_hold_light("backlit")
				_sun_az = _yaw + PI
				_sun_el = 0.15
				_color = Color(1.0, 0.7, 0.45)
				_energy = 1.2
				_amb = 0.08
			KEY_EQUAL:
				_energy = minf(_energy * 1.25, 8.0)
			KEY_MINUS:
				_energy = maxf(_energy / 1.25, 0.02)
			KEY_BRACKETLEFT:
				_amb = maxf(_amb - 0.03, 0.0)
			KEY_BRACKETRIGHT:
				_amb = minf(_amb + 0.03, 1.0)
			KEY_COMMA:
				if _sign_mode == 1:
					_sign_wrap = maxf(_sign_wrap - 0.05, 0.0) # mode 1: tweak sign-free wrap w
				else:
					_wrap = maxf(_wrap - 0.25, 0.25)
			KEY_PERIOD:
				if _sign_mode == 1:
					_sign_wrap = minf(_sign_wrap + 0.05, 4.0)
				else:
					_wrap = minf(_wrap + 0.25, 8.0)
			_:
				if PRESETS.has(e.keycode):
					var p: Dictionary = PRESETS[e.keycode]
					_hold_light(p["name"])
					_sun_el = p["el"]
					_color = p["color"]
					_energy = p["energy"]
					_amb = p["amb"]


# Full override of the base light orbit: same ONE directional light + per-frame
# RelightPass.set_light, but azimuth/elevation/color/energy/ambient/wrap are live.
func _process(delta: float) -> void:
	if _light == null:
		return
	if _day_cycle:
		_condition = "day-cycle"
		_cycle_t = fmod(_cycle_t + delta / DAY_CYCLE_SECONDS, 1.0)
		var elfrac := sin(_cycle_t * PI) # sunrise -> noon -> sunset, then wrap
		_sun_el = maxf(elfrac * 1.25, 0.03)
		_sun_az += delta * 0.15
		_color = Color(1.0, 0.55, 0.30).lerp(Color(1.0, 0.99, 0.95), elfrac)
		_energy = 0.25 + 0.85 * elfrac
		_amb = 0.06 + 0.2 * elfrac
	elif not _light_paused:
		_sun_az += delta * ORBIT_SPEED
	var sun := Vector3(
		cos(_sun_el) * sin(_sun_az),
		sin(_sun_el),
		cos(_sun_el) * cos(_sun_az)
	)
	_light.look_at_from_position(Vector3.ZERO, -sun, Vector3.UP)
	var light_dir_ws := -_light.global_transform.basis.z
	var eff_energy := 0.0 if _sun_off else _energy
	var eff_amb := 0.0 if _amb_off else _amb
	RelightPass.set_light(light_dir_ws, _color * eff_energy, _wrap, eff_amb, _mode, _trans_on)
	# D7 sign-agnostic prototype: push the camera world pos (mode 2 flip-toward-camera),
	# the sign wrap w (mode 1), and the active sign mode every frame (camera moves).
	if _cam != null:
		RelightPass.set_camera_pos(_cam.global_position)
	RelightPass.set_sign_wrap(_sign_wrap)
	RelightPass.set_sign_mode(_sign_mode)
	_update_flashlight()
	_refresh_hud()


# Camera-attached flashlight: world pos = camera pos, dir = camera forward. Energy
# scales with distance so the focal point stays roughly constant as you zoom. The
# engine SpotLight3D (orb reference) is a child of the camera, so it tracks pos/dir
# automatically — we only toggle its visibility with the flashlight state.
func _update_flashlight() -> void:
	if _cam == null:
		return
	var cam_pos := _cam.global_position
	var cam_fwd := -_cam.global_transform.basis.z
	var flash_energy := FLASH_BRIGHTNESS * (1.0 + _dist * _dist)
	RelightPass.set_flashlight(_flash_on, cam_pos, cam_fwd, FLASH_COLOR, flash_energy,
		_flash_range, FLASH_INNER_DEG, FLASH_OUTER_DEG)
	if _orb_light != null:
		_orb_light.visible = _flash_on


func _hold_light(condition: String) -> void:
	_day_cycle = false
	_light_paused = true
	_condition = condition


func _refresh_hud() -> void:
	_set_status(
		"fps=%d  frame=%.1fms  splats=%s\n" % [
			Engine.get_frames_per_second(),
			1000.0 / maxf(Engine.get_frames_per_second(), 1.0),
			str(_splat.gaussian.point_count) if _splat != null and _splat.gaussian != null else "?",
		]
		+ "mode=%s%s  env=%s%s%s  flash=%s  orb=%s  sun az=%d° el=%d°  E=%.2f  amb=%.2f  wrap=%.2f  [%s]\n" % [
			"relit" if _mode == RelightPass.MODE_RELIT else "RAW ALBEDO",
			"+trans" if _trans_on else "",
			("none" if _env_coeffs.is_empty() else ("SH" if _env_on else "flat")),
			"  SUN-OFF" if _sun_off else "",
			"  AMB-OFF" if _amb_off else "",
			"on" if _flash_on else "off",
			("on" if (_orb != null and _orb.visible) else "off"),
			roundi(wrapf(rad_to_deg(_sun_az), 0.0, 360.0)), roundi(rad_to_deg(_sun_el)),
			_energy, _amb, _wrap, _condition,
		]
		+ "D7 sign=%d:%s%s\n" % [
			_sign_mode, SIGN_NAMES[_sign_mode],
			("  w=%.2f" % _sign_wrap) if _sign_mode == 1 else "",
		]
		+ "drag=cam  rdrag=sun  wheel=zoom  SPACE=orbit pause  C=day-cycle\n"
		+ "1=noon 2=golden 3=overcast 4=moon 5=backlit  +/-=E  [/]=amb  ,/.=wrap  R=reset\n"
		+ "F=flashlight  O=reference orb  V=envSH/flat  A=sun off  D=ambient off  N=sign mode"
	)


# Gray Lambert reference sphere, offset from the AABB center, engine-lit by the same
# DirectionalLight3D. Placement uses the shared helper so a later sphere_consistency
# check reuses the exact position/radius.
func _build_orb(ab: AABB) -> void:
	var place := orb_placement(_center, ab.size)
	_orb = MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = place["radius"]
	sphere.height = place["radius"] * 2.0
	_orb.mesh = sphere
	var mat := StandardMaterial3D.new()
	mat.albedo_color = ORB_ALBEDO
	mat.roughness = ORB_ROUGHNESS
	mat.metallic = 0.0
	_orb.material_override = mat
	_orb.position = place["position"]
	_orb.visible = false
	add_child(_orb)


# One engine SpotLight3D mirroring the compute-pass flashlight, parented to the camera
# so it tracks camera pos + forward. Toggled visible with the flashlight so the orb
# stays an honest cross-model reference in flashlight mode too.
func _build_flash_engine_light() -> void:
	if _cam == null:
		return
	_orb_light = SpotLight3D.new()
	_orb_light.light_color = FLASH_COLOR
	_orb_light.light_energy = 6.0
	_orb_light.spot_range = _flash_range
	_orb_light.spot_angle = FLASH_OUTER_DEG
	_orb_light.spot_angle_attenuation = 1.0
	_orb_light.visible = false
	_cam.add_child(_orb_light)


# Shared orb placement helper (reused by any later sphere-based reference check).
# Offsets the sphere to the side + slightly above the AABB center; radius scales with
# the asset extent so it reads at the demo's viewing distance.
static func orb_placement(center: Vector3, aabb_size: Vector3) -> Dictionary:
	var radius: float = maxf(aabb_size.length() * 0.12, 0.2)
	var pos := center + Vector3(
		maxf(aabb_size.x, 1.0) * 0.75 + radius,
		maxf(aabb_size.y, 1.0) * 0.25,
		0.0)
	return {"position": pos, "radius": radius}


func _update_cam() -> void:
	if _cam == null:
		return
	var offset := Vector3(
		cos(_pitch) * sin(_yaw),
		sin(_pitch),
		cos(_pitch) * cos(_yaw)
	) * _dist
	_cam.look_at_from_position(_center + offset, _center, Vector3.UP)
