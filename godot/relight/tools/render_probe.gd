extends SceneTree
# GDGS tile-dropout probe (GPU, real display). Renders the SAME asset + camera at
# several resolutions and, per resolution, reports:
#   * sort_buffer_size  — the projection pass's tile-gaussian PAIR counter
#                         (histogram[0]); the decisive tile-dropout metric.
#   * capacity          — the per-half sort-pair buffer size the pairs must fit in
#                         (state.sort_capacity_per_half post-fix, else point_count*10).
#   * interior holes    — count of enclosed ~background 16px tiles (blocky dropouts).
# Expect: small << capacity (clean); pre-fix fullscreen/4K sort_buffer_size > capacity
# (repro); post-fix fullscreen/4K sort_buffer_size <= capacity and holes ~0.
# It also saves one screenshot per resolution for human eyeballing (NOT a gate).
#   DISPLAY=:0 godot --path godot --script res://relight/tools/render_probe.gd
#   (--headless = dummy renderer, won't rasterize — real GPU required)

const ASSET := "res://gs_assets/cactus_142k.ply"
const MANAGER_NODE_NAME := "_GdgsGaussianRenderManager"
const TILE := 16
const SETTLE_FRAMES := 60          # let the resize + steady-state render settle

# Resolutions swept, low -> high, plus a zoomed pass. `cam` = camera distance from
# origin (smaller = zoomed in = bigger splat footprints = more tile-gaussian pairs).
# Small stays under the reference tile budget; fullscreen/4K/zoom are where the
# resolution- and zoom-dependent pair count blows the fixed budget.
var _phases := [
	{"name": "small", "size": Vector2i(960, 540), "cam": 3.5},
	{"name": "fullscreen", "size": Vector2i(1920, 1080), "cam": 3.5},
	{"name": "uhd4k", "size": Vector2i(3840, 2160), "cam": 3.5},
	{"name": "uhd4k_zoom", "size": Vector2i(3840, 2160), "cam": 1.5},
]

var _out_dir: String
var _gs: GaussianSplatNode
var _cam: Camera3D

var _phase := 0
var _frames := 0
var _waiting_readback := false
var _last_img: Image
var _last_holes := -1
var _last_capacity := -1
var _last_render_size := Vector2i.ZERO

var _readback_mutex := Mutex.new()
var _readback_done := false
var _readback_value := -1

# Resolve the screenshot output dir: RELIGHT_SHOT_DIR env, else first cmdline user
# arg (after `--`), else a repo-relative default. Returns an absolute fs path with
# the directory created.
func _resolve_shot_dir() -> String:
	var d := OS.get_environment("RELIGHT_SHOT_DIR")
	if d.is_empty():
		var ua := OS.get_cmdline_user_args()
		if ua.size() > 0:
			d = ua[0]
	if d.is_empty():
		d = "res://shots"   # repo-relative default (godot/shots when run with --path godot)
	var abs_dir := d
	if d.begins_with("res://") or d.begins_with("user://"):
		abs_dir = ProjectSettings.globalize_path(d)
	elif not d.is_absolute_path():
		# relative path -> resolve against the project root, not an unspecified CWD
		abs_dir = ProjectSettings.globalize_path("res://".path_join(d))
	DirAccess.make_dir_recursive_absolute(abs_dir)
	return abs_dir

func _initialize() -> void:
	_out_dir = _resolve_shot_dir()
	var root := get_root()
	root.size = _phases[0].size

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

	# --- light (splats keep baked appearance; light is for scene parity) ---
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, -35, 0)
	root.add_child(light)

	# --- the splat (fills a good part of frame -> overlap -> more pairs) ---
	_gs = GaussianSplatNode.new()
	_gs.gaussian = load(ASSET)
	root.add_child(_gs)
	print("[probe] splat count=", _gs.gaussian.point_count, " aabb=", _gs.gaussian.aabb)

	# --- camera framing the asset ---
	_cam = Camera3D.new()
	root.add_child(_cam)
	_place_cam(_phases[0].cam)
	_cam.current = true

	print("[probe] ---- resolution sweep (sort_buffer_size + interior holes) ----")

# Place the camera at distance `dist` along a fixed viewing direction, aimed at origin.
func _place_cam(dist: float) -> void:
	var dir := Vector3(2.0, 0.8, 2.8).normalized()
	_cam.look_at_from_position(dir * dist, Vector3(0.0, 0.0, 0.0), Vector3.UP)

func _process(_delta: float) -> bool:
	if _phase >= _phases.size():
		return true
	_frames += 1

	if _waiting_readback:
		_readback_mutex.lock()
		var done := _readback_done
		var value := _readback_value
		_readback_mutex.unlock()
		if not done:
			return false
		_emit_phase_result(value)
		_save_phase_shot()
		return _advance_phase()

	if _frames < SETTLE_FRAMES:
		return false
	_capture_and_kick_readback()
	return false

func _capture_and_kick_readback() -> void:
	_last_img = get_root().get_texture().get_image()
	_last_holes = _count_interior_holes(_last_img) if _last_img != null else -1
	# The render state is keyed by the compositor's internal size == the rendered
	# image size (the requested window size may be clamped by the WM).
	var size: Vector2i = _phases[_phase].size
	if _last_img != null:
		size = Vector2i(_last_img.get_width(), _last_img.get_height())
	_last_render_size = size
	_last_capacity = _get_capacity(size)

	var rid := _find_histogram_rid(size)
	_readback_mutex.lock()
	_readback_done = false
	_readback_value = -1
	_readback_mutex.unlock()
	if rid.is_valid():
		# Read back on the render thread — safe access to the main RenderingDevice.
		RenderingServer.call_on_render_thread(_do_readback.bind(rid))
	else:
		push_error("[probe] no histogram buffer for size %s (state not built?) available=%s" % [size, _cache_sizes()])
		_readback_mutex.lock()
		_readback_done = true
		_readback_mutex.unlock()
	_waiting_readback = true

func _do_readback(rid: RID) -> void:
	var v := -1
	var rd := RenderingServer.get_rendering_device()
	if rd != null and rid.is_valid():
		var bytes := rd.buffer_get_data(rid, 0, 4)   # histogram[0] = sort_buffer_size
		if bytes.size() >= 4:
			v = int(bytes.decode_u32(0))
	_readback_mutex.lock()
	_readback_value = v
	_readback_done = true
	_readback_mutex.unlock()

func _emit_phase_result(sort_buffer_size: int) -> void:
	var p = _phases[_phase]
	var size: Vector2i = _last_render_size if _last_render_size != Vector2i.ZERO else p.size
	var tiles := _tile_count(size)
	var ratio := 0.0
	if _last_capacity > 0:
		ratio = float(sort_buffer_size) / float(_last_capacity)
	var over := "OVER-CAPACITY(repro)" if sort_buffer_size > _last_capacity else "ok"
	# One machine-readable line per resolution.
	print("PROBE name=%s res=%dx%d tiles=%d point_count=%d sort_buffer_size=%d capacity=%d ratio=%.3f headroom=%.2fx holes=%d %s" % [
		p.name, size.x, size.y, tiles, _gs.gaussian.point_count,
		sort_buffer_size, _last_capacity, ratio,
		(float(_last_capacity) / float(maxi(sort_buffer_size, 1))),
		_last_holes, over
	])

func _save_phase_shot() -> void:
	if _last_img == null or _last_img.get_width() == 0:
		push_error("[probe] empty viewport image for phase %s" % _phases[_phase].name)
		return
	var path := _out_dir.path_join("tiledrop_%s.png" % _phases[_phase].name)
	var err := _last_img.save_png(path)
	if err != OK or not FileAccess.file_exists(path):
		push_error("[probe] save_png FAILED err=%d -> %s" % [err, path])
		return
	print("SHOT_SAVED ", path)

func _advance_phase() -> bool:
	_phase += 1
	_frames = 0
	_waiting_readback = false
	if _phase >= _phases.size():
		print("[probe] ---- sweep complete ----")
		return true
	get_root().size = _phases[_phase].size
	_place_cam(_phases[_phase].cam)
	return false

# --- helpers -----------------------------------------------------------------

func _tile_count(size: Vector2i) -> int:
	return ((size.x + TILE - 1) / TILE) * ((size.y + TILE - 1) / TILE)

func _get_render_state(size: Vector2i):
	var mgr = get_root().get_node_or_null(MANAGER_NODE_NAME)
	if mgr == null or not ("_gpu_state_cache" in mgr):
		return null
	var cache = mgr._gpu_state_cache
	var state = cache._render_states.get(size, null)
	if state == null:
		for s in cache._render_states.values():
			if s.texture_size == size:
				state = s
				break
	return state

func _cache_sizes() -> String:
	var mgr = get_root().get_node_or_null(MANAGER_NODE_NAME)
	if mgr == null or not ("_gpu_state_cache" in mgr):
		return "<no manager>"
	var out := []
	for s in mgr._gpu_state_cache._render_states.values():
		out.append(s.texture_size)
	return str(out)

func _find_histogram_rid(size: Vector2i) -> RID:
	var state = _get_render_state(size)
	if state == null or not state.descriptors.has("histogram"):
		return RID()
	return state.descriptors["histogram"].rid

func _get_capacity(size: Vector2i) -> int:
	var state = _get_render_state(size)
	if state != null and ("sort_capacity_per_half" in state) and state.sort_capacity_per_half > 0:
		return state.sort_capacity_per_half
	# Pre-fix fallback: the old fixed budget was point_count * MAX_SORT_ELEMENTS_PER_SPLAT(=10).
	return _gs.gaussian.point_count * 10

# Count enclosed ~background 16px tiles = blocky interior dropouts. A tile is
# "background" if its mean color matches the top-left corner (a known-empty tile);
# it is an interior hole only if bracketed by content tiles on BOTH axes (so the
# asset silhouette / true background border is not counted). The absolute count is
# noisy in concave regions, but the delta (many -> ~0 after the fix) is decisive.
func _count_interior_holes(img: Image) -> int:
	var w := img.get_width()
	var h := img.get_height()
	if w < TILE * 3 or h < TILE * 3:
		return 0
	var tw := (w + TILE - 1) / TILE
	var th := (h + TILE - 1) / TILE
	var bg := img.get_pixel(2, 2)   # top-left tile = reliably background
	var eps := 0.02

	# Classify tiles: true = content, false = background.
	var content := PackedByteArray()
	content.resize(tw * th)
	for ty in range(th):
		for tx in range(tw):
			var px := mini(tx * TILE + TILE / 2, w - 1)
			var py := mini(ty * TILE + TILE / 2, h - 1)
			var c := img.get_pixel(px, py)
			var d := absf(c.r - bg.r) + absf(c.g - bg.g) + absf(c.b - bg.b)
			content[ty * tw + tx] = 1 if d > eps else 0

	# Per-row content extent.
	var row_min := PackedInt32Array()
	var row_max := PackedInt32Array()
	row_min.resize(th)
	row_max.resize(th)
	for ty in range(th):
		var lo := -1
		var hi := -1
		for tx in range(tw):
			if content[ty * tw + tx] == 1:
				if lo == -1:
					lo = tx
				hi = tx
		row_min[ty] = lo
		row_max[ty] = hi
	# Per-column content extent.
	var col_min := PackedInt32Array()
	var col_max := PackedInt32Array()
	col_min.resize(tw)
	col_max.resize(tw)
	for tx in range(tw):
		var lo := -1
		var hi := -1
		for ty in range(th):
			if content[ty * tw + tx] == 1:
				if lo == -1:
					lo = ty
				hi = ty
		col_min[tx] = lo
		col_max[tx] = hi

	var holes := 0
	for ty in range(th):
		for tx in range(tw):
			if content[ty * tw + tx] == 1:
				continue
			var h_enclosed := row_min[ty] != -1 and tx > row_min[ty] and tx < row_max[ty]
			var v_enclosed := col_min[tx] != -1 and ty > col_min[tx] and ty < col_max[tx]
			if h_enclosed and v_enclosed:
				holes += 1
	return holes
