extends SceneTree
# M1 visual check: render the trained foliage splat (train_base output) via the
# GDGS path, from a few angles, and save screenshots for eyeballing.
#   DISPLAY=:0 godot --path godot --script res://relight/tools/render_foliage.gd

const ASSET := "res://gs_assets/foliage_train.ply"
const OUTDIR := "/tmp/claude-1000/-home-lukas-splatworld/373979b4-7881-48cf-acdd-3433fa2526f5/scratchpad"
var _frames := 0
var _shot := 0
var _gs: GaussianSplatNode
var _cam: Camera3D
var _center: Vector3
var _radius: float

func _initialize() -> void:
	var root := get_root()
	root.size = Vector2i(1280, 960)

	var we := WorldEnvironment.new()
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.10, 0.11, 0.14)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.4, 0.4, 0.42)
	we.environment = env
	var comp := Compositor.new()
	comp.compositor_effects = [GaussianCompositorEffect.new()]
	we.compositor = comp
	root.add_child(we)

	_gs = GaussianSplatNode.new()
	_gs.gaussian = load(ASSET)
	root.add_child(_gs)
	var ab: AABB = _gs.gaussian.aabb
	_center = ab.position + ab.size * 0.5
	_radius = ab.size.length() * 0.6
	print("[foliage] count=", _gs.gaussian.point_count, " aabb=", ab)

	_cam = Camera3D.new()
	root.add_child(_cam)
	_place_cam(0)

func _place_cam(shot: int) -> void:
	var angles := [0.6, 2.2, 4.0]           # yaw around the asset
	var a: float = angles[shot % angles.size()]
	var pos := _center + Vector3(cos(a) * _radius, _radius * 0.5, sin(a) * _radius)
	_cam.look_at_from_position(pos, _center, Vector3.UP)
	_cam.current = true

func _process(_dt: float) -> bool:
	_frames += 1
	if _frames < 60:
		return false
	var img := get_root().get_texture().get_image()
	var p := "%s/m1_foliage_%d.png" % [OUTDIR, _shot]
	img.save_png(p)
	print("SHOT_SAVED ", p)
	_shot += 1
	if _shot >= 3:
		return true
	_place_cam(_shot)
	_frames = 0
	return false
