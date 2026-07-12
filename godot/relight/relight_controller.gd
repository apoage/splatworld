extends Node3D

# M2a interactive demo. Scene root: builds the environment (gray ambient floor so
# shadows never go black) + the GDGS compositor, loads the extended asset via
# RelightPlyLoader, registers its materials with RelightPass, orbits ONE
# DirectionalLight3D, and pushes light/mode/wrap/ambient into RelightPass each
# frame. UI: raw/relit toggle (M2) + transmission on/off toggle (wired to the
# trans_on lane, inert until M3 since placeholder trans == 0).

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")

const ASSET_PATH := "res://gs_assets/pxl_144634.relightply"

const WRAP_POWER := 2.0
const AMBIENT := 0.2
const LIGHT_COLOR := Color(1.0, 0.98, 0.92)
const ORBIT_SPEED := 0.5 # rad/s

var _light: DirectionalLight3D
var _splat: GaussianSplatNode
var _mode := RelightPass.MODE_RELIT
var _trans_on := false
var _orbit := 0.0
var _status: Label


func _ready() -> void:
	_build_environment()
	_build_ui()

	var res := RelightPlyLoader.load(ASSET_PATH)
	if res == null:
		_set_status("FAILED to load %s" % ASSET_PATH)
		push_error("[relight] controller: asset load failed (%s)" % ASSET_PATH)
		return

	RelightPass.set_materials(res.attr_data_byte, res.point_count)

	_splat = GaussianSplatNode.new()
	_splat.gaussian = res
	add_child(_splat)

	var ab: AABB = res.aabb
	var center := ab.position + ab.size * 0.5
	var radius: float = maxf(ab.size.length() * 0.6, 1.0)

	var cam := Camera3D.new()
	add_child(cam)
	cam.look_at_from_position(center + Vector3(radius, radius * 0.4, radius), center, Vector3.UP)
	cam.current = true

	_light = DirectionalLight3D.new()
	add_child(_light)

	_set_status("splats=%d  [relit]" % res.point_count)
	print("[relight] loaded %d splats, aabb=%s" % [res.point_count, ab])


func _exit_tree() -> void:
	# Don't leave stale materials bound for whatever scene renders next.
	RelightPass.clear_materials()


func _process(delta: float) -> void:
	if _light == null:
		return
	_orbit += delta * ORBIT_SPEED
	# Light travels downward while orbiting in azimuth (keeps foliage lit from above).
	var travel := Vector3(sin(_orbit) * 0.7, -0.7, cos(_orbit) * 0.7).normalized()
	_light.look_at_from_position(Vector3.ZERO, travel, Vector3.UP)

	var light_dir_ws := -_light.global_transform.basis.z # DirectionalLight3D shines along -Z
	RelightPass.set_light(light_dir_ws, LIGHT_COLOR, WRAP_POWER, AMBIENT, _mode, _trans_on)


func _build_environment() -> void:
	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.10, 0.11, 0.14)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.35, 0.35, 0.38)
	env.ambient_light_energy = 1.0
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	add_child(we)


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var box := VBoxContainer.new()
	box.position = Vector2(16, 16)
	layer.add_child(box)

	_status = Label.new()
	box.add_child(_status)

	var relit := CheckButton.new()
	relit.text = "Relit (off = raw albedo)"
	relit.button_pressed = true
	relit.toggled.connect(_on_relit_toggled)
	box.add_child(relit)

	var trans := CheckButton.new()
	trans.text = "Transmission (M3 — inert at trans=0)"
	trans.button_pressed = false
	trans.toggled.connect(_on_trans_toggled)
	box.add_child(trans)


func _on_relit_toggled(pressed: bool) -> void:
	_mode = RelightPass.MODE_RELIT if pressed else RelightPass.MODE_RAW
	_set_status("mode=%s" % ("relit" if pressed else "raw"))


func _on_trans_toggled(pressed: bool) -> void:
	_trans_on = pressed


func _set_status(text: String) -> void:
	if _status != null:
		_status.text = text
