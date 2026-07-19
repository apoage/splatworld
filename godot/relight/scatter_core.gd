@tool
extends RefCounted
class_name ScatterCore

# M4 task 4 — Splat Studio placement CORE + op model (4a). UI-free, headless-
# instantiable; the deterministic expander the loader consumes and the studio panel
# edits. Determinism contract: ALL randomness goes through make_rng(seed); replaying
# an op list reproduces instances[] byte-identically. No globals, no Time-based seeds,
# no unordered iteration in any output-affecting path.
#
# OPS / STROKES (the editable source of truth). A layout = an ORDERED list of ops; the
# flat instances[] the loader consumes is the deterministic EXPANSION of that list via
# apply_ops. Each generative stroke's seed = hash(master_seed, stroke_index) so Reseed
# re-rolls the whole layout deterministically. Each expanded instance carries:
#   id  : stable int (hash of stroke_seed + per-stroke index) — survives deletes,
#         so a saved nudge/delete op targeting id=K resolves identically on replay.
#   op  : source op index (a picked instance maps straight back to its stroke).
#   variant / pos(Vector3) / yaw / scale : the TRS the loader consumes.
# TRS-only: pos + single Y-yaw + SCALAR uniform scale (relight.glsl:187-191 transforms
# the normal with rotation-only mat3(model); shear / non-uniform scale / per-instance
# tilt are structurally forbidden). ground_y is a scatter convention for fill/paint;
# stamp/nudge may set any finite pos.y (the loader only validates finite pos + scale>0).
#
# HOSTILE-INPUT DISCIPLINE: every field read from a saved op/cfg goes through the _num /
# _int / _vec3 / _range2 extractors so a hand-edited or partially-corrupt save degrades
# to a skipped op / {ok:false} instead of a GDScript SCRIPT ERROR. Well-formed callers
# (the studio, the smoke gate) are unaffected. save_doc refuses protected SOURCE roots.

const SCHEMA := "splat_carpet 1"
const FRAME := "godot"

# A config over this many points is FLAGGED (not silently OK). Matches the CLAUDE.md
# perf target (≤1.5M visible splats @ 1080p); task 3b measured 277 fps at 1.45M.
const BUDGET_GREEN := 1500000

# Saturation cap (Poisson dart-throw attempts). ~30× the requested count is the
# standard relaxed-Poisson ceiling; on exhaustion we return what we have, never loop.
const POISSON_ATTEMPTS_MULT := 30

# Path components that mark a read-only SOURCE root (invariant #4: datasets/,
# assets/raw/, /media/lukas/gg/photoscan are never writable). save_doc refuses these.
const PROTECTED_WRITE_SUBSTRS := ["datasets", "assets/raw", "photoscan"]


# ─── RNG ──────────────────────────────────────────────────────────────────────────

# The ONLY randomness source in the placement pipeline. Seed is set verbatim (Godot's
# RNG is deterministic given a fixed seed); callers MUST NOT touch its seed after.
static func make_rng(seed: int) -> RandomNumberGenerator:
	var rng := RandomNumberGenerator.new()
	rng.seed = seed
	return rng


# Deterministic per-stroke seed. hash() on a fixed-shape Array is stable across runs
# (Godot's variant hash is content-addressed), so the same (master, idx) ALWAYS yields
# the same stroke seed and the layout is replayable.
static func stroke_seed(master_seed: int, stroke_index: int) -> int:
	return hash([master_seed, stroke_index])


# Picks a variant id from a weighted list. `variants` = [{id:String, weight:float}, ...]
# with weight>0; draws in list order from `rng` so the pick is reproducible. Returns ""
# on a degenerate list (empty / all-zero weights) — caller validates.
static func pick_variant(variants: Array, rng: RandomNumberGenerator) -> String:
	if variants.is_empty():
		return ""
	var total := 0.0
	for v in variants:
		if not (v is Dictionary):
			continue # hostile variants[] entry (a non-object) -> skip, no SCRIPT ERROR
		var w: float = _weight(v)
		if w > 0.0:
			total += w
	if total <= 0.0:
		return ""
	var r := rng.randf() * total
	var acc := 0.0
	for v in variants:
		if not (v is Dictionary):
			continue
		var w: float = _weight(v)
		if w <= 0.0:
			continue
		acc += w
		if r <= acc:
			return String(v.get("id", ""))
	# Float round-off fallback: return the last positive-weight id.
	for i in range(variants.size() - 1, -1, -1):
		if not (variants[i] is Dictionary):
			continue
		if _weight(variants[i]) > 0.0:
			return String(variants[i].get("id", ""))
	return ""


# Variant weight via the _num guard: absent -> 1.0 (unweighted); present-but-non-finite
# / non-numeric (null/string/array) -> 0.0 (excluded). Untyped arg + Dictionary guard so a
# hostile non-object variants[] entry can't reach v.get() (which would SCRIPT-ERROR); the
# caller (pick_variant) guards too, this is belt-and-suspenders.
static func _weight(v) -> float:
	if not (v is Dictionary):
		return 0.0
	var n = _num(v.get("weight", 1.0))
	return float(n) if n != null else 0.0


# ─── defensive extractors (hostile-doc guards) ────────────────────────────────────
# finite float iff v is a JSON number (int/float) AND finite; else null. NaN/Inf reject
# (int(NaN)==INT_MIN would otherwise underflow budget; float(null) would crash).
static func _num(v) -> Variant:
	if typeof(v) != TYPE_FLOAT and typeof(v) != TYPE_INT:
		return null
	var f := float(v)
	if not is_finite(f):
		return null
	return f


# int iff v is a JSON number and finite; else `dflt`.
static func _int(v, dflt: int) -> int:
	var n = _num(v)
	if n == null:
		return dflt
	return int(float(n))


# Vector3 iff v is a 3-element Array of finite numbers; else null.
static func _vec3(v) -> Variant:
	if not (v is Array) or (v as Array).size() != 3:
		return null
	var a: Array = v
	var out := Vector3()
	for i in 3:
		var n = _num(a[i])
		if n == null:
			return null
		out[i] = float(n)
	return out


# Vector2 from a cfg 2-element sub-array (min/max/yaw/scale); null if malformed. `dflt`
# is returned verbatim if the key is absent (well-formed callers omitting the key).
static func _range2(cfg: Dictionary, key: String, dflt: Array) -> Variant:
	if not cfg.has(key):
		return Vector2(float(dflt[0]), float(dflt[1]))
	var v = cfg[key]
	if not (v is Array) or (v as Array).size() < 2:
		return null
	var a: Array = v
	var x = _num(a[0])
	var y = _num(a[1])
	if x == null or y == null:
		return null
	return Vector2(float(x), float(y))


# ─── SpatialHash (Poisson neighbour grid; reused by fill + paint) ─────────────────

class SpatialHash:
	extends RefCounted
	var _cell: float
	var _cells: Dictionary = {}              # (ix, iz) -> Array[Vector2]

	func _init(cell_size: float) -> void:
		# Cell size == min_dist so any too-close neighbour is in the 3x3 around the cell.
		_cell = maxf(cell_size, 1e-6)

	func _key(p: Vector2) -> Vector2i:
		return Vector2i(int(floor(p.x / _cell)), int(floor(p.y / _cell)))

	# True iff `p` has an existing neighbour within min_dist (checked over the 3x3 'hood).
	func too_close(p: Vector2, min_dist: float) -> bool:
		var k := _key(p)
		var md2 := min_dist * min_dist
		for dy in range(-1, 2):
			for dx in range(-1, 2):
				var bucket: Array = _cells.get(Vector2i(k.x + dx, k.y + dy), [])
				for q in bucket:
					if (q - p).length_squared() <= md2:
						return true
		return false

	func add(p: Vector2) -> void:
		var key := _key(p)
		if not _cells.has(key):
			_cells[key] = []
		(_cells[key] as Array).append(p)


# ─── fill_region: Poisson-disk rect fill ──────────────────────────────────────────
# cfg = {
#   "min":[x,z], "max":[x,z], "ground_y":float,
#   "count":int,            # target count
#   "min_dist":float,       # Poisson min spacing (>0 enables rejection)
#   "variants":[{"id","weight"}, ...],
#   "yaw":[mn,mx], "scale":[mn,mx]
# }
# Returns an Array of instance Dicts (id/op/variant/pos/yaw/scale). A malformed cfg
# returns [] (never a SCRIPT ERROR); on saturation the array is SHORTER than count
# (attempts exhausted); the caller reads n_placed = result.size(), n_requested = count.
static func fill_region(cfg: Dictionary, stroke_seed_value: int, op_index: int) -> Array:
	var mn_v = _range2(cfg, "min", [-1.0, -1.0])
	var mx_v = _range2(cfg, "max", [1.0, 1.0])
	if mn_v == null or mx_v == null:
		return []
	var mn: Vector2 = mn_v
	var mx: Vector2 = mx_v
	var gy = _num(cfg.get("ground_y", 0.0))
	if gy == null:
		return []
	var ground_y: float = float(gy)
	var count: int = maxi(_int(cfg.get("count", 0), 0), 0)
	var min_dist: float = 0.0
	var md_n = _num(cfg.get("min_dist", 0.0))
	if md_n != null:
		min_dist = float(md_n)
	var variants_v = cfg.get("variants", [])
	var variants: Array = variants_v if (variants_v is Array) else []
	var yaw_v = _range2(cfg, "yaw", [0.0, 0.0])
	var sc_v = _range2(cfg, "scale", [1.0, 1.0])
	if yaw_v == null or sc_v == null or count <= 0:
		return []
	var yaw_mn: float = float(yaw_v.x)
	var yaw_mx: float = float(yaw_v.y)
	var sc_mn: float = float(sc_v.x)
	var sc_mx: float = float(sc_v.y)

	var rng := make_rng(stroke_seed_value)
	var hash_grid: SpatialHash = null
	if min_dist > 0.0:
		hash_grid = SpatialHash.new(min_dist)

	var attempts_cap: int = maxi(POISSON_ATTEMPTS_MULT * count, 1)
	var placed: Array = []
	var attempts := 0
	while placed.size() < count and attempts < attempts_cap:
		attempts += 1
		var px := rng.randf() * (mx.x - mn.x) + mn.x
		var pz := rng.randf() * (mx.y - mn.y) + mn.y
		var p := Vector2(px, pz)
		if hash_grid != null and hash_grid.too_close(p, min_dist):
			continue
		if hash_grid != null:
			hash_grid.add(p)
		var vid := pick_variant(variants, rng)
		if vid.is_empty():
			continue # degenerate variant list -> nothing to place
		var yaw := rng.randf() * (yaw_mx - yaw_mn) + yaw_mn
		var sc := rng.randf() * (sc_mx - sc_mn) + sc_mn
		placed.append(_make_instance(vid, Vector3(p.x, ground_y, p.y), yaw, sc,
				_make_id(stroke_seed_value, placed.size()), op_index))
	return placed


# ─── sample_disc: one brush stamp (Poisson inside a circle) ───────────────────────
# Same primitives as fill_region. `cfg` carries variants / yaw / scale / ground_y /
# min_dist / count (max stamps for this single disc). `rng` is the stroke's rng so a
# paint path is one continuous stream of draws (centers along the path advance the rng
# in path order => fully reproducible). Malformed cfg -> [].
static func sample_disc(center_xz: Vector2, radius: float, cfg: Dictionary,
		rng: RandomNumberGenerator, stroke_seed_value: int, op_index: int,
		id_offset: int) -> Array:
	var gy = _num(cfg.get("ground_y", 0.0))
	if gy == null:
		return []
	var ground_y: float = float(gy)
	var min_dist: float = 0.0
	var md_n = _num(cfg.get("min_dist", 0.0))
	if md_n != null:
		min_dist = float(md_n)
	var count: int = maxi(_int(cfg.get("count", 1), 1), 0)
	var variants_v = cfg.get("variants", [])
	var variants: Array = variants_v if (variants_v is Array) else []
	var yaw_v = _range2(cfg, "yaw", [0.0, 0.0])
	var sc_v = _range2(cfg, "scale", [1.0, 1.0])
	if yaw_v == null or sc_v == null or count <= 0:
		return []
	var yaw_mn: float = float(yaw_v.x)
	var yaw_mx: float = float(yaw_v.y)
	var sc_mn: float = float(sc_v.x)
	var sc_mx: float = float(sc_v.y)
	var rad := maxf(radius, 0.0)

	var hash_grid: SpatialHash = null
	if min_dist > 0.0:
		hash_grid = SpatialHash.new(min_dist)

	var attempts_cap: int = maxi(POISSON_ATTEMPTS_MULT * count, 1)
	var placed: Array = []
	var attempts := 0
	while placed.size() < count and attempts < attempts_cap:
		attempts += 1
		# Uniform point in disc: pick uniform angle + sqrt(radius) for uniform area.
		var a := rng.randf() * TAU
		var rr := sqrt(rng.randf()) * rad
		var p := center_xz + Vector2(cos(a), sin(a)) * rr
		if hash_grid != null and hash_grid.too_close(p, min_dist):
			continue
		if hash_grid != null:
			hash_grid.add(p)
		var vid := pick_variant(variants, rng)
		if vid.is_empty():
			continue
		var yaw := rng.randf() * (yaw_mx - yaw_mn) + yaw_mn
		var sc := rng.randf() * (sc_mx - sc_mn) + sc_mn
		placed.append(_make_instance(vid, Vector3(p.x, ground_y, p.y), yaw, sc,
				_make_id(stroke_seed_value, id_offset + placed.size()), op_index))
	return placed


# ─── pick: nearest instance to a mouse ray (for nudge/delete) ─────────────────────
# Returns the index into `positions` of the nearest instance whose perpendicular
# distance to the ray is <= tol AND ahead of the origin (t>0). -1 if none qualifies.
static func pick(positions: PackedVector3Array, ray_origin: Vector3,
		ray_dir: Vector3, tol: float) -> int:
	if positions.is_empty():
		return -1
	var d := ray_dir.normalized()
	var best_i := -1
	var best_perp := tol
	var best_t := INF
	for i in positions.size():
		var rel := positions[i] - ray_origin
		var t := rel.dot(d)
		if t < 0.0:
			continue
		var perp_v := rel - d * t
		var perp := perp_v.length()
		if perp > best_perp:
			continue
		# Closer-to-camera wins on ties of perp distance (feels right for occlusion).
		if perp < best_perp - 1e-9 or t < best_t - 1e-9:
			best_perp = perp
			best_t = t
			best_i = i
	return best_i


# ─── apply_ops: the deterministic expander (the DoD entry point) ──────────────────
# Walks `ops` in order. Generative ops (fill/paint/stamp) append instances; edit ops
# (nudge/delete) mutate the in-progress list. Replaying the same op list + master seed
# reproduces instances[] byte-identically (the smoke gate's integrity check). A
# malformed op (non-object, bad cfg, non-finite fields) is SKIPPED with a push_warning
# rather than crashing — so a hand-edited save degrades to a shorter replay (which
# open_doc's integrity check then flags) instead of a SCRIPT ERROR. Unknown tool values
# are silently skipped (forward-compat: a newer save's unknown tool must not throw).
static func apply_ops(ops: Array, master_seed: int) -> Array:
	var instances: Array = []
	if not (ops is Array):
		return []
	for i in ops.size():
		var op_v = ops[i]
		if not (op_v is Dictionary):
			push_warning("[scatter] skipping non-object op at index %d" % i)
			continue
		var op: Dictionary = op_v
		var tool := String(op.get("tool", ""))
		match tool:
			"fill":
				var cfg_v = op.get("cfg", null)
				if not (cfg_v is Dictionary):
					push_warning("[scatter] skipping fill op %d: cfg not an object" % i)
					continue
				var ss := stroke_seed(master_seed, i)
				instances.append_array(fill_region(cfg_v, ss, i))
			"paint":
				var cfg_v = op.get("cfg", null)
				if not (cfg_v is Dictionary):
					push_warning("[scatter] skipping paint op %d: cfg not an object" % i)
					continue
				var path_v = op.get("path", [])
				if not (path_v is Array):
					push_warning("[scatter] skipping paint op %d: path not an array" % i)
					continue
				var rad = _num(op.get("radius", 1.0))
				var radius: float = float(rad) if rad != null else 1.0
				var ss := stroke_seed(master_seed, i)
				var rng := make_rng(ss)
				var id_off := 0
				for c in path_v:
					if not (c is Array) or (c as Array).size() < 2:
						continue
					var cx = _num((c as Array)[0])
					var cz = _num((c as Array)[1])
					if cx == null or cz == null:
						continue
					var center := Vector2(float(cx), float(cz))
					var stamped := sample_disc(center, radius, cfg_v, rng, ss, i, id_off)
					instances.append_array(stamped)
					id_off += stamped.size()
			"stamp":
				var pos = _vec3(op.get("pos", null))
				var yaw = _num(op.get("yaw", 0.0))
				var sc = _num(op.get("scale", 1.0))
				var vid := String(op.get("variant", ""))
				if pos == null or yaw == null or sc == null or vid.is_empty():
					push_warning("[scatter] skipping malformed stamp op %d" % i)
					continue
				var ss := stroke_seed(master_seed, i)
				instances.append(_make_instance(vid, pos, yaw, sc, _make_id(ss, 0), i))
			"nudge":
				_apply_nudge(instances, op)
			"delete":
				_apply_delete(instances, op)
			_:
				pass # unknown tool skipped (forward-compat; never throw / warn)
	return instances


# Edit op: nudge by stable id (op["id"]) to op["pos"]. Malformed -> no-op.
static func _apply_nudge(instances: Array, op: Dictionary) -> void:
	var id_v = _num(op.get("id", -1.0))
	var pos = _vec3(op.get("pos", null))
	if id_v == null or pos == null:
		return
	var target: int = int(float(id_v))
	for inst in instances:
		if int(inst.get("id", -1)) == target:
			inst["pos"] = pos
			return


# Edit op: delete by op["id"] OR by op["center"]+[x,z]+op["radius"] (drops every id
# inside that disc). Single-pass filter; ids of survivors are UNCHANGED (stable across
# deletes — that's why id is a hash, not a list index). Malformed -> no-op.
static func _apply_delete(instances: Array, op: Dictionary) -> void:
	if op.has("id"):
		var id_v = _num(op.get("id", -1.0))
		if id_v == null:
			return
		var target: int = int(float(id_v))
		var i := 0
		while i < instances.size():
			if int(instances[i].get("id", -1)) == target:
				instances.remove_at(i)
				continue
			i += 1
		return
	if op.has("center") and op.has("radius"):
		var c = op.get("center", null)
		var rad = _num(op.get("radius", 0.0))
		if not (c is Array) or (c as Array).size() < 2 or rad == null:
			return
		var cx = _num((c as Array)[0])
		var cz = _num((c as Array)[1])
		if cx == null or cz == null:
			return
		var cxz := Vector2(float(cx), float(cz))
		var r2: float = float(rad) * float(rad)
		var i := 0
		while i < instances.size():
			var p: Vector3 = instances[i].get("pos", Vector3.ZERO)
			var dxz := Vector2(p.x, p.z) - cxz
			if dxz.length_squared() <= r2:
				instances.remove_at(i)
				continue
			i += 1


# ─── budget ───────────────────────────────────────────────────────────────────────
# Σ point_count over instances (NOT over unique variants — task spec: budget the
# RENDERED splat cost, which scales with total instances, not unique uploads).
# `point_counts` maps variant_id -> point_count (cached on first load by the studio).
# _int rejects NaN/non-numeric so a NaN'd cache entry can't underflow to INT_MIN and
# silently disable the over-budget flag.
static func budget(instances: Array, point_counts: Dictionary) -> int:
	var total := 0
	for inst in instances:
		var vid := String(inst.get("variant", ""))
		# _int rejects NaN/non-numeric (-> 0); maxi(..., 0) rejects negatives so a hostile
		# negative point_count can't silently bypass the over-budget flag (a negative total
		# is never > BUDGET_GREEN).
		total += maxi(_int(point_counts.get(vid, 0), 0), 0)
	return total


# ─── doc round-trip ───────────────────────────────────────────────────────────────
# build_doc() expands `ops` via apply_ops and returns a doc the loader accepts:
#   {"schema":"splat_carpet 1","frame":"godot","variants":[...],
#    "instances":[{variant,pos:[x,y,z],yaw,scale}, ...],
#    "studio":{"master_seed":..,"strokes":[...]}}
# `variants` = [{id,path}] (palette metadata; the loader resolves each instance's
# variant id to its path here). `region` optional. The loader ignores unknown keys, so
# the `studio` block rides along with no schema bump (D-INSTANCES-CONTRACT unchanged).
# Warns (does not fail) on duplicate variant ids — the loader resolves them
# last-write-wins, which would silently mis-bind materials.
static func build_doc(variants: Array, ops: Array, master_seed: int,
		region: Dictionary = {}) -> Dictionary:
	var seen_ids: Dictionary = {}
	for v in variants:
		if not (v is Dictionary):
			continue
		var vid := String(v.get("id", ""))
		if vid.is_empty():
			continue
		if seen_ids.has(vid):
			push_warning("[scatter] duplicate variant id '%s' (loader resolves last-write-wins)" % vid)
		else:
			seen_ids[vid] = true
	var instances := apply_ops(ops, master_seed)
	var flat: Array = []
	for inst in instances:
		flat.append(_instance_to_loader_dict(inst))
	var doc := {
		"schema": SCHEMA,
		"frame": FRAME,
		"variants": variants,
		"instances": flat,
		"studio": {
			"master_seed": master_seed,
			"strokes": ops,
		},
	}
	if not region.is_empty():
		doc["region"] = region
	return doc


# Writes a doc as JSON. Refuses any path inside a read-only SOURCE root (invariant #4)
# so the studio can NEVER clobber datasets/ / assets/raw/ / /media/lukas/gg/photoscan.
# Returns true on success, false (push_error) on a protected path or unwritable target.
static func save_doc(doc: Dictionary, path: String) -> bool:
	if _is_protected_write(path):
		push_error("[scatter] refusing to write read-only SOURCE path: %s" % path)
		return false
	var text := JSON.stringify(doc, "  ")
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f == null:
		push_error("[scatter] cannot open %s for write" % path)
		return false
	f.store_string(text)
	f.close()
	return true


# Reads a saved doc and INTEGRITY-CHECKS it: replays studio.strokes via apply_ops and
# confirms the replayed instances byte-match the saved flat instances[] (catches a
# hand-edited doc where strokes and instances drifted out of sync). Returns:
#   {"ok":bool, "error":String, "doc":Dictionary, "replayed":Array, "integrity":bool}
# Malformed JSON / non-object / malformed studio structure -> {ok:false, error:...}
# (never a SCRIPT ERROR). A doc with NO studio block (a hand-authored instances.json)
# is trivially integral (replayed == []). A doc whose studio.strokes replay disagrees
# with the saved instances[] -> {ok:true, integrity:false}.
static func open_doc(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {"ok": false, "error": "cannot open %s" % path, "doc": {}, "replayed": [], "integrity": false}
	var text := f.get_as_text()
	f.close()
	var parsed = JSON.parse_string(text)
	if parsed == null or not (parsed is Dictionary):
		return {"ok": false, "error": "%s: not a JSON object" % path, "doc": {}, "replayed": [], "integrity": false}
	var doc: Dictionary = parsed
	var studio_v = doc.get("studio", null)
	if studio_v == null:
		return {"ok": true, "error": "", "doc": doc, "replayed": [], "integrity": true}
	if not (studio_v is Dictionary):
		return {"ok": false, "error": "%s: 'studio' is not an object" % path, "doc": {}, "replayed": [], "integrity": false}
	var studio: Dictionary = studio_v
	var ops_v = studio.get("strokes", null)
	if ops_v == null:
		return {"ok": true, "error": "", "doc": doc, "replayed": [], "integrity": true}
	if not (ops_v is Array):
		return {"ok": false, "error": "%s: studio.strokes is not an array" % path, "doc": {}, "replayed": [], "integrity": false}
	var ops: Array = ops_v
	var master_seed: int = _int(studio.get("master_seed", 0), 0)
	var replayed := apply_ops(ops, master_seed)
	var integrity := _instances_match(replayed, doc.get("instances", []))
	return {"ok": true, "error": "", "doc": doc, "replayed": replayed, "integrity": integrity}


# Byte-identical comparison of two instance lists (replayed vs saved flat). Compares
# the loader-relevant fields (variant/id/pos/yaw/scale) with float tolerance. The saved
# side is treated as hostile: a non-Array `saved_flat` (hostile top-level `instances`)
# or a non-object entry / non-numeric field -> mismatch (never a SCRIPT ERROR).
static func _instances_match(replayed: Array, saved_flat) -> bool:
	if not (saved_flat is Array):
		return false
	if replayed.size() != saved_flat.size():
		return false
	for i in replayed.size():
		var a: Dictionary = replayed[i]
		var b_v = saved_flat[i]
		if not (b_v is Dictionary):
			return false
		var b: Dictionary = b_v
		if String(a.get("variant", "")) != String(b.get("variant", "")):
			return false
		var bid = _num(b.get("id", -1))
		if bid == null or int(a.get("id", -1)) != int(float(bid)):
			return false
		var pa: Vector3 = a["pos"]
		var pb = _vec3(b.get("pos", null))
		if pb == null or (pa - pb).length_squared() > 1e-9:
			return false
		var ayaw = _num(a.get("yaw", 0.0))
		var byaw = _num(b.get("yaw", 0.0))
		if byaw == null or absf(float(ayaw) - float(byaw)) > 1e-9:
			return false
		var asc = _num(a.get("scale", 1.0))
		var bsc = _num(b.get("scale", 1.0))
		if bsc == null or absf(float(asc) - float(bsc)) > 1e-9:
			return false
	return true


# True iff `path` is inside a read-only SOURCE root (invariant #4). Matches a path
# SEGMENT (slash + case-normalized) so it holds regardless of where the Godot project dir
# sits AND regardless of CWD: catches "/<sub>/" (absolute / res:// / ..-traversal), a
# suffix "/<sub>", a leading "<sub>/" (bare-relative like "datasets/x.json"), or exactly
# "<sub>". Segment matching avoids false positives on "my_datasets" / "datasets_backup".
static func _is_protected_write(path: String) -> bool:
	var p := path.replace("\\", "/").to_lower()
	for sub in PROTECTED_WRITE_SUBSTRS:
		var s := String(sub)
		if p.find("/" + s + "/") >= 0 or p.ends_with("/" + s) or p.begins_with(s + "/") or p == s:
			return true
	return false


# ─── instance factories + serializers ─────────────────────────────────────────────

# Internal instance dict. id is a stable hash (stroke_seed, per-stroke index); op is
# the source op index so a picked instance maps straight back to its stroke.
static func _make_instance(vid: String, pos: Vector3, yaw: float, scale: float,
		id: int, op: int) -> Dictionary:
	return {
		"id": id,
		"op": op,
		"variant": vid,
		"pos": pos,
		"yaw": yaw,
		"scale": scale,
	}


# Per-stroke instance id = hash of (stroke_seed, per-stroke index). Stable across
# deletes (NOT a list index), so a saved nudge/delete op resolves identically on replay.
static func _make_id(stroke_seed_value: int, per_stroke_index: int) -> int:
	return hash([stroke_seed_value, per_stroke_index])


# Internal instance (Vector3 pos) -> loader dict (pos as [x,y,z] array). Keeps `id`
# (the loader tolerates the unknown key; open_doc's integrity replay compares it) and
# drops `op` (internal bookkeeping the loader never reads).
static func _instance_to_loader_dict(inst: Dictionary) -> Dictionary:
	var p: Vector3 = inst["pos"]
	return {
		"variant": inst["variant"],
		"pos": [p.x, p.y, p.z],
		"yaw": inst["yaw"],
		"scale": inst["scale"],
		"id": inst["id"],
	}
