extends SceneTree
# M4 carpet frame-time HARNESS (task 3a). Loads an instances.json carpet via the shipped
# CarpetLoader, drives a FIXED, DETERMINISTIC camera orbit over the scene, and reports
#   count / frame-ms / fps
# (total rendered splat count, mean wall-clock ms/frame over the orbit, derived fps).
#
# ── WHY THIS TOOL DOES NOT ASSERT AN FPS IN HEADLESS ──────────────────────────────────
# `--headless` runs Godot's DUMMY display server: it does NOT rasterize, so any frame time
# it reports is MEANINGLESS. Therefore:
#   * The DoD of THIS build step (task 3a) is the TOOL + a STRUCTURE self-check on a small
#     instance count — the harness runs, loads the carpet via CarpetLoader, reports the
#     count/frame-ms/fps fields, and the PERF_FPS_MIN assert-scaffold is present & correct.
#     It is NOT an fps number.
#   * Headless mode prints a `HEADLESS — frame time not authoritative` marker, does NOT gate
#     on the frame time, and emits `CARPET_PERF_RESULT PASS` iff the STRUCTURE check passed
#     (mirroring carpet_smoke.gd's `CARPET_SMOKE_RESULT PASS/FAIL` convention). It never
#     fabricates or gates on a headless reading.
#   * The REAL measurement is task 3b: run this SAME script on DISPLAY=:0 (real 3090). There
#     `_authoritative` is true, so `_assert_fps` enforces `fps >= PERF_FPS_MIN` and exits
#     nonzero on a miss. The factory never marks itself blocked on 3b.
#
# ── CARPET SELECTED (real happy-path vs synthetic structure check) ────────────────────
#   1. CARPET_JSON=<res://…|abs> env set + loadable  -> use it verbatim (the real carpet;
#      task 3b points this at the heroes + a ~1.5M decimated variant minted by
#      clean_relight.py). This build step does NOT mint or run clean_relight on real assets.
#   2. else both hero .vply present            -> synthesize a small hero grid carpet
#      (exercises the real extended-schema assets when the gitignored gs_assets are here).
#   3. else                                          -> a tiny SYNTHETIC carpet written to
#      user:// (a handful of ~5-Gaussian fixtures). Runs anywhere; this is the DoD path.
#   CARPET_PERF_REQUIRE_ASSET=1 forces a real carpet (1 or 2): if none is available the run
#   FAILs (SMOKE_REQUIRE_ASSET-style) instead of falling back to synthetic.
#   CARPET_PERF_SYNTHETIC=1 forces (3) even when heroes/CARPET_JSON exist — keeps the
#   light "runs-anywhere, small instance count" structure gate reachable on a box that
#   happens to hold the heavy heroes (the 9-hero grid is ~20M splats, not "small").
#
#   ~/godot/godot --path godot --headless --script res://relight/tools/carpet_perf.gd   # structure gate
#   DISPLAY=:0 ~/godot/godot --path godot --script res://relight/tools/carpet_perf.gd   # real measurement (3b)
#   PERF_FPS_MIN=60 CARPET_JSON=res://carpet/meadow.instances.json  DISPLAY=:0 … (3b)

const CarpetLoader = preload("res://relight/carpet_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")

const HERO_A := "res://gs_assets/pxl_144634.vply"
const HERO_B := "res://gs_assets/pxl_131945.vply"
const TINY_A := "user://carpet_perf_tiny_a.vply"
const TINY_B := "user://carpet_perf_tiny_b.vply"
const TINY_JSON := "user://carpet_perf_tiny.json"
const HERO_JSON := "user://carpet_perf_hero.json"

const DEFAULT_FPS_MIN := 60.0
const TARGET_W := 1920                # perf spec resolution (CLAUDE.md: 60 fps @ 1080p)
const TARGET_H := 1080
const WARMUP := 30                    # frames to settle before the timed orbit
const ORBIT_FRAMES := 180             # one full deterministic revolution, timed as the window

const WRAP_POWER := 2.0
const AMBIENT := 0.2
const LIGHT_COLOR := Color(1.0, 0.98, 0.92)
const LIGHT_DIR := Vector3(0.4, -0.7, 0.5)

const TINY_NA := 5
const TINY_NB := 4

var _fps_min := DEFAULT_FPS_MIN
var _authoritative := false           # true only on a real (non-dummy) display server
var _carpet_kind := "synthetic"       # synthetic | hero | external
var _problems: Array[String] = []     # STRUCTURE self-check failures -> drive the sentinel
var _perf_failed := false             # real-display fps-budget miss -> drives exit code ONLY

var _center := Vector3.ZERO
var _radius := 3.0
var _cam: Camera3D
var _total_count := 0
var _instance_count := 0
var _variant_count := 0
var _render_size := Vector2i(TARGET_W, TARGET_H)   # ACTUAL window/viewport size, read back

var _stage := 0                       # 0 warm, 1 measure, 2 done
var _frames := 0
var _t0 := 0
var _ran := false                     # did the orbit measurement actually run?


func _initialize() -> void:
	_fps_min = _env_float("PERF_FPS_MIN", DEFAULT_FPS_MIN)
	_authoritative = DisplayServer.get_name() != "headless"

	var root := get_root()
	if _authoritative:
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
		# Put the window on a screen that can actually host TARGET_W x TARGET_H BEFORE sizing:
		# a window bigger than the monitor is silently clamped by the WM, so it would measure at
		# the wrong resolution (the exact defect that voided the first 3b run on a 1600-wide
		# secondary). CARPET_PERF_SCREEN forces a screen index; else auto-pick the first that fits.
		_place_window_on_capable_screen()
		# Force the OS window (hence the render viewport) to EXACTLY the target pixels. On a real
		# display `root.size` alone leaves the OS window at Godot's 1152x648 default and only
		# resizes the logical viewport (ambiguous window != viewport); window_set_size makes
		# window == viewport == target, so the readback below is unambiguous. content_scale_factor
		# pinned to 1 guards against any project-level content scale.
		root.content_scale_factor = 1.0
		DisplayServer.window_set_size(Vector2i(TARGET_W, TARGET_H))
	else:
		root.size = Vector2i(TARGET_W, TARGET_H)
	# NEVER trust the request — read back the true window size. On a real display a clamp/DPI
	# mismatch means the perf number would be at the wrong resolution, so treat it as a STRUCTURE
	# failure (voids the sentinel + exits nonzero) instead of the old hardcoded "res=1920x1080"
	# lie. Headless keeps the target verbatim (no display server) -> behavior byte-identical.
	_render_size = DisplayServer.window_get_size() if _authoritative else Vector2i(TARGET_W, TARGET_H)
	if _authoritative and _render_size != Vector2i(TARGET_W, TARGET_H):
		_problems.append("render size %dx%d != target %dx%d (screen %d clamped/scaled; set CARPET_PERF_SCREEN to a screen >= %dx%d) — perf number would be at the WRONG resolution" % [
			_render_size.x, _render_size.y, TARGET_W, TARGET_H, DisplayServer.window_get_current_screen(), TARGET_W, TARGET_H])
		_finish()
		return

	# Gaussian compositor on a WorldEnvironment (parity with the other GPU tools; a no-op
	# rasterize under the dummy renderer, real compositing on DISPLAY=:0).
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

	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-45, -35, 0)
	root.add_child(light)

	# ── resolve + load the carpet, then run the STRUCTURE self-check on it ──
	var json_path := _resolve_carpet()
	if json_path.is_empty():
		# CARPET_PERF_REQUIRE_ASSET was set but no real carpet is available.
		_problems.append("CARPET_PERF_REQUIRE_ASSET=1 but no real carpet available (CARPET_JSON unset/absent and hero assets missing)")
		_finish()
		return

	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(json_path, parent)
	if not result.get("ok", false):
		_problems.append("load_carpet(%s) failed: %s" % [json_path, result.get("error", "?")])
		_finish()
		return

	if not _structure_check(result):
		_finish()
		return

	# Relight state: flat ambient (no env sidecar bound -> ambient_sh collapses to the flat
	# constant), no point light. Materials were set by the loader (set_materials_multi).
	RelightPass.clear_env_sh()
	RelightPass.clear_flashlight()
	RelightPass.set_light(LIGHT_DIR.normalized(), LIGHT_COLOR, WRAP_POWER, AMBIENT, RelightPass.MODE_RELIT, false)

	_compute_orbit(result["nodes"])

	_cam = Camera3D.new()
	root.add_child(_cam)
	_place_cam(0.0)
	_cam.current = true
	_ran = true

	print("[carpet-perf] kind=%s instances=%d variants=%d splats=%d res=%dx%d orbit=%d frames fps_min=%.1f authoritative=%s" % [
		_carpet_kind, _instance_count, _variant_count, _total_count, _render_size.x, _render_size.y, ORBIT_FRAMES, _fps_min, str(_authoritative)])


func _process(_delta: float) -> bool:
	if not _ran or _stage == 2:
		return true

	# Warm-up: advance the camera along the orbit (so state settles), then start the timer.
	if _stage == 0:
		_place_cam(float(_frames) / float(WARMUP))
		_frames += 1
		if _frames >= WARMUP:
			_frames = 0
			_t0 = Time.get_ticks_usec()
			_stage = 1
		return false

	# Timed window: one full deterministic revolution.
	_place_cam(float(_frames) / float(ORBIT_FRAMES))
	_frames += 1
	if _frames < ORBIT_FRAMES:
		return false

	var elapsed_us := Time.get_ticks_usec() - _t0
	var ms := float(elapsed_us) / 1000.0 / float(ORBIT_FRAMES)
	var fps := 1000.0 / maxf(ms, 1e-6)

	# The single machine-readable results line (count / frame-ms / fps).
	print("CARPET_PERF count=%d frame-ms=%.3f fps=%.1f" % [_total_count, ms, fps])

	_assert_fps(fps)

	_stage = 2
	RelightPass.clear_materials()
	RelightPass.clear_env_sh()
	_finish()
	return true


# ── the PERF_FPS_MIN assert-scaffold ──────────────────────────────────────────────────
# Structured so the scheduled GPU one-shot (task 3b, DISPLAY=:0) ENFORCES the budget and
# exits nonzero on a miss, while a headless run does NOT — a dummy-renderer frame time is
# not authoritative, so gating on it would be a lie.
func _assert_fps(fps: float) -> void:
	if not _authoritative:
		print("[carpet-perf] HEADLESS — frame time not authoritative (dummy renderer does not rasterize); PERF_FPS_MIN>=%.1f gate SKIPPED" % _fps_min)
		return
	# A perf miss is NOT a structure failure: keep it OUT of `_problems` so the
	# CARPET_PERF_RESULT sentinel stays structure-only (per the DoD). The miss is signalled
	# through the exit code alone (see `_finish`), so a 3b consumer can tell "the harness/
	# structure worked" (sentinel) apart from "perf passed" (exit code).
	if fps < _fps_min:
		_perf_failed = true
		push_error("[carpet-perf] PERF MISS: fps %.1f < PERF_FPS_MIN %.1f (real GPU, 1080p, %d splats)" % [fps, _fps_min, _total_count])
	else:
		print("[carpet-perf] fps %.1f >= PERF_FPS_MIN %.1f OK" % [fps, _fps_min])


# ── structure / coverage self-check (the DoD gate; runs on any carpet) ───────────────
func _structure_check(result: Dictionary) -> bool:
	var nodes: Array = result.get("nodes", [])
	var ordered: Array = result.get("ordered_resources", [])
	var node_variant: Array = result.get("node_variant", [])

	_instance_count = nodes.size()
	_variant_count = ordered.size()

	if _instance_count < 1:
		_problems.append("carpet loaded 0 instances (nothing to measure)")
	if _variant_count < 1:
		_problems.append("carpet loaded 0 unique variants (ordered_resources empty)")
	if node_variant.size() != _instance_count:
		_problems.append("node_variant size %d != nodes %d (loader contract violated)" % [node_variant.size(), _instance_count])

	# Total RENDERED splat count = Σ over instances of the (possibly shared) resource point
	# count (GDGS renders every instance's points; VRAM is shared but points are drawn per
	# instance — cost scales with total rendered points).
	_total_count = 0
	for n in nodes:
		var res = (n as GaussianSplatNode).gaussian
		if res == null:
			_problems.append("an instance node has a null gaussian resource")
			continue
		_total_count += int(res.point_count)
	if _total_count <= 0:
		_problems.append("total rendered splat count is 0")

	# For our authored carpets we know the exact instance count; assert it (catches a loader
	# that silently drops instances). External CARPET_JSON count is unknown -> skip.
	if _carpet_kind == "synthetic" and _instance_count != 9:
		_problems.append("synthetic carpet expected 9 instances, got %d" % _instance_count)

	return _problems.is_empty()


# ── carpet resolution ────────────────────────────────────────────────────────────────
# Returns a loadable instances.json path, or "" if REQUIRE_ASSET was set and none exists.
func _resolve_carpet() -> String:
	var require := not OS.get_environment("CARPET_PERF_REQUIRE_ASSET").is_empty()

	if not OS.get_environment("CARPET_PERF_SYNTHETIC").is_empty():
		_carpet_kind = "synthetic"
		print("[carpet-perf] CARPET_PERF_SYNTHETIC set -> forcing the light synthetic structure carpet")
		return _write_synthetic_carpet()

	var ext := OS.get_environment("CARPET_JSON")
	if not ext.is_empty():
		if FileAccess.file_exists(ext):
			_carpet_kind = "external"
			print("[carpet-perf] using CARPET_JSON=%s" % ext)
			return ext
		push_error("[carpet-perf] CARPET_JSON=%s does not exist" % ext)
		if require:
			return ""

	if FileAccess.file_exists(HERO_A) and FileAccess.file_exists(HERO_B):
		_carpet_kind = "hero"
		print("[carpet-perf] hero assets present -> synthesizing a small hero-grid carpet")
		return _write_hero_carpet()

	if require:
		push_error("[carpet-perf] CARPET_PERF_REQUIRE_ASSET set but no real carpet available")
		return ""

	_carpet_kind = "synthetic"
	print("[carpet-perf] no real carpet -> tiny synthetic carpet (structure self-check; frame time non-authoritative regardless)")
	return _write_synthetic_carpet()


# A 3x3 grid of 9 instances over the 2 heroes (A/B checkerboard). Small on purpose: this
# build step verifies the harness, NOT the ~1.5M budget (that is task 3b, which points
# CARPET_JSON at the real decimated fleet). Spacing keeps blocks middle-distance.
func _write_hero_carpet() -> String:
	var instances: Array = []
	var step := 6.0
	for gz in 3:
		for gx in 3:
			var vid := "a" if ((gx + gz) % 2 == 0) else "b"
			instances.append({
				"variant": vid,
				"pos": [(gx - 1) * step, 0.0, (gz - 1) * step],
				"yaw": float(gx * 3 + gz) * 0.3,
				"scale": 1.0,
				"seed": gx * 3 + gz,
			})
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"region": {"min": [-9, -9], "max": [9, 9], "ground_y": 0.0},
		"variants": [{"id": "a", "path": HERO_A}, {"id": "b", "path": HERO_B}],
		"instances": instances,
	}
	_write_text(HERO_JSON, JSON.stringify(doc))
	return HERO_JSON


# A 3x3 grid of 9 instances over 2 tiny synthetic fixtures. Runs anywhere.
func _write_synthetic_carpet() -> String:
	_write_tiny_relightply(TINY_A, TINY_NA, 0.20)
	_write_tiny_relightply(TINY_B, TINY_NB, 0.70)
	var instances: Array = []
	var step := 1.5
	for gz in 3:
		for gx in 3:
			var vid := "a" if ((gx + gz) % 2 == 0) else "b"
			instances.append({
				"variant": vid,
				"pos": [(gx - 1) * step, 0.0, (gz - 1) * step],
				"yaw": float(gx * 3 + gz) * 0.4,
				"scale": 1.0 + 0.1 * float(gx),
				"seed": gx * 3 + gz,
			})
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"region": {"min": [-3, -3], "max": [3, 3], "ground_y": 0.0},
		"variants": [{"id": "a", "path": TINY_A}, {"id": "b", "path": TINY_B}],
		"instances": instances,
	}
	_write_text(TINY_JSON, JSON.stringify(doc))
	return TINY_JSON


# ── camera path (deterministic orbit) ─────────────────────────────────────────────────
# Union-AABB of the transformed instance nodes -> bounding sphere; orbit at a fixed radius
# and height. `t` in [0,1] is the fraction around one revolution -> fully reproducible.
func _compute_orbit(nodes: Array) -> void:
	var have := false
	var aabb := AABB()
	for n in nodes:
		var node := n as Node3D
		var res = (n as GaussianSplatNode).gaussian
		if res == null:
			continue
		var local: AABB = res.aabb
		var world := node.transform * local     # transform the local AABB into scene space
		if not have:
			aabb = world
			have = true
		else:
			aabb = aabb.merge(world)
	if have:
		_center = aabb.position + aabb.size * 0.5
		_radius = maxf(aabb.size.length() * 0.7, 2.0)
	else:
		_center = Vector3.ZERO
		_radius = 3.0


func _place_cam(t: float) -> void:
	var a := TAU * t
	var pos := _center + Vector3(cos(a) * _radius, _radius * 0.45, sin(a) * _radius)
	_cam.look_at_from_position(pos, _center, Vector3.UP)


# ── helpers ───────────────────────────────────────────────────────────────────────────
# Move the window to a screen that can host TARGET_W x TARGET_H so root.size is not clamped by
# a too-small monitor. CARPET_PERF_SCREEN=<i> forces a screen index; otherwise pick the first
# screen whose size fits the target. No-op if no screen fits (the size readback then flags it).
func _place_window_on_capable_screen() -> void:
	var n := DisplayServer.get_screen_count()
	var target := -1
	var forced := OS.get_environment("CARPET_PERF_SCREEN")
	if not forced.is_empty() and forced.is_valid_int():
		target = clampi(int(forced), 0, maxi(n - 1, 0))
	else:
		for i in n:
			var ss := DisplayServer.screen_get_size(i)
			if ss.x >= TARGET_W and ss.y >= TARGET_H:
				target = i
				break
	if target < 0:
		push_warning("[carpet-perf] no screen fits %dx%d; the size readback will flag the clamp" % [TARGET_W, TARGET_H])
		return
	DisplayServer.window_set_current_screen(target)
	DisplayServer.window_set_position(DisplayServer.screen_get_position(target))
	print("[carpet-perf] window -> screen %d (screen size %s)" % [target, str(DisplayServer.screen_get_size(target))])


func _env_float(name: String, dflt: float) -> float:
	var v := OS.get_environment(name)
	if v.is_empty() or not v.is_valid_float():
		return dflt
	return v.to_float()


func _write_text(path: String, text: String) -> bool:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(text)
	f.close()
	return true


# Minimal valid `splat_relight_schema 1` binary_little_endian PLY (mirrors carpet_smoke's
# fixture): 19 float32 props + a uchar label per vertex; albedo_base separates variants.
func _write_tiny_relightply(path: String, n: int, albedo_base: float) -> void:
	var props := [
		"x", "y", "z",
		"scale_0", "scale_1", "scale_2",
		"rot_0", "rot_1", "rot_2", "rot_3",
		"opacity",
		"albedo_r", "albedo_g", "albedo_b",
		"nx", "ny", "nz",
		"rough", "trans",
	]
	var header := "ply\nformat binary_little_endian 1.0\ncomment splat_relight_schema 1\nelement vertex %d\n" % n
	for pn in props:
		header += "property float %s\n" % pn
	header += "property uchar label\nend_header\n"

	var body := StreamPeerBuffer.new()
	body.big_endian = false
	for i in n:
		body.put_float(i * 0.1)   # x
		body.put_float(0.0)       # y
		body.put_float(0.0)       # z
		body.put_float(-3.0)      # scale_0 (log; loader applies exp)
		body.put_float(-3.0)      # scale_1
		body.put_float(-3.0)      # scale_2
		body.put_float(1.0)       # rot_0 (w)
		body.put_float(0.0)       # rot_1 (x)
		body.put_float(0.0)       # rot_2 (y)
		body.put_float(0.0)       # rot_3 (z)
		body.put_float(0.0)       # opacity (logit -> sigmoid 0.5)
		var alb := albedo_base + i * 0.01
		body.put_float(alb)       # albedo_r
		body.put_float(alb)       # albedo_g
		body.put_float(alb)       # albedo_b
		body.put_float(0.0)       # nx
		body.put_float(0.0)       # ny
		body.put_float(1.0)       # nz
		body.put_float(0.5)       # rough
		body.put_float(0.0)       # trans
		body.put_u8(1)            # label
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(header)
	f.store_buffer(body.data_array)
	f.close()


func _finish() -> void:
	# Sentinel = STRUCTURE self-check only (the task-3a DoD). Exit code = structure AND the
	# real-display perf budget, so a 3b perf miss exits nonzero while the sentinel still
	# reports that the harness/structure itself worked.
	var ok := _problems.is_empty()
	if not ok:
		for p in _problems:
			push_error("[carpet-perf] FAIL: %s" % p)
	print("CARPET_PERF_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if (ok and not _perf_failed) else 1)
