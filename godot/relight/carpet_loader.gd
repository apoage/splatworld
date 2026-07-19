@tool
extends RefCounted
class_name CarpetLoader

# M4 carpet loader (task 1, THE SPINE). Instances a hand-written `instances.json`
# (D-INSTANCES-CONTRACT) into GaussianSplatNodes that SHARE Gaussian data by resource-
# object identity, and registers the concatenated per-variant materials with RelightPass.
#
# Contract (schema "splat_carpet 1"):
#   {"schema":"splat_carpet 1", "frame":"godot",
#    "region":{...}(optional, unused at load),
#    "variants":[{"id","path"}, ...],
#    "instances":[{"variant","pos":[x,y,z],"yaw","scale","seed"}, ...]}
# TRS-only: pos + single Y-yaw + SCALAR uniform scale (relight.glsl:187-191 transforms
# the normal with rotation-only mat3(model), so shear / non-uniform scale is forbidden —
# the contract structurally cannot express them). `seed` is reserved for M5 wind phase
# and ignored here. Only frame=="godot" is handled in task 1; frame=="blender_zup"
# conversion is task 6.
#
# The one fragile coupling (relight.glsl:170-171): the shader reads
# `materials[si.y]` where si.y is the GLOBAL unique splat-data index built by
# GaussianSceneRegistry in FIRST-SEEN order (= the order nodes are add_child'd =
# the order we spawn instances here). So the ordered unique-resource list passed to
# RelightPass.set_materials_multi MUST match that spawn/first-seen order, and each
# variant's .relightply resource OBJECT must be loaded ONCE and shared across all its
# instances (a re-load = a new object = a duplicate VRAM upload + wrong offsets).
#
# OWNERSHIP PRECONDITION (correctness): set_materials_multi OVERWRITES the single global
# RelightPass material buffer with ONLY this carpet's unique resources, in this carpet's
# spawn order. That buffer is indexed by the registry's GLOBAL first-seen order over ALL
# registered GaussianSplatNodes. Therefore the caller MUST guarantee the carpet owns the
# ENTIRE set of registered splat nodes: any OTHER GaussianSplatNode registered before the
# carpet's nodes (or a stale prior carpet not removed before a rebuild) prepends an entry
# to the registry's first-seen order that `ordered_resources` lacks -> every si.y shifts
# -> the whole scene mis-shades. Before calling load_carpet, remove/free any previously
# spawned carpet (and do not mix a lone single-asset RelightPlyLoader node into the same
# scene). The loader has no registry handle so this cannot be asserted here.
#
# ATOMICITY: load_carpet is all-or-nothing. It fully VALIDATES every instance (resolve
# variant, lazy-load its resource, check pos/yaw/scale) with NO add_child and NO
# RelightPass mutation FIRST; only once all instances validate does it spawn nodes and set
# materials. On any failure it mutates nothing and returns ok:false, so a failed (re)load
# can never leave orphan nodes in the render buffer or a stale material buffer that
# mismatches the merged point count (which would drive materials[si.y] out of bounds).

const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")
const RelightPass = preload("res://relight/relight_pass.gd")

const SCHEMA := "splat_carpet 1"
const FRAME_GODOT := "godot"

# Per-parent cache of the last resync's ordered resource IDs (instance_id() per
# RelightGaussianResource). Lets resync_materials detect the "unique set + order
# unchanged" case (add/remove an instance of an ALREADY-PLACED variant — the common
# incremental edit) and SKIP set_materials_multi entirely, so _material_version does
# not bump and no buffer is re-uploaded. Keyed by carpet_parent.get_instance_id() so
# two coexisting carpets (e.g. a compare-A/B scene) don't shadow each other.
static var _resync_state: Dictionary = {}


# Parses `json_path`, VALIDATES every instance, then (only if all valid) spawns one
# GaussianSplatNode per instance under `parent`, assigns the cached (shared) variant
# resource, add_child's it, THEN sets its transform (pos + Y-yaw + uniform scale) per D3,
# and finally registers the ordered unique-resource materials with RelightPass. Returns:
#   {"ok": bool, "error": String,
#    "nodes": Array[GaussianSplatNode],           # one per instance, spawn order
#    "ordered_resources": Array,                  # unique resources, first-seen order
#    "node_variant": Array[String]}               # variant id per node (parallel to nodes)
# On failure: nodes/ordered_resources/node_variant empty, no node parented, RelightPass
# untouched.
static func load_carpet(json_path: String, parent: Node) -> Dictionary:
	if parent == null:
		return _err("parent node is null")

	var f := FileAccess.open(json_path, FileAccess.READ)
	if f == null:
		return _err("cannot open %s" % json_path)
	var text := f.get_as_text()
	f.close()

	var parsed = JSON.parse_string(text)
	if parsed == null or not (parsed is Dictionary):
		return _err("%s: not a JSON object" % json_path)
	var doc: Dictionary = parsed

	if String(doc.get("schema", "")) != SCHEMA:
		return _err("%s: schema '%s' != '%s'" % [json_path, doc.get("schema", ""), SCHEMA])
	var frame := String(doc.get("frame", ""))
	if frame != FRAME_GODOT:
		return _err("%s: frame '%s' unsupported (task 1 handles '%s' only; blender_zup is task 6)" % [json_path, frame, FRAME_GODOT])

	var variants = doc.get("variants", null)
	if not (variants is Array) or (variants as Array).is_empty():
		return _err("%s: 'variants' missing or empty" % json_path)
	var instances = doc.get("instances", null)
	if not (instances is Array):
		return _err("%s: 'instances' missing" % json_path)

	# Map declared variant id -> path (no loading yet; resources load lazily on first
	# instance reference in the validation pass, so an unreferenced declared variant never
	# triggers a multi-million-splat parse).
	var variant_path := {}          # id -> path
	for v in variants:
		if not (v is Dictionary) or not v.has("id") or not v.has("path"):
			return _err("%s: variant entry missing 'id'/'path'" % json_path)
		variant_path[String(v["id"])] = String(v["path"])

	# ---- VALIDATION PASS: resolve + validate EVERY instance. No add_child, no
	# RelightPass mutation. Builds an in-memory spawn plan + first-seen unique list. ----
	var path_res := {}              # path -> RelightGaussianResource (load-once cache)
	var plan: Array = []            # [{res, origin:Vector3, yaw:float, scale:float, vid:String}]
	var ordered_resources: Array = []
	var seen := {}                  # resource instance_id -> true (first-seen tracking)

	for inst in instances:
		if not (inst is Dictionary):
			return _err("%s: instance is not an object" % json_path)
		var vid := String(inst.get("variant", ""))
		if not variant_path.has(vid):
			return _err("%s: instance references unknown variant '%s'" % [json_path, vid])

		# Lazy load (cache by path so two ids sharing a path -> same object -> one upload).
		var p: String = variant_path[vid]
		if not path_res.has(p):
			var r = RelightPlyLoader.load(p)
			if r == null:
				return _err("%s: variant '%s' failed to load '%s'" % [json_path, vid, p])
			path_res[p] = r
		var res = path_res[p]

		var origin = _to_vec3(inst.get("pos", null))
		if origin == null:
			return _err("%s: instance (variant '%s') has bad 'pos' (need 3 finite numbers)" % [json_path, vid])
		# yaw/scale MUST be JSON numbers — raw float() would throw on an array/object and
		# silently coerce a string/bool ("foo"->0, true->1). Reject non-numbers cleanly.
		var yaw_n = _as_number(inst.get("yaw", 0.0))
		if yaw_n == null:
			return _err("%s: instance (variant '%s') 'yaw' is not a number" % [json_path, vid])
		var yaw: float = yaw_n
		if not is_finite(yaw):
			return _err("%s: instance (variant '%s') has non-finite 'yaw'" % [json_path, vid])
		var scale_n = _as_number(inst.get("scale", 1.0))
		if scale_n == null:
			return _err("%s: instance (variant '%s') 'scale' is not a number" % [json_path, vid])
		var scale: float = scale_n
		if not is_finite(scale) or scale <= 0.0:
			return _err("%s: instance (variant '%s') has non-positive/non-finite scale %s" % [json_path, vid, str(scale)])

		# First-seen unique-resource registration MUST mirror the registry: append the
		# resource the FIRST time an instance uses it, in spawn (= instance) order.
		var rid: int = res.get_instance_id()
		if not seen.has(rid):
			seen[rid] = true
			ordered_resources.append(res)

		plan.append({"res": res, "origin": origin, "yaw": yaw, "scale": scale, "vid": vid})

	# ---- SPAWN PASS: every instance validated, so this cannot fail partway. ----
	var nodes: Array = []
	var node_variant: Array = []
	for e in plan:
		var node := GaussianSplatNode.new()
		node.gaussian = e["res"]
		parent.add_child(node)
		# D3: set the transform AFTER add_child so it overrides GDGS's conditional -PI Z
		# default flip (fires in _enter_tree only when transform ~= identity). TRS-only:
		# uniform scale * Y-yaw rotation, then origin. Rotation-only basis keeps
		# relight.glsl's mat3(model) normal transform valid.
		var s: float = e["scale"]
		var basis := Basis(Vector3.UP, float(e["yaw"])).scaled(Vector3(s, s, s))
		var origin: Vector3 = e["origin"]
		node.transform = Transform3D(basis, origin)
		nodes.append(node)
		node_variant.append(e["vid"])

	# Materials are per UNIQUE resource (one region per VRAM upload), concatenated in
	# first-seen order so materials[si.y] lands in the correct variant's region. Resources
	# were all validated above, so this should not fail; belt-and-suspenders, if it does we
	# free the just-spawned nodes to preserve the all-or-nothing guarantee.
	if not RelightPass.set_materials_multi(ordered_resources):
		for n in nodes:
			parent.remove_child(n)
			n.free()
		return _err("%s: set_materials_multi rejected the resource list" % json_path)

	return {
		"ok": true,
		"error": "",
		"nodes": nodes,
		"ordered_resources": ordered_resources,
		"node_variant": node_variant,
	}


# Returns `v` as a float iff it is a JSON NUMBER (int/float); null otherwise. Rejects
# strings/bools/arrays/objects/null so raw float() never throws (array/object) or silently
# coerces ("foo"->0.0, true->1.0). TYPE_BOOL is deliberately NOT in the allow-list.
static func _as_number(v) -> Variant:
	if typeof(v) != TYPE_FLOAT and typeof(v) != TYPE_INT:
		return null
	return float(v)


# Returns a Vector3 iff `v` is a 3-element array whose every element is a finite JSON
# NUMBER. Rejects strings/bools/null (float("foo")==0.0 would otherwise silently coerce a
# non-numeric pos to the origin). Returns null on any violation.
static func _to_vec3(v) -> Variant:
	if not (v is Array) or (v as Array).size() != 3:
		return null
	var a: Array = v
	var comp := PackedFloat32Array()
	comp.resize(3)
	for i in 3:
		var n = _as_number(a[i])
		if n == null or not is_finite(float(n)):
			return null
		comp[i] = float(n)
	return Vector3(comp[0], comp[1], comp[2])


static func _err(msg: String) -> Dictionary:
	push_error("[carpet] %s" % msg)
	return {"ok": false, "error": msg, "nodes": [], "ordered_resources": [], "node_variant": []}


# ─── resync_materials (M4 task 4 — 4a-e) ───────────────────────────────────────────
# Incremental material re-bind for an EDITED carpet. Walks `carpet_parent`'s children
# in TREE order, collects the first-seen unique GaussianSplatNode resources (the SAME
# order the GDGS GaussianSceneRegistry builds its global si.y index in), and re-calls
# RelightPass.set_materials_multi with that ordered list. This is the cheap path that
# KILLS the per-stroke teardown hitch: most edits (add/remove an instance of an
# already-placed variant) leave the unique set + order unchanged, in which case this
# is a NO-OP (set_materials_multi is skipped, _material_version does not bump).
#
# Behaviour vs. the task spec (4a-e):
#   - add an instance of an ALREADY-PLACED variant → unique set unchanged → no
#     material work, just the caller's add_child + transform. Returns true.
#   - add a NEW variant → its resource appends at the END of the ordered list →
#     existing si.y don't shift → ONE set_materials_multi call. Returns true.
#   - erase the LAST instance of a variant → re-walk, drop it from the ordered
#     uniques, ONE set_materials_multi call (no node respawn). Returns true.
#   - erase ALL instances → ordered list empties → set_materials_multi([]) clears
#     the material buffer. Returns true.
#   - Full node teardown stays the caller's job for "Regenerate from scratch" — this
#     touches materials ONLY, never nodes.
#
# OWNERSHIP PRECONDITION (same as load_carpet): `carpet_parent` MUST own every
# registered GaussianSplatNode. A foreign splat node registered before this carpet
# prepends a unique-resource entry to the registry's first-seen order that this walk
# will miss → every si.y shifts → the scene mis-shades. D9 (mixed-scene material
# offsets) is explicitly OUT OF SCOPE here; this is single-carpet only.
#
# Returns false ONLY on a set_materials_multi rejection (a resource with bad
# attr/count); in that case RelightPass state is unchanged (fail-closed) and the
# caller's nodes are LEFT IN PLACE (this does not free them — full teardown is the
# "Regenerate" path).
static func resync_materials(carpet_parent: Node) -> bool:
	if carpet_parent == null:
		push_error("[carpet] resync_materials: parent is null")
		return false

	# Tree-order walk collecting first-seen unique resources. Mirrors load_carpet's
	# spawn-pass unique tracking (instance_id() == object identity) so the ordered
	# list lands in the SAME order the registry built si.y in.
	var ordered: Array = []
	var ordered_ids: Array = []
	var seen: Dictionary = {}
	for n in carpet_parent.get_children():
		if not (n is GaussianSplatNode):
			continue
		var g = (n as GaussianSplatNode).gaussian
		if g == null:
			continue
		var rid: int = g.get_instance_id()
		if seen.has(rid):
			continue
		seen[rid] = true
		ordered.append(g)
		ordered_ids.append(rid)

	# Skip if the unique set AND order is unchanged since the last resync for THIS
	# parent. This is the "no material work" path: add/remove an instance of an
	# already-placed variant → the unique set is identical → set_materials_multi is
	# NOT called → _material_version / _material_count are unchanged.
	var key: int = carpet_parent.get_instance_id()
	var prev_ids: Array = _resync_state.get(key, [])

	# An EMPTY carpet MUST clear the material buffer. The no-op short-circuit below is
	# only valid for a NON-empty unchanged set: load_carpet binds materials directly
	# WITHOUT priming _resync_state, so a parent whose nodes were all removed AFTER a
	# load (or right after forget_resync) has prev_ids == [] while materials are STILL
	# bound — the naive `[] == []` short-circuit would skip the clear and leave stale
	# materials referencing freed resources. Always clear on empty (set_materials_multi([])
	# is idempotent — re-calling an already-empty buffer just re-bumps the version).
	if ordered.is_empty():
		if not RelightPass.set_materials_multi(ordered):
			return false
		_resync_state[key] = ordered_ids
		return true

	# Non-empty no-op: the unique set AND order is unchanged since the last resync for
	# THIS parent → skip set_materials_multi entirely (add/remove an instance of an
	# already-placed variant). This is the "no material work" path.
	if _ids_equal(prev_ids, ordered_ids):
		return true

	# set_materials_multi is fail-closed: returns false + mutates nothing if any
	# resource has a bad attr/count. On success, persist the new ordered IDs so the
	# next no-op resync skips (and so a foreign parent doesn't get this parent's
	# cached order). On REJECTION do NOT persist — a later no-op resync must not skip
	# a change that was never applied.
	if not RelightPass.set_materials_multi(ordered):
		return false
	_resync_state[key] = ordered_ids
	return true


# Drop the per-parent resync cache. Call after a FULL teardown (free the parent) so the
# static map doesn't keep stale keys. NB: NOT strictly harmless to skip — Godot recycles
# instance_ids, so if a freed parent's id is reused by a new parent whose ordered-resource
# set happens to match the stale entry, the no-op short-circuit would skip a needed rebind
# (theoretical — not reproduced in practice; requires the freed parent's RelightGaussianResource
# objects to stay alive AND the new parent to reference exactly them — but call this on
# teardown to close that window). Keyed by instance_id (NOT a weakref) for O(1) lookup.
static func forget_resync(carpet_parent: Node) -> void:
	if carpet_parent == null:
		return
	_resync_state.erase(carpet_parent.get_instance_id())


# Array-of-int identity compare (resource instance_ids). Returns true iff same length
# and same elements in the same order.
static func _ids_equal(a: Array, b: Array) -> bool:
	if a.size() != b.size():
		return false
	for i in a.size():
		if int(a[i]) != int(b[i]):
			return false
	return true
