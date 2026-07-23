@tool
extends Node
class_name SplatStudio

# M4 task 4 — Splat Studio interactive tool belt (4b). Owns the op-model editing
# session on top of ScatterCore (4a) and rebuilds the carpet via CarpetLoader +
# resync_materials when an op commits. Self-contained: builds its own CanvasLayer +
# panel in _ready() so it instantiates headless cleanly without forcing a viewer
# edit. The factory gate is "constructs headless" (check 11) + Fill/Stamp wired;
# Paint-drag and Nudge mouse ergonomics are a clean follow-up slice (functional
# via commit_* methods, but no interactive drag loop in this build).
#
# Lifecycle: caller parents this Node into a scene that has a viewport, then calls
# set_carpet_parent() with the Node3D that owns the spawned GaussianSplatNodes,
# set_variants() with the palette, and the commit_* methods to author strokes.
# save_to()/load_from() round-trip the doc (with the embedded `studio` block).

const ScatterCore = preload("res://relight/scatter_core.gd")
const CarpetLoader = preload("res://relight/carpet_loader.gd")
const RelightPlyLoader = preload("res://relight/relight_ply_loader.gd")

const TOOLS := ["fill", "stamp", "paint", "nudge", "delete"]

# Studio session state (the editable source of truth).
var _master_seed: int = 7
var _ops: Array = []                       # ordered op list (the strokes)
var _variants: Array = []                  # palette: [{id, path, point_count, weight}]
var _region: Dictionary = {}               # optional region metadata
var _ground_y: float = 0.0
var _doc_path: String = ""
var _carpet_parent: Node = null            # Node3D that owns the GaussianSplatNodes

# Tool state.
var _active_tool: String = "fill"

# UI refs (built lazily in _ready; safe no-op if there's no viewport).
var _panel_root: Control
var _ui: Dictionary = {}


func _ready() -> void:
	_build_panel()


func _exit_tree() -> void:
	# Close the theoretical CarpetLoader._resync_state instance_id-reuse window on
	# teardown: free this studio's cache entry so a recycled id can't cache-hit a stale
	# ordered-resource order. (The window is latent — _rebuild already forget_resyncs on
	# every commit — but this makes a studio queue_free() self-cleaning too.)
	if _carpet_parent != null:
		CarpetLoader.forget_resync(_carpet_parent)


# ─── session wiring ───────────────────────────────────────────────────────────────

# The Node3D that owns spawned GaussianSplatNodes. _rebuild frees + respawns its
# GaussianSplatNode children on each commit; non-splat children are left untouched.
func set_carpet_parent(p: Node) -> void:
	_carpet_parent = p


# `ground_y` is a fill/paint convention; stamp may set any finite pos.y.
func set_ground_y(y: float) -> void:
	_ground_y = y


func set_region(region: Dictionary) -> void:
	_region = region.duplicate(true)


# Palette: [{id, path, point_count?, weight?}]. point_count is loaded lazily if absent
# (cached so the budget meter doesn't reload multi-million-splat plys per tick); weight
# defaults to 1.0. Rejects duplicate ids (the loader resolves dup ids last-write-wins,
# silently mis-binding materials) and guards a missing `path` (used to raise on direct
# key access). See _normalize_variants for the @tool editor-load guard.
func set_variants(variants: Array) -> void:
	_variants = _normalize_variants(variants.duplicate(true))


# Normalize a variants[] list: drop non-objects, reject duplicate ids (loader resolves
# dup ids last-write-wins -> silent material mis-bind), guard a missing `path` (a direct
# v["path"] used to raise "Invalid access to key"), cache point_count, default weight.
# Under @tool / in the editor, do NOT parse multi-million-splat .vply on the editor
# thread (hangs the editor) — point_count stays 0 there, which is correct (no live carpet
# in the editor). Returns a fresh clean list (caller's array is not mutated in place).
func _normalize_variants(vs: Array) -> Array:
	var out: Array = []
	var seen: Dictionary = {}
	for v in vs:
		if not (v is Dictionary):
			continue
		var vid := String(v.get("id", ""))
		if not vid.is_empty() and seen.has(vid):
			push_error("[splat-studio] duplicate variant id '%s' ignored" % vid)
			continue
		if not vid.is_empty():
			seen[vid] = true
		var p := String(v.get("path", ""))
		if not v.has("point_count"):
			if not Engine.is_editor_hint() and not p.is_empty():
				var res = RelightPlyLoader.load(p)
				v["point_count"] = int(res.point_count) if res != null else 0
			else:
				v["point_count"] = 0
		v["weight"] = float(v.get("weight", 1.0))
		out.append(v)
	return out


func select_tool(name: String) -> void:
	if TOOLS.has(name):
		_active_tool = name


func reseed(new_seed: int) -> void:
	_master_seed = new_seed
	_rebuild()


# ─── op commits (the tool belt; each is one stroke on the undo stack) ─────────────

# Fill (drag-rect Poisson). `rect_min`/`rect_max` are XZ; `cfg` carries count,
# min_dist, variants+weights, yaw/scale ranges. ground_y is folded in here.
func commit_fill(rect_min: Vector2, rect_max: Vector2, cfg: Dictionary) -> void:
	if not (is_finite(rect_min.x) and is_finite(rect_min.y) \
			and is_finite(rect_max.x) and is_finite(rect_max.y)):
		push_error("[splat-studio] commit_fill rejected non-finite rect")
		return
	var c: Dictionary = cfg.duplicate(true)
	c["min"] = [rect_min.x, rect_min.y]
	c["max"] = [rect_max.x, rect_max.y]
	c["ground_y"] = _ground_y
	_ops.append({"tool": "fill", "cfg": c})
	_rebuild()


# Stamp (single click). `pos` is full 3D — caller decides y (ground_y snap is the
# UI layer's job, not the op's). variant_id defaults to the palette's first entry.
func commit_stamp(pos: Vector3, variant_id: String = "", yaw: float = 0.0,
		scale: float = 1.0) -> void:
	# Reject non-finite values at the entry point: JSON.stringify writes `null` for NaN
	# and `1e99999` for Inf, so a non-finite value would brick the saved doc on reload
	# (apply_ops' _num rejects them, but the WRITE must never produce them either).
	if not (is_finite(pos.x) and is_finite(pos.y) and is_finite(pos.z)) \
			or not is_finite(yaw) or not is_finite(scale):
		push_error("[splat-studio] commit_stamp rejected non-finite pos/yaw/scale")
		return
	var vid := variant_id
	if vid.is_empty() and not _variants.is_empty():
		vid = String(_variants[0].get("id", ""))
	_ops.append({
		"tool": "stamp",
		"pos": [pos.x, pos.y, pos.z],
		"yaw": yaw,
		"scale": scale,
		"variant": vid,
	})
	_rebuild()


# Paint (path of disc stamps). `path` is an Array of Vector2 XZ centers; the op
# expands to Poisson samples per center along the path (the interactive drag loop
# is the follow-up slice; this method is the headless-exercisable commit).
func commit_paint(path: Array, radius: float, cfg: Dictionary) -> void:
	for c2 in path:
		if not (c2 is Vector2) or not (is_finite((c2 as Vector2).x) and is_finite((c2 as Vector2).y)):
			push_error("[splat-studio] commit_paint rejected non-finite / non-Vector2 path point")
			return
	if not is_finite(radius):
		push_error("[splat-studio] commit_paint rejected non-finite radius")
		return
	var c: Dictionary = cfg.duplicate(true)
	c["ground_y"] = _ground_y
	var p2: Array = []
	for c2 in path:
		p2.append([float((c2 as Vector2).x), float((c2 as Vector2).y)])
	_ops.append({"tool": "paint", "radius": radius, "path": p2, "cfg": c})
	_rebuild()


# Nudge one instance (by stable id) to a new pos. Functional via op model; the
# interactive drag + mouse-pick is the follow-up slice.
func commit_nudge(target_id: int, new_pos: Vector3) -> void:
	if not (is_finite(new_pos.x) and is_finite(new_pos.y) and is_finite(new_pos.z)):
		push_error("[splat-studio] commit_nudge rejected non-finite pos")
		return
	_ops.append({"tool": "nudge", "id": target_id,
			"pos": [new_pos.x, new_pos.y, new_pos.z]})
	_rebuild()


# Delete by stable id.
func commit_delete(target_id: int) -> void:
	_ops.append({"tool": "delete", "id": target_id})
	_rebuild()


# Pop the last op (the head of the undo stack). The op model makes this trivial:
# the layout is the deterministic expansion of the op list, so dropping the last
# op and re-expanding restores the prior instances[] byte-identically.
func undo() -> void:
	if not _ops.is_empty():
		_ops.pop_back()
		_rebuild()


func clear_ops() -> void:
	_ops.clear()
	_rebuild()


func op_count() -> int:
	return _ops.size()


func instances() -> Array:
	return ScatterCore.apply_ops(_ops, _master_seed)


func point_counts() -> Dictionary:
	var pc: Dictionary = {}
	for v in _variants:
		pc[String(v.get("id", ""))] = int(v.get("point_count", 0))
	return pc


func total_points() -> int:
	return ScatterCore.budget(instances(), point_counts())


# ─── doc persistence ──────────────────────────────────────────────────────────────

func save_to(path: String) -> bool:
	var doc := ScatterCore.build_doc(_variants, _ops, _master_seed, _region)
	if not ScatterCore.save_doc(doc, path):
		return false
	_doc_path = path
	return true


func load_from(path: String) -> bool:
	var opened := ScatterCore.open_doc(path)
	if not bool(opened.get("ok", false)):
		return false
	var doc: Dictionary = opened["doc"]
	# Defensive top-level reads: a hostile/hand-edited doc may have any of these
	# present-but-wrong-typed, and Dictionary.get returns the STORED value (not the
	# default) when the key exists — coerce every one so a typed assign can't SCRIPT-ERROR.
	var studio_v = doc.get("studio", {})
	var studio: Dictionary = studio_v if (studio_v is Dictionary) else {}
	var strokes_v = studio.get("strokes", [])
	_ops = strokes_v if (strokes_v is Array) else []
	_master_seed = ScatterCore._int(studio.get("master_seed", _master_seed), _master_seed)
	# Palette is whatever the doc declares; re-cache point_counts (guarded: missing
	# path / dup id / @tool editor load — see _normalize_variants).
	var vs_v = doc.get("variants", [])
	var vs: Array = vs_v if (vs_v is Array) else []
	_variants = _normalize_variants(vs)
	var region_v = doc.get("region", {})
	_region = region_v if (region_v is Dictionary) else {}
	_doc_path = path
	return _rebuild()


# ─── carpet rebuild ───────────────────────────────────────────────────────────────

# Commit path: regenerate the carpet from the current op list. This is the
# "Regenerate from scratch" path (full teardown + reload) — correct + simple.
# The cheap interactive path (per-stroke incremental resync_materials without
# teardown) is what the spec reserves for in-progress paint previews; a committed
# op always round-trips through the loader so the spawned tree == the doc.
func _rebuild() -> bool:
	if _carpet_parent == null:
		return false
	for c in _carpet_parent.get_children():
		if c is GaussianSplatNode:
			_carpet_parent.remove_child(c)
			c.free()
	CarpetLoader.forget_resync(_carpet_parent)
	if _ops.is_empty() or _variants.is_empty():
		# Empty session: clear the material buffer via resync_materials on the live
		# parent. load_carpet is NOT involved, so NO file is written.
		CarpetLoader.resync_materials(_carpet_parent)
		_update_panel_info()
		return true
	var doc := ScatterCore.build_doc(_variants, _ops, _master_seed, _region)
	# ALWAYS round-trip the rebuilt doc through a SCRATCH autosave under user:// — NEVER
	# _doc_path. load_from() may have pointed _doc_path at a protected SOURCE file
	# (datasets/ / assets/raw/ / photoscan), and committing a stroke must not overwrite
	# it. (save_doc refuses protected roots regardless, as belt-and-suspenders.) The
	# user's chosen save location is written ONLY by the explicit save_to() call.
	var path := "user://splat_studio_autosave.json"
	if not ScatterCore.save_doc(doc, path):
		push_error("[splat-studio] could not save session doc to %s" % path)
		_update_panel_info()
		return false
	var result := CarpetLoader.load_carpet(path, _carpet_parent)
	if not bool(result.get("ok", false)):
		push_error("[splat-studio] load_carpet rejected the rebuilt doc: %s" % result.get("error", "?"))
		_update_panel_info()
		return false
	_update_panel_info()
	return true


# ─── panel (constructs headless; the ONLY UI assert in the DoD) ───────────────────

func _build_panel() -> void:
	var vp = get_viewport()
	if vp == null:
		return # pure-logic instantiation (e.g. a headless unit test) — no panel
	var layer := CanvasLayer.new()
	add_child(layer)
	_panel_root = PanelContainer.new()
	_panel_root.custom_minimum_size = Vector2(320.0, 0.0)
	layer.add_child(_panel_root)
	var box := VBoxContainer.new()
	_panel_root.add_child(box)
	var title := Label.new()
	title.text = "— Splat Studio —"
	box.add_child(title)
	_ui["tool"] = _add_option(box, "tool", TOOLS, 0, _on_tool_ui)
	_ui["seed"] = _add_spin(box, "master seed", 0, 1000000, 1, _master_seed, _on_seed_ui)
	_ui["info"] = Label.new()
	box.add_child(_ui["info"])
	_update_panel_info()


func _update_panel_info() -> void:
	if _ui.get("info", null) == null:
		return
	var n_inst := instances().size()
	var pts := total_points()
	var flag := " (OVER BUDGET)" if pts > ScatterCore.BUDGET_GREEN else ""
	(_ui["info"] as Label).text = "ops=%d  instances=%d  pts=%d%s" % [_ops.size(), n_inst, pts, flag]


func _on_tool_ui(i: int) -> void:
	_active_tool = TOOLS[i]


func _on_seed_ui(v: float) -> void:
	_master_seed = int(v)
	_rebuild()


func _add_option(parent: Node, text: String, items: Array, selected: int,
		cb: Callable) -> OptionButton:
	var row := HBoxContainer.new()
	var lbl := Label.new()
	lbl.text = text
	lbl.custom_minimum_size = Vector2(90.0, 0.0)
	row.add_child(lbl)
	var o := OptionButton.new()
	for it in items:
		o.add_item(str(it))
	o.selected = selected
	o.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	o.item_selected.connect(cb)
	row.add_child(o)
	parent.add_child(row)
	return o


func _add_spin(parent: Node, text: String, mn: float, mx: float, step: float,
		val: float, cb: Callable) -> SpinBox:
	var row := HBoxContainer.new()
	var lbl := Label.new()
	lbl.text = text
	lbl.custom_minimum_size = Vector2(90.0, 0.0)
	row.add_child(lbl)
	var s := SpinBox.new()
	s.min_value = mn
	s.max_value = mx
	s.step = step
	s.value = val
	s.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	s.value_changed.connect(cb)
	row.add_child(s)
	parent.add_child(row)
	return s
