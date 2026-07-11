extends SceneTree
# M0 visual check (GPU, real display). Builds a scene: GDGS splat + an intersecting
# mesh cube + one directional light + the gaussian compositor. Renders a few frames
# then saves a screenshot for human/AI eyeballing. NOT a pass/fail gate.
#   DISPLAY=:0 godot --path godot --script res://relight/tools/render_probe.gd

const ASSET := "res://gs_assets/cactus_142k.ply"
const OUT := "/tmp/claude-1000/-home-lukas-splatworld/373979b4-7881-48cf-acdd-3433fa2526f5/scratchpad/m0_shot.png"
var _frames := 0

func _initialize() -> void:
	var root := get_root()
	root.size = Vector2i(1280, 960)

	# --- Gaussian compositor on a WorldEnvironment ---
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
	root.add_child(we)

	# --- light (affects the cube; splats keep baked appearance in M0) ---
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -35, 0)
	root.add_child(light)

	# --- the splat ---
	var gs := GaussianSplatNode.new()
	gs.gaussian = load(ASSET)
	root.add_child(gs)
	print("[probe] splat count=", gs.gaussian.point_count, " aabb=", gs.gaussian.aabb)

	# --- an intersecting mesh cube (to prove depth compositing both ways) ---
	var mi := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(0.9, 0.9, 0.9)
	mi.mesh = box
	mi.position = Vector3(0.45, -0.1, 0.1)   # overlaps the cactus body
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.85, 0.30, 0.20)
	mi.material_override = mat
	root.add_child(mi)

	# --- camera framing the pair ---
	var cam := Camera3D.new()
	root.add_child(cam)
	cam.look_at_from_position(Vector3(2.6, 1.0, 3.6), Vector3(0.0, 0.0, 0.0), Vector3.UP)
	cam.current = true

func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 150:
		return false
	var img := get_root().get_texture().get_image()
	if img == null or img.get_width() == 0:
		push_error("[probe] empty viewport image")
		return true
	var err := img.save_png(OUT)
	print("[probe] save_png err=%d -> %s (%dx%d)" % [err, OUT, img.get_width(), img.get_height()])
	print("SHOT_SAVED")
	return true
