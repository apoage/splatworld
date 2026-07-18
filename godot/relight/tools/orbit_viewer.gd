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
	KEY_6: {"name": "underground", "el": -0.9, "color": Color(0.6, 0.85, 0.5), "energy": 1.4, "amb": 0.05},
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

# Facing-debug overlay (key G) — sandbox stage 1. Colors each splat by its RAW normal's
# facing vs a reference (green=front/toward, magenta=back/away, brightness ~|dot|) so the
# sign domains + isolated flipped splats behind the closeup noise are directly visible.
# Orthogonal to raw/relit (binding-5 meta.z), so it survives the M raw toggle.
const DBG_NAMES := ["off", "N·L (sun)", "N·V (cam)", "N·up (world)"]
var _dbg := 0

# M3 backlit-transmission formula A/B (key T cycles): 0 = shipped dot(-N,L) wrap (a),
# 1 = Frostbite view–light phase (b). Owner eyeballs a vs b on the backlit pose (5) with
# the Transmission toggle on. Needs a re-exported asset with nonzero leaf/grass trans to
# show anything (placeholder heroes still ship trans=0). Mode 0 is byte-identical.
const TRANS_NAMES := ["wrap (a)", "phase (b)"]
var _trans_mode := 0

# Fly camera: WASD / arrows move in the camera plane, E/Q up/down, SHIFT sprints. Moves
# BOTH the camera and its orbit pivot (_center) so left-drag orbit still works after you
# fly somewhere. Speed scales with the asset extent. (A/D freed from the old sun/ambient
# toggles, which are now clickable panel checkboxes.)
var _fly_speed := 1.0

# Clickable A/B control panel (top-right): every toggle + sun/energy/ambient sliders, for
# fast A/B without memorizing keys. Two-way: UI events write state; _sync_ui() mirrors
# state back each frame via *_no_signal setters (keys + day-cycle keep the panel live).
var _ui := {}

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
		_fly_speed = maxf(ab.size.length() * 0.8, 1.0)
		_update_cam()
		_build_orb(ab)
		_build_flash_engine_light()
	_build_control_panel()
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
			# Elevation spans below the horizon now (owner: "light a patch of grass from
			# underground") — negative el => sun.y<0 => L points down, lighting undersides.
			_sun_el = clampf(_sun_el - e.relative.y * 0.008, -1.55, 1.55)
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
				_dbg = 0
				_trans_mode = 0
				RelightPass.set_sign_mode(0)
				RelightPass.set_viz_mode(0)
				RelightPass.set_trans_mode(0)
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
			KEY_F:
				_flash_on = not _flash_on
			KEY_O:
				if _orb != null:
					_orb.visible = not _orb.visible
			KEY_N:
				# D7: cycle the sign-agnostic shading mode live (HUD shows it).
				_sign_mode = (_sign_mode + 1) % SIGN_NAMES.size()
				RelightPass.set_sign_mode(_sign_mode)
			KEY_G:
				# Sandbox stage 1: cycle the facing-debug overlay (isolate front/back).
				_dbg = (_dbg + 1) % DBG_NAMES.size()
				RelightPass.set_viz_mode(_dbg)
			KEY_T:
				# M3: cycle the backlit-transmission formula (a wrap / b phase) live.
				_trans_mode = (_trans_mode + 1) % TRANS_NAMES.size()
				RelightPass.set_trans_mode(_trans_mode)
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
	_fly_move(delta)
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
	# Gimbal guard: near-vertical light (|el|->~90°, e.g. straight up from underground)
	# makes -sun nearly parallel to Y-up and look_at degenerate; swap to a Z up there.
	var up := Vector3.UP if absf(_sun_el) < 1.3 else Vector3(0.0, 0.0, 1.0)
	_light.look_at_from_position(Vector3.ZERO, -sun, up)
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
	RelightPass.set_trans_mode(_trans_mode)
	_update_flashlight()
	_refresh_hud()
	_sync_ui()


# WASD / arrows move in the camera plane, E/Q down/up, SHIFT sprints. Translates both the
# camera and its orbit pivot so orbit still works afterward. Polled (held keys) not events.
func _fly_move(delta: float) -> void:
	if _cam == null:
		return
	var fb := 0.0
	var lr := 0.0
	var ud := 0.0
	if Input.is_physical_key_pressed(KEY_W) or Input.is_physical_key_pressed(KEY_UP): fb += 1.0
	if Input.is_physical_key_pressed(KEY_S) or Input.is_physical_key_pressed(KEY_DOWN): fb -= 1.0
	if Input.is_physical_key_pressed(KEY_D) or Input.is_physical_key_pressed(KEY_RIGHT): lr += 1.0
	if Input.is_physical_key_pressed(KEY_A) or Input.is_physical_key_pressed(KEY_LEFT): lr -= 1.0
	if Input.is_physical_key_pressed(KEY_E): ud += 1.0
	if Input.is_physical_key_pressed(KEY_Q): ud -= 1.0
	if fb == 0.0 and lr == 0.0 and ud == 0.0:
		return
	var b := _cam.global_transform.basis
	var move := (-b.z) * fb + b.x * lr + Vector3.UP * ud
	if move.length() < 1e-4:
		return
	var sprint := 3.0 if Input.is_physical_key_pressed(KEY_SHIFT) else 1.0
	_center += move.normalized() * _fly_speed * sprint * delta
	_update_cam()


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
		+ "D7 sign=%d:%s%s   dbg=%s%s   trans-lobe=%s\n" % [
			_sign_mode, SIGN_NAMES[_sign_mode],
			("  w=%.2f" % _sign_wrap) if _sign_mode == 1 else "",
			DBG_NAMES[_dbg],
			"  (green=front/toward  magenta=back/away)" if _dbg != 0 else "",
			TRANS_NAMES[_trans_mode],
		]
		+ "drag=cam  rdrag=sun (now goes BELOW horizon)  wheel=zoom  SPACE=orbit pause  C=day-cycle\n"
		+ "1=noon 2=golden 3=overcast 4=moon 5=backlit 6=underground  +/-=E  [/]=amb  ,/.=wrap  R=reset\n"
		+ "F=flashlight  O=orb  V=envSH/flat  A=sun off  D=ambient off  N=sign mode  G=facing debug  T=trans lobe"
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


# ---- clickable A/B control panel (top-right) -------------------------------------------

func _build_control_panel() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var vp := get_viewport().get_visible_rect().size
	var bg := PanelContainer.new()
	bg.position = Vector2(vp.x - 300.0, 84.0)
	bg.custom_minimum_size = Vector2(288.0, 0.0)
	layer.add_child(bg)
	var box := VBoxContainer.new()
	bg.add_child(box)

	var title := Label.new()
	title.text = "— A/B controls —"
	box.add_child(title)

	_ui["relit"] = _add_check(box, "Relit (raw off)", _mode == RelightPass.MODE_RELIT, _on_relit_ui)
	_ui["env"] = _add_check(box, "Env-SH ambient", _env_on, _on_env_ui)
	_ui["sun_off"] = _add_check(box, "Sun off", _sun_off, _on_sunoff_ui)
	_ui["amb_off"] = _add_check(box, "Ambient off", _amb_off, _on_amboff_ui)
	_ui["flash"] = _add_check(box, "Flashlight", _flash_on, _on_flash_ui)
	_ui["orb"] = _add_check(box, "Reference orb", false, _on_orb_ui)

	_ui["az"] = _add_slider(box, "sun az°", 0.0, 360.0, 1.0, wrapf(rad_to_deg(_sun_az), 0.0, 360.0), _on_az_ui)
	_ui["el"] = _add_slider(box, "sun el°", -90.0, 90.0, 1.0, rad_to_deg(_sun_el), _on_el_ui)
	_ui["energy"] = _add_slider(box, "energy", 0.02, 8.0, 0.02, _energy, _on_energy_ui)
	_ui["amb"] = _add_slider(box, "ambient", 0.0, 1.0, 0.01, _amb, _on_amb_ui)

	_ui["sign"] = _add_option(box, "sign mode", SIGN_NAMES, _sign_mode, _on_sign_ui)
	_ui["dbg"] = _add_option(box, "facing debug", DBG_NAMES, _dbg, _on_dbg_ui)
	_ui["trans_mode"] = _add_option(box, "trans lobe", TRANS_NAMES, _trans_mode, _on_transmode_ui)


func _add_check(parent: Node, text: String, pressed: bool, cb: Callable) -> CheckButton:
	var c := CheckButton.new()
	c.text = text
	c.button_pressed = pressed
	c.toggled.connect(cb)
	parent.add_child(c)
	return c


func _add_slider(parent: Node, text: String, mn: float, mx: float, step: float, val: float, cb: Callable) -> HSlider:
	var row := HBoxContainer.new()
	var lbl := Label.new()
	lbl.text = text
	lbl.custom_minimum_size = Vector2(90.0, 0.0)
	row.add_child(lbl)
	var s := HSlider.new()
	s.min_value = mn
	s.max_value = mx
	s.step = step
	s.value = val
	s.custom_minimum_size = Vector2(170.0, 0.0)
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.value_changed.connect(cb)
	row.add_child(s)
	parent.add_child(row)
	return s


func _add_option(parent: Node, text: String, items: Array, selected: int, cb: Callable) -> OptionButton:
	var row := HBoxContainer.new()
	var lbl := Label.new()
	lbl.text = text
	lbl.custom_minimum_size = Vector2(90.0, 0.0)
	row.add_child(lbl)
	var o := OptionButton.new()
	for it in items:
		o.add_item(str(it))
	o.selected = selected
	o.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	o.item_selected.connect(cb)
	row.add_child(o)
	parent.add_child(row)
	return o


# UI event handlers (write state; mirror the keyboard paths exactly).
func _on_relit_ui(p: bool) -> void:
	_mode = RelightPass.MODE_RELIT if p else RelightPass.MODE_RAW

func _on_env_ui(p: bool) -> void:
	if _env_coeffs.is_empty():
		return
	_env_on = p
	if _env_on and not _amb_off:
		RelightPass.set_env_sh(_env_coeffs)
	else:
		RelightPass.clear_env_sh()

func _on_sunoff_ui(p: bool) -> void:
	_sun_off = p

func _on_amboff_ui(p: bool) -> void:
	_amb_off = p
	if _amb_off:
		RelightPass.clear_env_sh()
	elif _env_on and not _env_coeffs.is_empty():
		RelightPass.set_env_sh(_env_coeffs)

func _on_flash_ui(p: bool) -> void:
	_flash_on = p

func _on_orb_ui(p: bool) -> void:
	if _orb != null:
		_orb.visible = p

func _on_az_ui(v: float) -> void:
	_hold_light("manual")
	_sun_az = deg_to_rad(v)

func _on_el_ui(v: float) -> void:
	_hold_light("manual")
	_sun_el = clampf(deg_to_rad(v), -1.55, 1.55)

func _on_energy_ui(v: float) -> void:
	_energy = v

func _on_amb_ui(v: float) -> void:
	_amb = v

func _on_sign_ui(i: int) -> void:
	_sign_mode = i
	RelightPass.set_sign_mode(_sign_mode)

func _on_dbg_ui(i: int) -> void:
	_dbg = i
	RelightPass.set_viz_mode(_dbg)

func _on_transmode_ui(i: int) -> void:
	_trans_mode = i
	RelightPass.set_trans_mode(_trans_mode)


# Mirror current state into the panel each frame (keys + day-cycle keep it live) without
# re-emitting the control signals.
func _sync_ui() -> void:
	if _ui.is_empty():
		return
	_ui["relit"].set_pressed_no_signal(_mode == RelightPass.MODE_RELIT)
	_ui["env"].set_pressed_no_signal(_env_on and not _env_coeffs.is_empty())
	_ui["sun_off"].set_pressed_no_signal(_sun_off)
	_ui["amb_off"].set_pressed_no_signal(_amb_off)
	_ui["flash"].set_pressed_no_signal(_flash_on)
	_ui["orb"].set_pressed_no_signal(_orb != null and _orb.visible)
	_ui["az"].set_value_no_signal(wrapf(rad_to_deg(_sun_az), 0.0, 360.0))
	_ui["el"].set_value_no_signal(rad_to_deg(_sun_el))
	_ui["energy"].set_value_no_signal(_energy)
	_ui["amb"].set_value_no_signal(_amb)
	_ui["sign"].selected = _sign_mode
	_ui["dbg"].selected = _dbg
	_ui["trans_mode"].selected = _trans_mode
