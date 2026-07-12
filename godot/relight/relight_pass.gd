@tool
extends RefCounted
class_name RelightPass

# The ONE relight compute pass, inserted into the GDGS pipeline at a single point
# (gaussian_renderer.gd `_rasterize_state`, after projection / before sort).
#
# Owns its GPU objects lazily against the PUBLIC GDGS render state: it builds a
# shader / material buffer / descriptor set / pipeline on the state's
# GdgsRenderingDeviceContext, and REBUILDS them whenever GDGS swaps that context
# (its rebuild_gpu_state frees the old context, which frees everything we pushed
# onto its deletion queue). There is no rebuild hook, so run() polls context
# identity per RenderState (keyed by RenderState.get_instance_id()).
#
# run() early-returns when no materials are registered -> the cactus / standard
# GDGS path stays byte-identical.
#
# Light / mode / wrap / ambient arrive via set_light() (called each frame by the
# scene). Materials arrive via set_materials() (called on resource assign). Both
# are static so the single GDGS insertion point needs no new plumbing.

const RenderingDeviceContext := preload("res://addons/gdgs/runtime/render/gaussian_rendering_device_context.gd")
const SHADER_PATH := "res://relight/relight.glsl"
const LOCAL_SIZE := 256

enum { MODE_RAW = 0, MODE_RELIT = 1 }

# --- material state (set on resource assign) ---
static var _material_bytes := PackedByteArray()
static var _material_count := 0
static var _material_version := 0

# --- light / shading state (set each frame by the scene) ---
static var _light_dir := Vector3(0.0, -1.0, 0.0) # travel direction (world)
static var _light_color := Vector3(1.0, 1.0, 1.0)
static var _wrap_power := 2.0
static var _ambient := 0.2
static var _mode := MODE_RELIT
static var _trans_on := 0

# state.get_instance_id() -> per-state GPU bundle
static var _states := {}


class Bundle:
	extends RefCounted
	var context           # GdgsRenderingDeviceContext (identity == rebuild sentinel)
	var shader: RID
	var material_desc     # GdgsRenderingDeviceContext.Descriptor
	var descriptor_set: RID
	var pipeline: Callable
	var point_count := 0
	var material_size := 0
	var material_version := -1


static func set_materials(attr_data_byte: PackedByteArray, count: int) -> void:
	_material_bytes = attr_data_byte
	_material_count = count
	_material_version += 1


static func clear_materials() -> void:
	_material_bytes = PackedByteArray()
	_material_count = 0
	_material_version += 1


static func set_light(light_dir_ws: Vector3, light_color: Color, wrap_power: float,
		ambient: float, mode: int, trans_on: bool) -> void:
	_light_dir = light_dir_ws
	_light_color = Vector3(light_color.r, light_color.g, light_color.b)
	_wrap_power = wrap_power
	_ambient = ambient
	_mode = mode
	_trans_on = 1 if trans_on else 0


# Called from GDGS gaussian_renderer._rasterize_state (the single insertion point).
static func run(state, point_count: int) -> void:
	if _material_bytes.is_empty() or _material_count <= 0:
		return # no relight asset registered -> standard GDGS path untouched
	if state == null or point_count <= 0:
		return
	var ctx = state.context
	if ctx == null or not state.descriptors.has("culled_splats"):
		return

	var key = state.get_instance_id()
	var bundle = _states.get(key, null)
	# Rebuild if: first use, GDGS swapped the context, point budget changed, or the
	# material buffer was resized. (A context swap already freed our old RIDs.)
	if bundle == null or bundle.context != ctx \
			or bundle.point_count != point_count \
			or bundle.material_size != _material_bytes.size():
		bundle = _build(state, point_count)
		if bundle == null:
			return
		_states[key] = bundle

	# Refresh material contents if they changed under a still-valid context.
	if bundle.material_version != _material_version:
		ctx.device.buffer_update(bundle.material_desc.rid, 0, _material_bytes.size(), _material_bytes)
		bundle.material_version = _material_version

	var push := _push_constant(point_count)
	var compute_list: int = ctx.compute_list_begin()
	bundle.pipeline.call(ctx, compute_list, push)
	ctx.compute_list_end()


static func _build(state, point_count: int) -> Bundle:
	var ctx = state.context
	var b := Bundle.new()
	b.context = ctx
	b.point_count = point_count
	b.material_size = _material_bytes.size()
	b.shader = ctx.load_shader(SHADER_PATH)
	if not b.shader.is_valid():
		push_error("[relight] failed to load compute shader %s" % SHADER_PATH)
		return null
	b.material_desc = ctx.create_storage_buffer(_material_bytes.size(), _material_bytes)
	b.material_version = _material_version
	b.descriptor_set = ctx.create_descriptor_set([
		state.descriptors["culled_splats"],
		state.descriptors["splat_instance_ids"],
		state.descriptors["instance_transforms"],
		b.material_desc,
	], b.shader, 0)
	b.pipeline = ctx.create_pipeline([ceili(point_count / float(LOCAL_SIZE)), 1, 1], [b.descriptor_set], b.shader)
	return b


static func _push_constant(point_count: int) -> PackedByteArray:
	# Exactly 12 x 4 bytes = 48 bytes = 3 vec4 (Godot 4.7 requires an exact match).
	return RenderingDeviceContext.create_push_constant([
		_light_dir.x, _light_dir.y, _light_dir.z, _wrap_power,
		_light_color.x, _light_color.y, _light_color.z, _ambient,
		_mode, point_count, _trans_on, 0,
	])
