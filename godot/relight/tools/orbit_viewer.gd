extends "res://relight/relight_controller.gd"

# Interactive viewer on top of the M2a demo controller: left-drag orbits the camera
# around the asset, wheel zooms, SPACE pauses/resumes the light orbit. The base
# class's UI toggles (raw/relit, transmission) keep working. Launch:
#   DISPLAY=:0 ~/godot/godot --path godot res://scenes/viewer.tscn

var _cam: Camera3D
var _center := Vector3.ZERO
var _dist := 3.0
var _yaw := 0.6
var _pitch := 0.35
var _dragging := false
var _light_paused := false


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
	_set_status("drag=orbit  wheel=zoom  SPACE=pause light")


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton:
		match e.button_index:
			MOUSE_BUTTON_LEFT:
				_dragging = e.pressed
			MOUSE_BUTTON_WHEEL_UP:
				if e.pressed:
					_dist = maxf(_dist * 0.9, 0.2)
					_update_cam()
			MOUSE_BUTTON_WHEEL_DOWN:
				if e.pressed:
					_dist *= 1.1
					_update_cam()
	elif e is InputEventMouseMotion and _dragging:
		_yaw -= e.relative.x * 0.008
		_pitch = clampf(_pitch + e.relative.y * 0.008, -1.45, 1.45)
		_update_cam()
	elif e is InputEventKey and e.pressed and e.keycode == KEY_SPACE:
		_light_paused = not _light_paused


func _process(delta: float) -> void:
	super(0.0 if _light_paused else delta)


func _update_cam() -> void:
	if _cam == null:
		return
	var offset := Vector3(
		cos(_pitch) * sin(_yaw),
		sin(_pitch),
		cos(_pitch) * cos(_yaw)
	) * _dist
	_cam.look_at_from_position(_center + offset, _center, Vector3.UP)
