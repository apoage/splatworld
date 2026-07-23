extends SceneTree
# M4 carpet data gate (headless). Proves the material-concat coupling of CarpetLoader +
# RelightPass.set_materials_multi at the DATA level (no GPU needed), and covers the
# fail-closed / atomicity paths.
#
# Runs FAST on self-generated tiny synthetic .vply fixtures (seconds), then repeats
# the happy-path coupling on the two real hero assets when present (skipped cleanly if the
# gitignored gs_assets are absent — the synthetic + failure coverage still runs and gates).
#
# Coupling assertions (synthetic AND hero when present):
#   1. VRAM dedup: unique upload points (point_data_byte/240) == Σ point_count over the
#      2 UNIQUE resources (one upload per resource, NOT per instance).
#   2. concat material size == Σ attr_data_byte over unique resources == unique_pts * 48;
#      _material_count == unique_pts.
#   3. total rendered points (get_point_count) == Σ point_count over INSTANCES.
#   4. every instance node LOCAL basis == its intended yaw+uniform-scale basis (D3:
#      transform set after add_child; not identity, not the GDGS -PI Z flip). LOCAL, not
#      global: a bare SceneTree._initialize() node reports is_inside_tree()==false so
#      global_transform is unusable here.
#   5. per-variant offset alignment (THE point): a splat known to belong to variant B has
#      si.y in B's concatenated material region, and materials[si.y] byte-equals variant
#      B's own material for that local index -> materials[si.y] resolves to the right
#      variant WITHOUT a GPU.
#
# Failure / atomicity assertions (synthetic):
#   (a) a bad instance mid-list -> ok:false, parent.get_child_count()==0, and RelightPass
#       _material_count UNCHANGED from before the call (all-or-nothing, no orphan nodes,
#       no stale material buffer).
#   (b) non-numeric pos (["foo",...]) rejected (not silently coerced to origin).
#   (c) non-finite yaw (1e999 -> inf) rejected.
#   (d) set_materials_multi([res, null]) returns false and mutates nothing; a valid
#       single-element array is byte-identical to set_materials (regression).
#
#   ~/godot/godot --path godot --headless --script res://relight/tools/carpet_smoke.gd

const CarpetLoader = preload("res://relight/carpet_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")
const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const GaussianSceneRegistry = preload("res://addons/gdgs/runtime/render/gaussian_scene_registry.gd")

const HERO_A := "res://gs_assets/pxl_144634.vply"
const HERO_B := "res://gs_assets/pxl_131945.vply"
const TINY_A := "user://carpet_smoke_tiny_a.vply"
const TINY_B := "user://carpet_smoke_tiny_b.vply"
const BYTES_PER_SPLAT := 240
const MATERIAL_BYTES := 48

# Fixed instance transforms authored by every happy-path (A, B, A order). Non-identity so
# the D3 check is meaningful.
const INST_YAW := [0.3, 1.1, -0.7]
const INST_SCALE := [1.2, 0.8, 1.5]
const TINY_NA := 5
const TINY_NB := 4


func _initialize() -> void:
	var problems: Array[String] = []

	# --- tiny synthetic fixtures (distinct albedo so A/B materials differ) ---
	_write_tiny_relightply(TINY_A, TINY_NA, 0.20)
	_write_tiny_relightply(TINY_B, TINY_NB, 0.70)

	# 1) fast synthetic happy-path coupling (proves the coupling with no gitignored assets)
	_run_coupling(problems, "synthetic", TINY_A, TINY_B)

	# 2) failure / atomicity paths (fast, synthetic)
	_test_atomic_partial(problems)
	_test_bad_pos(problems)
	_test_bad_yaw(problems)
	_test_bad_yaw_scale_types(problems)
	_test_null_material(problems)

	# 3) real-scale hero happy-path (skipped cleanly if gitignored assets absent)
	if FileAccess.file_exists(HERO_A) and FileAccess.file_exists(HERO_B):
		print("[carpet-smoke] hero assets present -> running real-scale coupling")
		_run_coupling(problems, "hero", HERO_A, HERO_B)
	else:
		print("[carpet-smoke] hero assets absent -> hero coupling SKIPPED (synthetic + failure paths still gate)")

	if not problems.is_empty():
		for p in problems:
			push_error("[carpet-smoke] FAIL: %s" % p)
	_finish(problems.is_empty())


# ---- happy-path coupling (shared by synthetic + hero) ------------------------
func _run_coupling(problems: Array[String], tag: String, path_a: String, path_b: String) -> void:
	# instances.json: A, B, A -> first-seen unique order [A, B]; A shares data across 2 nodes.
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"region": {"min": [-4, -4], "max": [4, 4], "ground_y": 0.0},
		"variants": [
			{"id": "a", "path": path_a},
			{"id": "b", "path": path_b},
		],
		"instances": [
			{"variant": "a", "pos": [0.0, 0.0, 0.0], "yaw": INST_YAW[0], "scale": INST_SCALE[0], "seed": 1},
			{"variant": "b", "pos": [2.0, 0.0, 0.0], "yaw": INST_YAW[1], "scale": INST_SCALE[1], "seed": 2},
			{"variant": "a", "pos": [-2.0, 0.0, 1.0], "yaw": INST_YAW[2], "scale": INST_SCALE[2], "seed": 3},
		],
	}
	var json_path := "user://carpet_smoke_%s.json" % tag
	if not _write_json(json_path, JSON.stringify(doc)):
		problems.append("[%s] cannot write %s" % [tag, json_path])
		return

	var parent := Node3D.new()
	root.add_child(parent)

	var result := CarpetLoader.load_carpet(json_path, parent)
	if not result.get("ok", false):
		problems.append("[%s] load_carpet failed: %s" % [tag, result.get("error", "?")])
		parent.free()
		return

	var nodes: Array = result["nodes"]
	var ordered: Array = result["ordered_resources"]
	var node_variant: Array = result["node_variant"]

	var registry: GaussianSceneRegistry = GaussianSceneRegistry.new()
	for n in nodes:
		registry.register_splat_node(n)

	if ordered.size() != 2:
		problems.append("[%s] ordered_resources size=%d (want 2)" % [tag, ordered.size()])
		parent.free()
		return
	var res_a = ordered[0]
	var res_b = ordered[1]
	var count_a: int = int(res_a.point_count)
	var count_b: int = int(res_b.point_count)
	var unique_pts := count_a + count_b
	var instance_pts := 2 * count_a + count_b

	print("[carpet-smoke][%s] count_a=%d count_b=%d unique_pts=%d instance_pts=%d nodes=%d" % [
		tag, count_a, count_b, unique_pts, instance_pts, nodes.size()])

	# assert 1: VRAM dedup
	var upload_pts: int = registry.get_point_data_byte().size() / BYTES_PER_SPLAT
	if upload_pts != unique_pts:
		problems.append("[%s] VRAM upload_pts=%d != unique_pts=%d (dedup broken)" % [tag, upload_pts, unique_pts])

	# assert 2: concat material size / count
	var concat_size: int = RelightPass._material_bytes.size()
	var sum_attr: int = res_a.attr_data_byte.size() + res_b.attr_data_byte.size()
	print("[carpet-smoke][%s] upload_pts=%d concat_material=%d sum_attr=%d material_count=%d" % [
		tag, upload_pts, concat_size, sum_attr, RelightPass._material_count])
	if concat_size != sum_attr:
		problems.append("[%s] concat material %d != Σ attr_data_byte %d" % [tag, concat_size, sum_attr])
	if concat_size != unique_pts * MATERIAL_BYTES:
		problems.append("[%s] concat material %d != unique_pts*48 %d" % [tag, concat_size, unique_pts * MATERIAL_BYTES])
	if RelightPass._material_count != unique_pts:
		problems.append("[%s] _material_count %d != unique_pts %d" % [tag, RelightPass._material_count, unique_pts])

	# assert 3: total rendered points == Σ over instances
	var rendered: int = registry.get_point_count()
	if rendered != instance_pts:
		problems.append("[%s] rendered_pts=%d != Σ instances %d" % [tag, rendered, instance_pts])

	# assert 4: local basis == intended yaw+scale (D3); not identity, not the GDGS flip
	var flip := GaussianSplatNode.get_model_orientation_correction().basis
	for i in nodes.size():
		var b: Basis = (nodes[i] as Node3D).transform.basis
		if b.is_equal_approx(Basis.IDENTITY):
			problems.append("[%s] node %d (variant %s) basis == identity (D3 violated)" % [tag, i, node_variant[i]])
		if b.is_equal_approx(flip):
			problems.append("[%s] node %d (variant %s) basis == GDGS -PI Z flip (D3 flip NOT suppressed)" % [tag, i, node_variant[i]])
		var want := Basis(Vector3.UP, float(INST_YAW[i])).scaled(Vector3.ONE * float(INST_SCALE[i]))
		if not b.is_equal_approx(want):
			problems.append("[%s] node %d (variant %s) basis != intended yaw/scale" % [tag, i, node_variant[i]])

	# assert 5: per-variant offset alignment (the highest-value coupling proof)
	# instance_ids are int32 pairs [transform_idx, unique_data_idx] laid out per node in
	# spawn order: node0(A)=count_a pairs, node1(B)=count_b pairs, node2(A)=count_a pairs.
	# node1's (variant B) pairs begin at pair index count_a; resource_start_B == count_a.
	var ids: PackedInt32Array = registry.get_splat_instance_ids_byte().to_int32_array()
	if ids.size() != rendered * 2:
		problems.append("[%s] instance_ids pairs=%d != rendered*2=%d" % [tag, ids.size(), rendered * 2])
	else:
		var local_b: int = mini(10, count_b - 1)
		var pair_index := count_a + local_b
		var x_idx := ids[pair_index * 2]
		var y_idx := ids[pair_index * 2 + 1]
		var expect_y := count_a + local_b
		print("[carpet-smoke][%s] B-splat local=%d pair@%d -> x=%d y=%d (expect y=%d)" % [
			tag, local_b, pair_index, x_idx, y_idx, expect_y])
		if y_idx != expect_y:
			problems.append("[%s] variant-B splat si.y=%d != expected %d (offset mis-aligned)" % [tag, y_idx, expect_y])
		if y_idx < count_a or y_idx >= count_a + count_b:
			problems.append("[%s] variant-B splat si.y=%d outside B region [%d,%d)" % [tag, y_idx, count_a, count_a + count_b])
		var concat_slice: PackedByteArray = RelightPass._material_bytes.slice(y_idx * MATERIAL_BYTES, y_idx * MATERIAL_BYTES + MATERIAL_BYTES)
		var b_slice: PackedByteArray = res_b.attr_data_byte.slice(local_b * MATERIAL_BYTES, local_b * MATERIAL_BYTES + MATERIAL_BYTES)
		if concat_slice != b_slice:
			problems.append("[%s] materials[si.y=%d] != variant B material[local=%d] (WRONG variant would shade)" % [tag, y_idx, local_b])
		else:
			print("[carpet-smoke][%s] materials[si.y] byte-matches variant B's own material (coupling OK)" % tag)
		# node2 (variant A, 2nd instance) must reuse A's region -> first pair y == 0.
		var a2_pair := count_a + count_b
		if a2_pair * 2 + 1 < ids.size():
			var a2_y := ids[a2_pair * 2 + 1]
			if a2_y != 0:
				problems.append("[%s] variant-A 2nd instance si.y=%d != 0 (dedup region reuse broken)" % [tag, a2_y])
			else:
				print("[carpet-smoke][%s] variant-A 2nd instance reuses A region (si.y=0) OK" % tag)

	parent.free()


# ---- failure / atomicity paths ----------------------------------------------

# (a) a bad instance MID-LIST must abort with zero nodes parented and RelightPass state
# unchanged (all-or-nothing). Captures _material_count before (nonzero from the synthetic
# happy-path above) and asserts it is unchanged after the failed load.
func _test_atomic_partial(problems: Array[String]) -> void:
	var before_count := RelightPass._material_count
	var before_ver := RelightPass._material_version
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"variants": [{"id": "a", "path": TINY_A}, {"id": "b", "path": TINY_B}],
		"instances": [
			{"variant": "a", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0},
			{"variant": "b", "pos": [1.0, 0.0, 0.0], "yaw": 0.0, "scale": -1.0}, # BAD scale, mid-list
			{"variant": "a", "pos": [2.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0},
		],
	}
	var json_path := "user://carpet_smoke_atomic.json"
	if not _write_json(json_path, JSON.stringify(doc)):
		problems.append("[atomic] cannot write json")
		return
	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(json_path, parent)
	if result.get("ok", true):
		problems.append("[atomic] load_carpet returned ok:true on a bad mid-list instance")
	if parent.get_child_count() != 0:
		problems.append("[atomic] %d orphan node(s) parented after failed load (must be 0)" % parent.get_child_count())
	if RelightPass._material_count != before_count:
		problems.append("[atomic] _material_count changed %d -> %d on failed load (not atomic)" % [before_count, RelightPass._material_count])
	if RelightPass._material_version != before_ver:
		problems.append("[atomic] _material_version bumped on failed load (RelightPass mutated)")
	if parent.get_child_count() == 0 and RelightPass._material_count == before_count:
		print("[carpet-smoke][atomic] failed mid-list load: 0 nodes parented, RelightPass unchanged (count=%d) OK" % before_count)
	parent.free()


# (b) non-numeric pos must be rejected, not coerced to origin.
func _test_bad_pos(problems: Array[String]) -> void:
	var doc := {
		"schema": "splat_carpet 1",
		"frame": "godot",
		"variants": [{"id": "a", "path": TINY_A}],
		"instances": [{"variant": "a", "pos": ["foo", "bar", "baz"], "yaw": 0.0, "scale": 1.0}],
	}
	var json_path := "user://carpet_smoke_badpos.json"
	if not _write_json(json_path, JSON.stringify(doc)):
		problems.append("[badpos] cannot write json")
		return
	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(json_path, parent)
	if result.get("ok", true):
		problems.append("[badpos] non-numeric pos accepted (must be rejected)")
	elif parent.get_child_count() != 0:
		problems.append("[badpos] node parented despite rejection")
	else:
		print("[carpet-smoke][badpos] non-numeric pos rejected OK")
	parent.free()


# (c) non-finite yaw (raw JSON 1e999 -> inf) must be rejected.
func _test_bad_yaw(problems: Array[String]) -> void:
	# Hand-written JSON so yaw parses to inf (JSON.stringify can't emit inf).
	var raw := '{"schema":"splat_carpet 1","frame":"godot","variants":[{"id":"a","path":"%s"}],"instances":[{"variant":"a","pos":[0,0,0],"yaw":1e999,"scale":1.0}]}' % TINY_A
	var json_path := "user://carpet_smoke_badyaw.json"
	if not _write_json(json_path, raw):
		problems.append("[badyaw] cannot write json")
		return
	var parent := Node3D.new()
	root.add_child(parent)
	var result := CarpetLoader.load_carpet(json_path, parent)
	if result.get("ok", true):
		problems.append("[badyaw] non-finite yaw accepted (must be rejected)")
	elif parent.get_child_count() != 0:
		problems.append("[badyaw] node parented despite rejection")
	else:
		print("[carpet-smoke][badyaw] non-finite yaw rejected OK")
	parent.free()


# (c2) yaw/scale that are the WRONG TYPE (array / object / string / bool) must be REJECTED
# with a proper {ok:false} dict (never a raised script error -> null return), and the load
# must stay atomic (0 nodes parented, RelightPass unchanged) even for a bad MID-LIST value.
func _test_bad_yaw_scale_types(problems: Array[String]) -> void:
	# key, bad JSON value, label
	var cases := [
		["yaw", [1, 2, 3], "yaw-array"],
		["scale", [1, 2, 3], "scale-array"],
		["yaw", "foo", "yaw-string"],
		["scale", "1.5", "scale-string"],
	]
	for c in cases:
		var key: String = c[0]
		var bad = c[1]
		var label: String = c[2]
		var mid := {"variant": "a", "pos": [1.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0}
		mid[key] = bad
		var doc := {
			"schema": "splat_carpet 1",
			"frame": "godot",
			"variants": [{"id": "a", "path": TINY_A}],
			"instances": [
				{"variant": "a", "pos": [0.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0},
				mid,  # bad value, MID-LIST
				{"variant": "a", "pos": [2.0, 0.0, 0.0], "yaw": 0.0, "scale": 1.0},
			],
		}
		var json_path := "user://carpet_smoke_type_%s.json" % label
		if not _write_json(json_path, JSON.stringify(doc)):
			problems.append("[%s] cannot write json" % label)
			continue
		var before_count := RelightPass._material_count
		var before_ver := RelightPass._material_version
		var parent := Node3D.new()
		root.add_child(parent)
		var result = CarpetLoader.load_carpet(json_path, parent)  # untyped: assert it's a real dict
		if typeof(result) != TYPE_DICTIONARY:
			problems.append("[%s] load_carpet did not return a Dictionary (raised instead of rejecting?)" % label)
		elif result.get("ok", true):
			problems.append("[%s] wrong-type %s accepted (must be rejected)" % [label, key])
		elif parent.get_child_count() != 0:
			problems.append("[%s] %d node(s) parented despite rejection (not atomic)" % [label, parent.get_child_count()])
		elif RelightPass._material_count != before_count or RelightPass._material_version != before_ver:
			problems.append("[%s] RelightPass mutated on rejected load (not atomic)" % label)
		else:
			print("[carpet-smoke][%s] wrong-type %s rejected cleanly, atomic OK" % [label, key])
		parent.free()


# (d) set_materials_multi with a null element must return false and mutate nothing; a valid
# single-element array must be byte-identical to set_materials (regression safety).
func _test_null_material(problems: Array[String]) -> void:
	var res_a: RelightGaussianResource = RelightPlyLoader.load(TINY_A)
	if res_a == null:
		problems.append("[nullmat] could not load tiny fixture")
		return

	# Establish a known state, then attempt the null-bearing call.
	RelightPass.set_materials_multi([res_a])
	var before_bytes := RelightPass._material_bytes.size()
	var before_count := RelightPass._material_count
	var before_ver := RelightPass._material_version
	var ok := RelightPass.set_materials_multi([res_a, null])
	if ok:
		problems.append("[nullmat] set_materials_multi([res, null]) returned true (must reject)")
	if RelightPass._material_bytes.size() != before_bytes or RelightPass._material_count != before_count or RelightPass._material_version != before_ver:
		problems.append("[nullmat] set_materials_multi mutated state on a null element")
	else:
		print("[carpet-smoke][nullmat] null element rejected, state unchanged OK")

	# Regression: single-element multi == static set_materials, byte-for-byte.
	RelightPass.set_materials_multi([res_a])
	var multi_bytes := RelightPass._material_bytes
	var multi_count := RelightPass._material_count
	RelightPass.set_materials(res_a.attr_data_byte, res_a.point_count)
	if RelightPass._material_bytes != multi_bytes or RelightPass._material_count != multi_count:
		problems.append("[nullmat] single-element set_materials_multi != set_materials (regression)")
	else:
		print("[carpet-smoke][nullmat] single-element multi byte-identical to set_materials OK")
	RelightPass.clear_materials()


# ---- helpers ----------------------------------------------------------------

func _write_json(path: String, text: String) -> bool:
	var wf := FileAccess.open(path, FileAccess.WRITE)
	if wf == null:
		return false
	wf.store_string(text)
	wf.close()
	return true


# Minimal valid `splat_relight_schema 1` binary_little_endian PLY: 19 float32 props + a
# uchar label per vertex. Values are finite and in-range; albedo_base separates variants.
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
		body.put_float(0.0)       # opacity (logit; loader applies sigmoid -> 0.5)
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


func _finish(ok: bool) -> void:
	print("CARPET_SMOKE_RESULT %s" % ("PASS" if ok else "FAIL"))
	quit(0 if ok else 1)
