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


func _ready() -> void:
	super()
	for c in get_children():
		if c is Camera3D:
			_cam = c
	if _cam != null and _splat != null:
		var ab: AABB = _splat.gaussian.aabb
		_center = ab.position + ab.size * 0.5
		_dist = maxf(ab.size.length() * 0.9, 1.0)
		_update_cam()


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
				_wrap = maxf(_wrap - 0.25, 0.25)
			KEY_PERIOD:
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
	RelightPass.set_light(light_dir_ws, _color * _energy, _wrap, _amb, _mode, _trans_on)
	_refresh_hud()


func _hold_light(condition: String) -> void:
	_day_cycle = false
	_light_paused = true
	_condition = condition


func _refresh_hud() -> void:
	_set_status(
		"mode=%s%s  sun az=%d° el=%d°  E=%.2f  amb=%.2f  wrap=%.2f  [%s]\n" % [
			"relit" if _mode == RelightPass.MODE_RELIT else "RAW ALBEDO",
			"+trans" if _trans_on else "",
			roundi(wrapf(rad_to_deg(_sun_az), 0.0, 360.0)), roundi(rad_to_deg(_sun_el)),
			_energy, _amb, _wrap, _condition,
		]
		+ "drag=cam  rdrag=sun  wheel=zoom  SPACE=orbit pause  C=day-cycle\n"
		+ "1=noon 2=golden 3=overcast 4=moon 5=backlit  +/-=E  [/]=amb  ,/.=wrap  R=reset"
	)


func _update_cam() -> void:
	if _cam == null:
		return
	var offset := Vector3(
		cos(_pitch) * sin(_yaw),
		sin(_pitch),
		cos(_pitch) * cos(_yaw)
	) * _dist
	_cam.look_at_from_position(_center + offset, _center, Vector3.UP)
