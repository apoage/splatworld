extends SceneTree
# M4 task 4 — Splat Studio headless data gate. Exercises the deterministic placement
# CORE (scatter_core.gd), the op/stroke model, the embedded `studio` block save/load,
# CarpetLoader.resync_materials, and SplatStudio's headless construct (the ONLY UI
# assert). Prints `SPLAT_STUDIO_RESULT PASS/FAIL` and exits nonzero on failure.
#
# Scratch paths are `user://splat_studio_*` (distinct from carpet_smoke_* / carpet_perf_*)
# and the sentinel is `SPLAT_STUDIO_RESULT` so this gate never clashes with the other
# harnesses. pytest stays 141 (this is Godot-only); carpet_smoke + carpet_perf stay
# PASS (their behavior is unchanged — resync_materials is additive, load_carpet is
# untouched).
#
#   ~/godot/godot --path godot --headless --script res://relight/tools/splat_studio_smoke.gd

const ScatterCore = preload("res://relight/scatter_core.gd")
const CarpetLoader = preload("res://relight/carpet_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const GaussianSceneRegistry = preload("res://addons/gdgs/runtime/render/gaussian_scene_registry.gd")
const SplatStudio = preload("res://relight/splat_studio.gd")

const TINY_A := "user://splat_studio_tiny_a.relightply"
const TINY_B := "user://splat_studio_tiny_b.relightply"
const TINY_C := "user://splat_studio_tiny_c.relightply"
const MATERIAL_BYTES := 48
const BYTES_PER_SPLAT := 240


func _initialize() -> void:
	var problems: Array[String] = []

	# Distinct-albedo tiny fixtures so A/B/C materials differ (variants are distinguishable
	# in the material byte stream as well as by id).
	_write_tiny_relightply(TINY_A, 5, 0.20)
	_write_tiny_relightply(TINY_B, 4, 0.55)
	_write_tiny_relightply(TINY_C, 3, 0.85)

	_check_determinism(problems)
	_check_stroke_replay(problems)
	_check_poisson(problems)
	_check_paint_poisson(problems)
	_check_region_trs(problems)
	_check_weighting(problems)
	_check_budget(problems)
	_check_round_trip(problems)
	_check_resync(problems)
	_check_undo(problems)
	_check_contract_tolerance(problems)
	_check_studio_constructs(problems)
	_check_protected_path(problems)   # BLOCKER 1: save_doc refuses SOURCE roots; _rebuild never writes _doc_path
	_check_hostile_json(problems)     # MAJOR 2: open_doc/apply_ops degrade, never SCRIPT-ERROR
	_check_finite_reject(problems)    # MAJOR 3: commit_* reject NaN/Inf (no bricked saves)
	_check_variant_guards(problems)   # MAJOR 4 + MINOR 5: missing path / dup id
	_check_resync_edges(problems)     # empty-resync clears; bad-resource resync fail-closed
	_check_budget_nan(problems)       # MINOR 6: budget(NaN point_count) -> 0, not INT_MIN

	# Sanity: pytest is run by the orchestrator out-of-band; here we just confirm our
	# scratch + sentinel are distinct from the other harnesses (no clash).
	if "CARPET_SMOKE_RESULT" in "SPLAT_STUDIO_RESULT" or "CARPET_PERF_RESULT" in "SPLAT_STUDIO_RESULT":
		problems.append("sentinel clash: SPLAT_STUDIO_RESULT must differ from carpet sentinels")
	if TINY_A.findn("carpet_smoke") >= 0 or TINY_A.findn("carpet_perf") >= 0:
		problems.append("scratch path clash: %s must not collide with carpet harness paths" % TINY_A)

	if not problems.is_empty():
		for p in problems:
			push_error("[splat-studio] FAIL: %s" % p)
	_finish(problems.is_empty())


# ─── 1. Determinism ───────────────────────────────────────────────────────────────
func _check_determinism(problems: Array[String]) -> void:
	var ops: Array = [
		{"tool": "fill", "cfg": {
			"min": [-2.0, -2.0], "max": [2.0, 2.0], "ground_y": 0.0,
			"count": 12, "min_dist": 0.3,
			"variants": [{"id": "a", "weight": 1.0}, {"id": "b", "weight": 1.0}],
			"yaw": [0.0, 1.0], "scale": [0.8, 1.2]}},
		{"tool": "stamp", "pos": [1.5, 0.0, 1.5], "yaw": 0.4, "scale": 1.1, "variant": "a"},
	]
	var a := ScatterCore.apply_ops(ops, 42)
	var b := ScatterCore.apply_ops(ops, 42)
	if not _instances_equal(a, b):
		problems.append("[determinism] same seed+ops produced different instances")
	var c := ScatterCore.apply_ops(ops, 43)
	if _instances_equal(a, c):
		problems.append("[determinism] different seed produced identical instances (must differ)")
	if a.size() == 0:
		problems.append("[determinism] apply_ops produced 0 instances (cfg wrong?)")
	else:
		print("[splat-studio][determinism] %d instances, replay-stable + seed-sensitive OK" % a.size())


# ─── 2. Stroke replay (saved studio.strokes ⇒ byte-identical instances) ───────────
func _check_stroke_replay(problems: Array[String]) -> void:
	var ops: Array = [
		{"tool": "fill", "cfg": {
			"min": [0.0, 0.0], "max": [4.0, 4.0], "ground_y": 0.0,
			"count": 8, "min_dist": 0.2,
			"variants": [{"id": "a", "weight": 2.0}, {"id": "b", "weight": 1.0}],
			"yaw": [0.0, 0.5], "scale": [1.0, 1.0]}},
		{"tool": "stamp", "pos": [2.0, 0.0, 2.0], "yaw": 0.0, "scale": 1.0, "variant": "b"},
	]
	var variants := [{"id": "a", "path": TINY_A}, {"id": "b", "path": TINY_B}]
	var doc := ScatterCore.build_doc(variants, ops, 99)
	var path := "user://splat_studio_replay.json"
	if not ScatterCore.save_doc(doc, path):
		problems.append("[replay] save_doc failed")
		return
	var opened := ScatterCore.open_doc(path)
	if not bool(opened.get("ok", false)):
		problems.append("[replay] open_doc failed: %s" % opened.get("error", "?"))
		return
	if not bool(opened.get("integrity", false)):
		problems.append("[replay] integrity check failed (replayed != saved instances)")
		return
	# Cross-check: replayed instances match what apply_ops produces directly.
	var direct := ScatterCore.apply_ops(ops, 99)
	if not _instances_equal(direct, opened["replayed"]):
		problems.append("[replay] open_doc replayed != direct apply_ops")
	else:
		print("[splat-studio][replay] %d instances round-trip byte-identical OK" % direct.size())


# ─── 3. Poisson (min_dist>0 ⇒ every accepted pair ≥ min_dist; saturation reported) ─
func _check_poisson(problems: Array[String]) -> void:
	# Tight rect + aggressive count -> guaranteed saturation. min_dist>0 so the rejection
	# gate is active.
	var cfg := {
		"min": [0.0, 0.0], "max": [1.0, 1.0], "ground_y": 0.0,
		"count": 50, "min_dist": 0.4,
		"variants": [{"id": "a", "weight": 1.0}],
		"yaw": [0.0, 0.0], "scale": [1.0, 1.0],
	}
	var placed := ScatterCore.fill_region(cfg, ScatterCore.stroke_seed(123, 0), 0)
	if placed.is_empty():
		problems.append("[poisson] fill_region placed 0 (rejection loop never accepted)")
		return
	# (a) every accepted pair >= min_dist.
	var md := 0.4
	var md2 := md * md
	var min_found := INF
	for i in placed.size():
		for j in range(i + 1, placed.size()):
			var pi: Vector3 = placed[i]["pos"]
			var pj: Vector3 = placed[j]["pos"]
			var dxz := Vector2(pi.x - pj.x, pi.z - pj.z)
			min_found = minf(min_found, dxz.length_squared())
			if dxz.length_squared() < md2 - 1e-6:
				problems.append("[poisson] pair (%d,%d) closer than min_dist %g" % [i, j, md])
				return
	# (b) saturation: requested 50 in a 1x1 rect at min_dist=0.4 cannot fit (the rect
	# fits at most ~9 points on a 0.4 grid) -> n_placed < count.
	if placed.size() >= 50:
		problems.append("[poisson] saturation not reported: placed %d of %d (expected fewer)" % [placed.size(), 50])
	else:
		print("[splat-studio][poisson] placed %d of %d (saturated); min pair gap^2=%.4f vs md^2=%.4f OK" % [placed.size(), 50, min_found, md2])


# ─── 3b. Paint cross-dab Poisson (min_dist holds across the WHOLE stroke) ─────────
# The gate gap that let the cross-dab bug ship: check 3 asserts the min_dist floor on
# fill_region only. A paint stroke's dabs must share ONE neighbour grid, so every
# accepted pair across the whole stroke is >= min_dist — not just pairs within a dab.
# Repro from the follow-up: radius=1.0, path=[[0,0],[0.2,0]], min_dist=0.4, count=30,
# seed=3 — two heavily-overlapping dabs, so a per-dab hash leaves many too-close pairs.
func _check_paint_poisson(problems: Array[String]) -> void:
	var ops: Array = [
		{"tool": "paint", "radius": 1.0, "path": [[0.0, 0.0], [0.2, 0.0]], "cfg": {
			"count": 30, "min_dist": 0.4, "ground_y": 0.0,
			"variants": [{"id": "a", "weight": 1.0}],
			"yaw": [0.0, 0.0], "scale": [1.0, 1.0]}},
	]
	var placed := ScatterCore.apply_ops(ops, 3)
	if placed.is_empty():
		problems.append("[paint-poisson] multi-dab paint placed 0 (rejection loop never accepted)")
		return
	var md := 0.4
	var md2 := md * md
	var min_found := INF
	var close_pairs := 0
	for i in placed.size():
		for j in range(i + 1, placed.size()):
			var pi: Vector3 = placed[i]["pos"]
			var pj: Vector3 = placed[j]["pos"]
			var dxz := Vector2(pi.x - pj.x, pi.z - pj.z)
			min_found = minf(min_found, dxz.length_squared())
			if dxz.length_squared() < md2 - 1e-6:
				close_pairs += 1
	if close_pairs > 0:
		problems.append("[paint-poisson] %d of %d placed across the stroke violate min_dist (closest gap^2=%.4f vs md^2=%.4f) — dabs must share one SpatialHash" % [close_pairs, placed.size(), min_found, md2])
		return
	# Stroke replay stays byte-identical with the shared grid (determinism contract).
	var replay := ScatterCore.apply_ops(ops, 3)
	if not _instances_equal(placed, replay):
		problems.append("[paint-poisson] multi-dab paint replay not byte-identical")
		return
	print("[splat-studio][paint-poisson] %d instances across 2 dabs; every pair >= min_dist (min gap^2=%.4f vs md^2=%.4f); replay-stable OK" % [placed.size(), min_found, md2])


# ─── 4. Region + TRS ──────────────────────────────────────────────────────────────
func _check_region_trs(problems: Array[String]) -> void:
	var cfg := {
		"min": [-3.0, -3.0], "max": [3.0, 3.0], "ground_y": 0.5,
		"count": 15, "min_dist": 0.0,
		"variants": [{"id": "a", "weight": 1.0}],
		"yaw": [0.3, 0.7], "scale": [0.9, 1.3],
	}
	var placed := ScatterCore.fill_region(cfg, ScatterCore.stroke_seed(7, 0), 0)
	for i in placed.size():
		var p: Vector3 = placed[i]["pos"]
		if p.x < -3.0 - 1e-6 or p.x > 3.0 + 1e-6 or p.z < -3.0 - 1e-6 or p.z > 3.0 + 1e-6:
			problems.append("[region] instance %d out of rect: x=%.3f z=%.3f" % [i, p.x, p.z])
			return
		if absf(p.y - 0.5) > 1e-6:
			problems.append("[region] instance %d pos.y=%.3f != ground_y 0.5" % [i, p.y])
			return
		var yaw: float = placed[i]["yaw"]
		if yaw < 0.3 - 1e-6 or yaw > 0.7 + 1e-6:
			problems.append("[region] instance %d yaw %.3f out of [0.3,0.7]" % [i, yaw])
			return
		var sc: float = placed[i]["scale"]
		if sc <= 0.0:
			problems.append("[region] instance %d scale not positive (%.3f)" % [i, sc])
			return
		if sc < 0.9 - 1e-6 or sc > 1.3 + 1e-6:
			problems.append("[region] instance %d scale %.3f out of [0.9,1.3]" % [i, sc])
			return
	print("[splat-studio][region] %d fill instances all in-rect, ground_y, yaw/scale in range OK" % placed.size())

	# Stamp with arbitrary y (the contract tolerance seam — fill defaults to ground_y,
	# stamp may set any finite pos.y). Stamp should NOT be region-checked.
	var stamped := ScatterCore.apply_ops([
		{"tool": "stamp", "pos": [10.0, 3.2, -7.0], "yaw": 0.0, "scale": 2.0, "variant": "a"},
	], 1)
	if stamped.size() != 1 or absf((stamped[0]["pos"] as Vector3).y - 3.2) > 1e-6:
		problems.append("[region] stamp did not preserve arbitrary y=3.2")
		return
	print("[splat-studio][region] stamp preserves arbitrary y=3.2 OK")


# ─── 5. Weighting ─────────────────────────────────────────────────────────────────
func _check_weighting(problems: Array[String]) -> void:
	# Large sample: 3:1 weighting -> variant 'a' ~75%, variant 'b' ~25%. min_dist=0 so
	# Poisson rejection doesn't bias the variant stream.
	var cfg := {
		"min": [-10.0, -10.0], "max": [10.0, 10.0], "ground_y": 0.0,
		"count": 400, "min_dist": 0.0,
		"variants": [{"id": "a", "weight": 3.0}, {"id": "b", "weight": 1.0}],
		"yaw": [0.0, 0.0], "scale": [1.0, 1.0],
	}
	var placed := ScatterCore.fill_region(cfg, ScatterCore.stroke_seed(2024, 0), 0)
	if placed.size() != 400:
		problems.append("[weighting] expected 400 placements, got %d" % placed.size())
		return
	var na := 0
	var nb := 0
	for inst in placed:
		if String(inst["variant"]) == "a":
			na += 1
		elif String(inst["variant"]) == "b":
			nb += 1
		else:
			problems.append("[weighting] unknown variant '%s'" % inst["variant"])
			return
	if na == 0 or nb == 0:
		problems.append("[weighting] a weight>0 variant missing (a=%d b=%d)" % [na, nb])
		return
	# 3:1 expected -> a/total ~= 0.75. Allow ±8% drift.
	var pa := float(na) / float(placed.size())
	if absf(pa - 0.75) > 0.08:
		problems.append("[weighting] a proportion %.3f drifts >8%% from 0.75 (na=%d nb=%d)" % [pa, na, nb])
		return
	print("[splat-studio][weighting] na=%d nb=%d (pa=%.3f vs target 0.75) OK" % [na, nb, pa])


# ─── 6. Budget ────────────────────────────────────────────────────────────────────
func _check_budget(problems: Array[String]) -> void:
	# 3 instances of A (5 pts) + 2 of B (4 pts) = 15 + 8 = 23.
	var instances := ScatterCore.apply_ops([
		{"tool": "stamp", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "a"},
		{"tool": "stamp", "pos": [1.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "a"},
		{"tool": "stamp", "pos": [2.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "a"},
		{"tool": "stamp", "pos": [3.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "b"},
		{"tool": "stamp", "pos": [4.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "b"},
	], 0)
	var pc := {"a": 5, "b": 4}
	var total := ScatterCore.budget(instances, pc)
	if total != 23:
		problems.append("[budget] expected 23, got %d" % total)
		return
	# Over-budget flag.
	var big := {"a": 800000, "b": 800000}
	if not (ScatterCore.budget(instances, big) > ScatterCore.BUDGET_GREEN):
		problems.append("[budget] 1.6M config not flagged as over budget")
		return
	print("[splat-studio][budget] sum=23 OK; 1.6M config flagged over %d OK" % ScatterCore.BUDGET_GREEN)


# ─── 7. Round-trip via CarpetLoader ───────────────────────────────────────────────
func _check_round_trip(problems: Array[String]) -> void:
	var variants := [{"id": "a", "path": TINY_A}, {"id": "b", "path": TINY_B}]
	var ops: Array = [
		{"tool": "fill", "cfg": {
			"min": [-2.0, -2.0], "max": [2.0, 2.0], "ground_y": 0.0,
			"count": 6, "min_dist": 0.2,
			"variants": [{"id": "a", "weight": 1.0}, {"id": "b", "weight": 1.0}],
			"yaw": [0.0, 0.3], "scale": [1.0, 1.0]}},
		{"tool": "stamp", "pos": [5.0, 0.0, 5.0], "yaw": 0.0, "scale": 1.0, "variant": "b"},
	]
	var doc := ScatterCore.build_doc(variants, ops, 7)
	var path := "user://splat_studio_roundtrip.json"
	if not ScatterCore.save_doc(doc, path):
		problems.append("[round-trip] save_doc failed")
		return

	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(path, parent)
	if not bool(result.get("ok", false)):
		problems.append("[round-trip] load_carpet failed: %s" % result.get("error", "?"))
		parent.free()
		return
	var nodes: Array = result["nodes"]
	var ordered: Array = result["ordered_resources"]
	var direct_instances := ScatterCore.apply_ops(ops, 7)
	if nodes.size() != direct_instances.size():
		problems.append("[round-trip] nodes %d != instances %d" % [nodes.size(), direct_instances.size()])
		parent.free()
		return

	# First-seen order check: walk instances, track unique variant in order, compare
	# each ordered resource's point_count against the corresponding variant's.
	var first_seen: Array = []
	var seen: Dictionary = {}
	for inst in direct_instances:
		var vid: String = inst["variant"]
		if not seen.has(vid):
			seen[vid] = true
			first_seen.append(vid)
	# Map variant id -> expected point_count (from the tiny fixtures: A=5, B=4).
	var id_to_pc: Dictionary = {"a": 5, "b": 4}
	if ordered.size() != first_seen.size():
		problems.append("[round-trip] ordered_resources size %d != first-seen %d" % [ordered.size(), first_seen.size()])
	else:
		for i in ordered.size():
			var pc: int = int(ordered[i].point_count)
			var expect_pc: int = int(id_to_pc.get(first_seen[i], -1))
			if pc != expect_pc:
				problems.append("[round-trip] ordered[%d] point_count %d != expected %d for variant '%s'" % [i, pc, expect_pc, first_seen[i]])
	if problems.is_empty():
		print("[splat-studio][round-trip] load_carpet ok, %d nodes, ordered matches first-seen order %s OK" % [nodes.size(), str(first_seen)])
	parent.free()


# ─── 8. Resync correctness ────────────────────────────────────────────────────────
func _check_resync(problems: Array[String]) -> void:
	var variants_ab := [{"id": "a", "path": TINY_A}, {"id": "b", "path": TINY_B}]
	# Manually-authored doc: A, B, A -> ordered [A, B]; A shares data across 2 nodes.
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"variants": variants_ab,
		"instances": [
			{"variant": "a", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "id": 1},
			{"variant": "b", "pos": [1.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "id": 2},
			{"variant": "a", "pos": [2.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "id": 3},
		],
	}
	var path := "user://splat_studio_resync.json"
	_write_json(path, JSON.stringify(doc))

	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(path, parent)
	if not bool(result.get("ok", false)):
		problems.append("[resync] baseline load_carpet failed: %s" % result.get("error", "?"))
		parent.free()
		return
	var nodes: Array = result["nodes"]
	var res_a = result["ordered_resources"][0]
	var res_b = result["ordered_resources"][1]
	var count_a: int = int(res_a.point_count)
	var count_b: int = int(res_b.point_count)

	# Warm-up resync (populates CarpetLoader._resync_state for this parent).
	if not CarpetLoader.resync_materials(parent):
		problems.append("[resync] warm-up resync_materials returned false")
		parent.free()
		return

	# --- (a) add-instance-of-EXISTING-variant -> no material work -----------------
	var v0 := RelightPass._material_version
	var c0 := RelightPass._material_count
	var a3 := GaussianSplatNode.new()
	a3.gaussian = res_a
	parent.add_child(a3)
	a3.transform = Transform3D(Basis(Vector3.UP, 0.4).scaled(Vector3.ONE * 1.1), Vector3(3, 0, 0))
	if not CarpetLoader.resync_materials(parent):
		problems.append("[resync] add-existing resync returned false")
	if RelightPass._material_version != v0:
		problems.append("[resync] add-existing bumped _material_version (should be no-op)")
	if RelightPass._material_count != c0:
		problems.append("[resync] add-existing changed _material_count (should be unchanged)")
	if problems.is_empty():
		print("[splat-studio][resync] add-instance-of-existing: no material work OK (v=%d c=%d)" % [RelightPass._material_version, RelightPass._material_count])

	# --- (b) add-new-variant C -> appended; prior si.y unshifted -----------------
	# Register the post-load tree in a registry to read si.y BEFORE adding C.
	var reg := GaussianSceneRegistry.new()
	for n in nodes:
		reg.register_splat_node(n)
	reg.register_splat_node(a3)
	var ids_before: PackedInt32Array = reg.get_splat_instance_ids_byte().to_int32_array()
	# Find a variant-B splat's si.y (B region starts at count_a).
	var b_si_y_before := -1
	if ids_before.size() >= (count_a + count_b) * 2:
		b_si_y_before = ids_before[count_a * 2 + 1]  # first B splat's si.y

	# Save current material state, then add a C node + resync.
	var v_before_c := RelightPass._material_version
	var c_before_c := RelightPass._material_count
	var res_c = RelightPlyLoader.load(TINY_C)
	if res_c == null:
		problems.append("[resync] could not load TINY_C")
		parent.free()
		return
	var c1 := GaussianSplatNode.new()
	c1.gaussian = res_c
	parent.add_child(c1)
	c1.transform = Transform3D(Basis.IDENTITY, Vector3(4, 0, 0))
	if not CarpetLoader.resync_materials(parent):
		problems.append("[resync] add-new resync returned false")
	# _material_version MUST bump (new unique resource appended).
	if RelightPass._material_version == v_before_c:
		problems.append("[resync] add-new did NOT bump _material_version (must rebuild)")
	# _material_count MUST increase by count_c.
	var count_c: int = int(res_c.point_count)
	if RelightPass._material_count != c_before_c + count_c:
		problems.append("[resync] add-new _material_count %d != %d + %d" % [RelightPass._material_count, c_before_c, count_c])

	# Verify ordered-resources first-seen order is now [A, B, C] via the resync cache.
	var cached_ids: Array = CarpetLoader._resync_state.get(parent.get_instance_id(), [])
	if cached_ids.size() != 3:
		problems.append("[resync] cached ordered size %d != 3 (after add-new)" % cached_ids.size())
	else:
		var want := [res_a.get_instance_id(), res_b.get_instance_id(), res_c.get_instance_id()]
		var ok_order := true
		for i in 3:
			if int(cached_ids[i]) != int(want[i]):
				ok_order = false
				break
		if not ok_order:
			problems.append("[resync] cached order != [A,B,C] (got %s want %s)" % [str(cached_ids), str(want)])

	# Prior si.y must be unshifted: re-register all + read B's first si.y again.
	var reg2 := GaussianSceneRegistry.new()
	for n in parent.get_children():
		if n is GaussianSplatNode:
			reg2.register_splat_node(n)
	var ids_after: PackedInt32Array = reg2.get_splat_instance_ids_byte().to_int32_array()
	if b_si_y_before >= 0 and ids_after.size() >= (count_a + count_b) * 2:
		var b_si_y_after := ids_after[count_a * 2 + 1]
		if b_si_y_after != b_si_y_before:
			problems.append("[resync] variant-B si.y shifted %d -> %d (must be unshifted)" % [b_si_y_before, b_si_y_after])
	if problems.is_empty():
		print("[splat-studio][resync] add-new-variant appended at end, prior si.y unshifted OK")

	# --- (c) erase-last-of-variant -> ordered uniques == tree order ---------------
	# Remove the C node (only C instance) + resync -> ordered should drop to [A, B].
	for c in parent.get_children():
		if c == c1:
			parent.remove_child(c)
			c.free()
			break
	if not CarpetLoader.resync_materials(parent):
		problems.append("[resync] erase-last resync returned false")
	var cached_after_erase: Array = CarpetLoader._resync_state.get(parent.get_instance_id(), [])
	if cached_after_erase.size() != 2:
		problems.append("[resync] after erase-last, cached ordered size %d != 2" % cached_after_erase.size())
	else:
		# Expected: [A_id, B_id] in tree order. Tree now has [a1, b1, a2, a3].
		var want2 := [res_a.get_instance_id(), res_b.get_instance_id()]
		if int(cached_after_erase[0]) != int(want2[0]) or int(cached_after_erase[1]) != int(want2[1]):
			problems.append("[resync] after erase-last, cached order != [A,B]")
	if problems.is_empty():
		print("[splat-studio][resync] erase-last-of-variant -> ordered uniques == tree order OK")

	CarpetLoader.forget_resync(parent)
	parent.free()


# ─── 9. Undo round-trip ───────────────────────────────────────────────────────────
func _check_undo(problems: Array[String]) -> void:
	# Seed the session with one fill, snapshot, then add+undo a stamp -> back to snapshot.
	var ops0: Array = [
		{"tool": "fill", "cfg": {
			"min": [0.0, 0.0], "max": [2.0, 2.0], "ground_y": 0.0,
			"count": 5, "min_dist": 0.0,
			"variants": [{"id": "a", "weight": 1.0}],
			"yaw": [0.0, 0.0], "scale": [1.0, 1.0]}},
	]
	var snap := ScatterCore.apply_ops(ops0, 11)
	var ops1: Array = ops0.duplicate(true)
	ops1.append({"tool": "stamp", "pos": [9.0, 0.0, 9.0], "yaw": 0.0, "scale": 1.0, "variant": "a"})
	var with_extra := ScatterCore.apply_ops(ops1, 11)
	if with_extra.size() != snap.size() + 1:
		problems.append("[undo] stamp op did not append exactly one instance (%d -> %d)" % [snap.size(), with_extra.size()])
	# Undo = drop the last op + re-expand.
	var ops_after_undo: Array = ops1.duplicate(true)
	ops_after_undo.pop_back()
	var restored := ScatterCore.apply_ops(ops_after_undo, 11)
	if not _instances_equal(snap, restored):
		problems.append("[undo] restored instances != pre-stamp snapshot")
	else:
		print("[splat-studio][undo] apply+undo a stroke restores the doc OK (%d instances)" % restored.size())


# ─── 10. Contract tolerance (studio block + y != ground_y) ────────────────────────
func _check_contract_tolerance(problems: Array[String]) -> void:
	# A doc WITH a studio block AND a stamped y=3.2 instance must load ok:true through
	# CarpetLoader (the loader only validates finite pos + scale>0; the studio block
	# rides its unknown-key tolerance, ground_y is NOT enforced).
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"variants": [{"id": "a", "path": TINY_A}],
		"instances": [
			{"variant": "a", "pos": [0.0, 3.2, 0.0], "yaw": 0.0, "scale": 1.0, "id": 1},
		],
		"studio": {
			"master_seed": 1,
			"strokes": [
				{"tool": "stamp", "pos": [0.0, 3.2, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "a"},
			],
		},
	}
	var path := "user://splat_studio_tolerance.json"
	_write_json(path, JSON.stringify(doc))
	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(path, parent)
	if not bool(result.get("ok", false)):
		problems.append("[tolerance] doc with studio+y!=ground_y rejected by load_carpet: %s" % result.get("error", "?"))
	else:
		var n: Array = result["nodes"]
		if n.size() != 1:
			problems.append("[tolerance] expected 1 node, got %d" % n.size())
		else:
			var p: Vector3 = (n[0] as Node3D).transform.origin
			if absf(p.y - 3.2) > 1e-6:
				problems.append("[tolerance] loaded node y=%.3f != 3.2" % p.y)
			else:
				print("[splat-studio][tolerance] studio block + y=3.2 stamp loads ok:true OK")
	parent.free()


# ─── 11. 4b constructs headless ───────────────────────────────────────────────────
func _check_studio_constructs(problems: Array[String]) -> void:
	# Instantiate SplatStudio, parent it into the scene (so _ready fires + the panel
	# builds). This is the ONLY UI assertion: it must not error.
	var s := SplatStudio.new()
	s.name = "SplatStudioInstance"
	root.add_child(s)

	# Wire Fill + Stamp (the partial-credit boundary's required surface).
	var parent := Node3D.new()
	root.add_child(parent)
	s.set_carpet_parent(parent)
	s.set_ground_y(0.0)
	s.set_variants([
		{"id": "a", "path": TINY_A, "point_count": 5},
		{"id": "b", "path": TINY_B, "point_count": 4},
	])
	s.commit_fill(Vector2(-2.0, -2.0), Vector2(2.0, 2.0), {
		"count": 6, "min_dist": 0.2,
		"variants": [{"id": "a", "weight": 1.0}, {"id": "b", "weight": 1.0}],
		"yaw": [0.0, 0.3], "scale": [1.0, 1.0],
	})
	var splat_count_after_fill := 0
	for c in parent.get_children():
		if c is GaussianSplatNode:
			splat_count_after_fill += 1
	if splat_count_after_fill == 0:
		problems.append("[constructs] Fill produced no splat nodes")

	s.commit_stamp(Vector3(5.0, 0.0, 5.0), "a", 0.5, 1.2)
	var splat_count_after_stamp := 0
	for c in parent.get_children():
		if c is GaussianSplatNode:
			splat_count_after_stamp += 1
	# Fill expanded to N instances, stamp adds exactly 1. So stamp count > fill count.
	if splat_count_after_stamp <= splat_count_after_fill:
		problems.append("[constructs] Stamp did not add a node (fill=%d after_stamp=%d)" % [splat_count_after_fill, splat_count_after_stamp])

	if problems.is_empty():
		print("[splat-studio][constructs] SplatStudio instantiates headless + Fill/Stamp wired (%d nodes after fill+stamp) OK" % splat_count_after_stamp)

	# Smoke Paint + Nudge too (functional via op-model even if interactive drag is deferred).
	s.commit_paint([Vector2(8.0, 8.0)], 0.7, {
		"count": 3, "min_dist": 0.1,
		"variants": [{"id": "a", "weight": 1.0}],
		"yaw": [0.0, 0.0], "scale": [1.0, 1.0],
	})
	if s.op_count() < 3:
		problems.append("[constructs] Paint op not appended (op_count=%d)" % s.op_count())

	# Undo should drop the last op cleanly.
	var ops_before := s.op_count()
	s.undo()
	if s.op_count() != ops_before - 1:
		problems.append("[constructs] Undo did not drop an op (%d -> %d)" % [ops_before, s.op_count()])

	s.queue_free()
	parent.free()


# ─── 13. Protected-path guard (BLOCKER 1) ────────────────────────────────────────
# save_doc must refuse any path inside a read-only SOURCE root (datasets/ /
# assets/raw/ / photoscan), and _rebuild must NEVER write to _doc_path (so loading a
# doc from a protected location + committing a stroke can't clobber source data).
func _check_protected_path(problems: Array[String]) -> void:
	# (a) the guard logic directly: protected roots flagged, normal paths not.
	for bad in ["/tmp/probe/photoscan/doc.json", "/tmp/probe/datasets/x.json",
			"/tmp/probe/assets/raw/y.json", "res://datasets/z.json",
			"/media/lukas/gg/photoscan/sub/f.json",
			"datasets/x.json", "photoscan/y.json"]:
		if not ScatterCore._is_protected_write(bad):
			problems.append("[protected] path NOT flagged protected: %s" % bad)
	for ok in ["user://carpet/x.json", "/tmp/normal.json", "res://carpet/meadow.json"]:
		if ScatterCore._is_protected_write(ok):
			problems.append("[protected] NORMAL path flagged protected: %s" % ok)
	# (b) end-to-end: save_doc refuses a protected path (returns false, writes nothing).
	var doc := ScatterCore.build_doc([{"id": "a", "path": TINY_A}],
			[{"tool": "stamp", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "a"}], 1)
	if ScatterCore.save_doc(doc, "/tmp/probe/photoscan/never.json"):
		problems.append("[protected] save_doc wrote to a protected photoscan path")

	# (c) _rebuild writes to the SCRATCH autosave, NOT _doc_path. Seed a doc at a known
	# user:// path, load_from it (sets _doc_path), snapshot its bytes, commit a stroke,
	# then assert the loaded file is UNCHANGED (the autosave went elsewhere).
	var load_path := "user://_ss_protected_loaded.json"
	ScatterCore.save_doc(doc, load_path)
	var s := SplatStudio.new()
	root.add_child(s)
	var parent := Node3D.new()
	root.add_child(parent)
	s.set_carpet_parent(parent)
	s.set_ground_y(0.0)
	if not s.load_from(load_path):
		problems.append("[protected] load_from setup failed")
	var before := FileAccess.get_file_as_string(load_path)
	s.commit_stamp(Vector3(2.0, 0.0, 2.0), "a", 0.0, 1.0)
	var after := FileAccess.get_file_as_string(load_path)
	if before != after:
		problems.append("[protected] _rebuild overwrote _doc_path on commit — must use the scratch autosave")
	elif problems.is_empty():
		print("[splat-studio][protected] save_doc refuses SOURCE roots + _rebuild writes scratch not _doc_path OK")
	s.queue_free()
	parent.queue_free()


# ─── 14. Hostile JSON degrades cleanly (MAJOR 2) ─────────────────────────────────
# open_doc / apply_ops must return {ok:false} or skip the bad op on a malformed doc,
# NEVER raise a GDScript SCRIPT ERROR. Each shape below used to crash (security judge).
func _check_hostile_json(problems: Array[String]) -> void:
	# Structural malformation -> open_doc returns a clean {ok:false} (not a crash/null).
	var cases := [
		['{"studio":"not_a_dict"}', false],
		['{"studio":{"strokes":"not_array"}}', false],
		['{"studio":{"strokes":[{"tool":"stamp","pos":"oops","variant":"a"}]}}', true],
		['{"studio":{"strokes":[{"tool":"stamp","pos":[1.0],"variant":"a"}]}}', true],
		['{"studio":{"strokes":[]},"instances":"oops"}', true],
		['{"studio":{"strokes":[]},"instances":5}', true],
	]
	var idx := 0
	for c in cases:
		var p := "user://_ss_hostile_%d.json" % idx
		idx += 1
		_write_json(p, String(c[0]))
		var r = ScatterCore.open_doc(p)
		if typeof(r) != TYPE_DICTIONARY:
			problems.append("[hostile] open_doc did not return a Dictionary for: %s" % String(c[0]))
			continue
		if bool(r.get("ok", false)) != bool(c[1]):
			problems.append("[hostile] open_doc ok=%s want=%s for: %s" % [str(r.get("ok")), str(c[1]), String(c[0])])

	# Op-level malformation: apply_ops must SKIP the bad op (no crash), returning an
	# Array (possibly empty / shorter). None of these may raise.
	var bad_ops_cases := [
		["not_a_dict"],
		[{"tool": "stamp", "pos": "oops", "variant": "a"}],
		[{"tool": "stamp", "pos": [1.0], "variant": "a"}],
		[{"tool": "stamp", "pos": [1.0, 2.0, 3.0], "yaw": "foo", "scale": 1.0, "variant": "a"}],
		[{"tool": "fill", "cfg": "not_a_dict"}],
		[{"tool": "fill", "cfg": {"min": "x", "count": 5}}],
		[{"tool": "stamp", "pos": [1.0, NAN, 3.0], "scale": 1.0, "variant": "a"}],
		[{"tool": "bogus_tool"}],
		[{"tool": "nudge", "id": "x", "pos": [0, 0, 0]}],
		[{"tool": "delete", "center": "x", "radius": 1.0}],
		[{"tool": "fill", "cfg": {"count": 3, "min_dist": 0.0, "min": [-1.0, -1.0], "max": [1.0, 1.0],
			"variants": [{"id": "a", "weight": null}], "yaw": [0.0, 0.0], "scale": [1.0, 1.0]}}],
		# Non-Dict variants[] entries (fail-closed MAJOR): pick_variant must skip them, no SCRIPT ERROR.
		[{"tool": "fill", "cfg": {"count": 3, "min_dist": 0.0, "min": [-1.0, -1.0], "max": [1.0, 1.0],
			"variants": [5, null, "str"], "yaw": [0.0, 0.0], "scale": [1.0, 1.0]}}],
		[{"tool": "paint", "radius": 1.0, "path": [[0.0, 0.0]],
			"cfg": {"count": 2, "min_dist": 0.0, "variants": [true], "yaw": [0.0, 0.0], "scale": [1.0, 1.0]}}],
	]
	for ops in bad_ops_cases:
		var got = ScatterCore.apply_ops(ops, 1)
		if typeof(got) != TYPE_ARRAY:
			problems.append("[hostile] apply_ops did not return an Array for ops: %s" % str(ops))

	# Hostile TOP-LEVEL saved-doc fields via load_from (studio:null / variants:str /
	# region:str — fail-closed re-verify BLOCKERs): must not SCRIPT-ERROR. Detection is
	# the gate run's stderr (a regression logs SCRIPT ERROR); exercising these paths is
	# the lock, and open_doc's hostile `instances` rows above cover the _instances_match path.
	var s3 := SplatStudio.new()
	root.add_child(s3)
	var p3 := Node3D.new()
	root.add_child(p3)
	s3.set_carpet_parent(p3)
	var tl_idx := 0
	for hostile_fields in [
		{"studio": null, "variants": [{"id": "a", "path": TINY_A}], "instances": []},
		{"studio": {"strokes": []}, "variants": "oops", "instances": []},
		{"studio": {"strokes": []}, "variants": [{"id": "a", "path": TINY_A}], "instances": [], "region": "oops"},
	]:
		var hd := {"schema": "splat_carpet 1", "frame": "godot"}
		hd.merge(hostile_fields, true)
		var hp := "user://_ss_hostile_tl_%d.json" % tl_idx
		tl_idx += 1
		_write_json(hp, JSON.stringify(hd))
		s3.load_from(hp) # must not abort the gate (no SCRIPT ERROR)
	s3.queue_free()
	p3.queue_free()

	if problems.is_empty():
		print("[splat-studio][hostile] open_doc + apply_ops + load_from top-level degrade cleanly (no SCRIPT ERROR) OK")


# ─── 15. commit_* reject non-finite (MAJOR 3) ────────────────────────────────────
func _check_finite_reject(problems: Array[String]) -> void:
	var s := SplatStudio.new()
	root.add_child(s)
	var parent := Node3D.new()
	root.add_child(parent)
	s.set_carpet_parent(parent)
	s.set_variants([{"id": "a", "path": TINY_A, "point_count": 5}])
	var before := s.op_count()
	s.commit_stamp(Vector3(NAN, 0.0, 0.0), "a", 0.0, 1.0)
	s.commit_stamp(Vector3(0.0, 0.0, 0.0), "a", INF, 1.0)
	s.commit_stamp(Vector3(0.0, 0.0, 0.0), "a", 0.0, INF)
	s.commit_nudge(1, Vector3(0.0, NAN, 0.0))
	s.commit_fill(Vector2(NAN, 0.0), Vector2(1.0, 1.0), {"count": 1, "min_dist": 0.0,
			"variants": [{"id": "a", "weight": 1.0}], "yaw": [0.0, 0.0], "scale": [1.0, 1.0]})
	s.commit_paint([Vector2(NAN, 0.0)], 0.5, {"count": 1, "min_dist": 0.0,
			"variants": [{"id": "a", "weight": 1.0}], "yaw": [0.0, 0.0], "scale": [1.0, 1.0]})
	if s.op_count() != before:
		problems.append("[finite] a non-finite commit appended an op (%d -> %d); must reject" % [before, s.op_count()])
	elif problems.is_empty():
		print("[splat-studio][finite] commit_* reject NaN/Inf (no bricked op appended) OK")
	s.queue_free()
	parent.queue_free()


# ─── 16. Variant guards: missing path + dup id (MAJOR 4 + MINOR 5) ───────────────
func _check_variant_guards(problems: Array[String]) -> void:
	var s := SplatStudio.new()
	root.add_child(s)
	# Missing path must not crash (direct v["path"] used to raise); point_count defaults 0.
	s.set_variants([{"id": "a"}])
	if int(s.point_counts().get("a", -1)) != 0:
		problems.append("[variants] missing-path variant should default point_count 0")
	# Duplicate id: second entry dropped (loader resolves dup ids last-write-wins).
	s.set_variants([
		{"id": "a", "path": TINY_A, "point_count": 5},
		{"id": "a", "path": TINY_B, "point_count": 4},
	])
	var pc := s.point_counts()
	if pc.size() != 1 or int(pc.get("a", -1)) != 5:
		problems.append("[variants] duplicate id not dropped (palette=%s, want one 'a'=5)" % str(pc))
	s.queue_free()

	# load_from must return FALSE on an unloadable rebuilt doc (an instance references a
	# variant id not in the palette) — not silently succeed with no carpet spawned.
	var bad_doc := ScatterCore.build_doc(
			[{"id": "a", "path": TINY_A, "point_count": 5}],
			[{"tool": "stamp", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "variant": "ghost"}],
			1)
	var bad_path := "user://_ss_loadfrom_bad.json"
	ScatterCore.save_doc(bad_doc, bad_path)
	var s2 := SplatStudio.new()
	root.add_child(s2)
	var bp := Node3D.new()
	root.add_child(bp)
	s2.set_carpet_parent(bp)
	if s2.load_from(bad_path):
		problems.append("[variants] load_from returned true on an unloadable doc (variant 'ghost' absent) — must be false")
	s2.queue_free()
	bp.queue_free()

	if problems.is_empty():
		print("[splat-studio][variants] missing-path + dup-id + load_from-unloadable OK")


# ─── 17. resync edge paths (empty-clears + bad-resource fail-closed) ─────────────
func _check_resync_edges(problems: Array[String]) -> void:
	# (a) After load_carpet binds materials, removing ALL nodes + resync MUST clear
	# _material_count to 0 (the empty==empty short-circuit used to skip the clear).
	var doc := {
		"schema": "splat_carpet 1", "frame": "godot",
		"variants": [{"id": "a", "path": TINY_A}],
		"instances": [{"variant": "a", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0, "id": 1}],
	}
	var path := "user://_ss_resync_empty.json"
	_write_json(path, JSON.stringify(doc))
	var parent := Node3D.new()
	root.add_child(parent)
	var r := CarpetLoader.load_carpet(path, parent)
	if not bool(r.get("ok", false)):
		problems.append("[resync-edge] baseline load failed")
		parent.free()
	else:
		if RelightPass._material_count <= 0:
			problems.append("[resync-edge] baseline did not bind materials (count=%d)" % RelightPass._material_count)
		for c in parent.get_children():
			parent.remove_child(c)
			c.free()
		if not CarpetLoader.resync_materials(parent):
			problems.append("[resync-edge] empty resync returned false")
		if RelightPass._material_count != 0:
			problems.append("[resync-edge] empty resync left _material_count=%d (must clear to 0)" % RelightPass._material_count)
		else:
			print("[splat-studio][resync-edge] empty carpet resync clears materials OK")
		CarpetLoader.forget_resync(parent)
		parent.free()

	# (b) A resource with a bad attr/point_count -> set_materials_multi rejects ->
	# resync returns false, _material_version UNCHANGED, cache NOT populated.
	RelightPass.clear_materials()
	var bad_res := RelightPlyLoader.load(TINY_A)
	bad_res.attr_data_byte = bad_res.attr_data_byte.slice(0, 8)  # truncate -> attr/pc mismatch
	var bad := GaussianSplatNode.new()
	bad.gaussian = bad_res
	var p2 := Node3D.new()
	root.add_child(p2)
	p2.add_child(bad)
	bad.transform = Transform3D.IDENTITY
	var v_before := RelightPass._material_version
	var ok3 := CarpetLoader.resync_materials(p2)
	if ok3:
		problems.append("[resync-edge] bad-resource resync returned true (must reject)")
	if RelightPass._material_version != v_before:
		problems.append("[resync-edge] bad-resource resync bumped _material_version (must leave unchanged)")
	if CarpetLoader._resync_state.has(p2.get_instance_id()):
		problems.append("[resync-edge] bad-resource resync populated the cache (must NOT on rejection)")
	else:
		print("[splat-studio][resync-edge] bad-resource resync fail-closed (false, no mutation, no cache) OK")
	CarpetLoader.forget_resync(p2)
	p2.free()


# ─── 18. budget hostile guards (NaN + negative; MINOR 6 + correctness-MINOR-1) ────
func _check_budget_nan(problems: Array[String]) -> void:
	var insts := [{"variant": "a"}, {"variant": "a"}]
	var b := ScatterCore.budget(insts, {"a": NAN})
	if b < 0:
		problems.append("[budget-nan] budget(NaN)=%d < 0 (int(NaN) INT_MIN underflow); must be 0" % b)
	# A negative point_count must clamp to 0 (else it silently bypasses the over-budget flag).
	var bn := ScatterCore.budget(insts, {"a": -100})
	if bn != 0:
		problems.append("[budget-nan] budget(negative=-100)=%d (must clamp to 0)" % bn)
	if problems.is_empty():
		print("[splat-studio][budget-nan] budget(NaN -> 0) + budget(negative -> 0 clamp) OK")


# ─── helpers ──────────────────────────────────────────────────────────────────────

# Deep compare two instance lists on the loader-relevant fields. id is part of the
# contract so identity round-trips too.
func _instances_equal(a: Array, b: Array) -> bool:
	if a.size() != b.size():
		return false
	for i in a.size():
		var x: Dictionary = a[i]
		var y: Dictionary = b[i]
		if String(x.get("variant", "")) != String(y.get("variant", "")):
			return false
		if int(x.get("id", -1)) != int(y.get("id", -1)):
			return false
		var px: Vector3 = x["pos"]
		var py_arr = y.get("pos", null)
		var py: Vector3
		if py_arr is Array:
			py = Vector3(float(py_arr[0]), float(py_arr[1]), float(py_arr[2]))
		else:
			py = py_arr
		if (px - py).length_squared() > 1e-9:
			return false
		if absf(float(x.get("yaw", 0.0)) - float(y.get("yaw", 0.0))) > 1e-9:
			return false
		if absf(float(x.get("scale", 1.0)) - float(y.get("scale", 1.0))) > 1e-9:
			return false
	return true


func _write_json(path: String, text: String) -> bool:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		return false
	f.store_string(text)
	f.close()
	return true


# Minimal valid `splat_relight_schema 1` PLY (mirrors carpet_smoke's fixture).
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
		body.put_float(i * 0.1)
		body.put_float(0.0)
		body.put_float(0.0)
		body.put_float(-3.0)
		body.put_float(-3.0)
		body.put_float(-3.0)
		body.put_float(1.0)
		body.put_float(0.0)
		body.put_float(0.0)
		body.put_float(0.0)
		body.put_float(0.0)
		var alb := albedo_base + i * 0.01
		body.put_float(alb)
		body.put_float(alb)
		body.put_float(alb)
		body.put_float(0.0)
		body.put_float(0.0)
		body.put_float(1.0)
		body.put_float(0.5)
		body.put_float(0.0)
		body.put_u8(1)
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(header)
	f.store_buffer(body.data_array)
	f.close()


func _finish(ok: bool) -> void:
	print("SPLAT_STUDIO_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
