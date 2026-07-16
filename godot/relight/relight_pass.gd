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

# Ambient env-SH buffer (binding 4): 9 coeffs x vec4 (xyz = c_lm RGB, w pad).
const ENV_SH_COEFFS := 9
const ENV_SH_BYTES := 144 # ENV_SH_COEFFS * 4 floats * 4 bytes

# Local point/spot light buffer (binding 5): a FIXED-SIZE array of light slots so the
# flashlight (N=1) extends to N=2..MAX_FLASH_LIGHTS Moon-Stone fireballs (M4/M5) WITHOUT
# another GPU buffer / shader contract change — only set_flashlight()'s caller grows.
# std430 layout, MUST match FlashBuffer in relight.glsl:
#   ivec4 meta                          (16 B)  x = active light count
#   FlashLight lights[MAX_FLASH_LIGHTS]         each 3 vec4 = 48 B:
#     pos_range  : xyz world pos, w = range (falloff cutoff distance)
#     dir_cone   : xyz spot axis (world, unit), w = cos(outer cone half-angle)
#     color_cone : rgb color*energy, w = cos(inner cone half-angle)
const MAX_FLASH_LIGHTS := 4
const FLASH_SLOT_BYTES := 48                       # 3 vec4
const FLASH_META_BYTES := 16                       # ivec4 header
const FLASH_BYTES := FLASH_META_BYTES + MAX_FLASH_LIGHTS * FLASH_SLOT_BYTES # 208

# DC-normalization (relit-energy): set_env_sh scales ALL 9 c_lm so the sphere-mean
# luma of ambient_sh(N) becomes 1.0. The sphere-mean of ambient_sh equals SH_C0*c00
# because every l>=1 SH band integrates to zero over the sphere, so dividing all
# coeffs by that mean's Rec.709 luma makes ambient_sh unit-mean while preserving the
# env's directional shape + RELATIVE tint. The shader then scales by the ambient
# slider (pc.light_color.w), so the recovered env drives ambient strength with the
# SAME energy budget as the flat fallback vec3(ambient). SH_C0 MUST equal the shader
# / relight_ply_loader constant; ENV_DC_EPS guards a ~0 (or negative) DC luma.
const SH_C0 := 0.28209479177387814
const ENV_DC_EPS := 1e-8

enum { MODE_RAW = 0, MODE_RELIT = 1 }

# --- material state (set on resource assign) ---
static var _material_bytes := PackedByteArray()
static var _material_count := 0
static var _material_version := 0

# --- ambient env-SH state (set on resource assign; empty => flat ambient fallback) ---
static var _env_bytes := PackedByteArray() # 144 B packed, or empty (=> flat fallback)
static var _env_active := 0                # push-constant misc.w: 1 => shade with env_sh
static var _env_version := 0

# --- local point/spot light state (set each frame by the scene; count 0 => no local light) ---
static var _flash_bytes := PackedByteArray() # FLASH_BYTES packed, or empty (=> off)
static var _flash_version := 0

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
	var env_desc          # GdgsRenderingDeviceContext.Descriptor (env-SH buffer, fixed 144 B)
	var flash_desc        # GdgsRenderingDeviceContext.Descriptor (local-light buffer, fixed 208 B)
	var descriptor_set: RID
	var pipeline: Callable
	var point_count := 0
	var material_size := 0
	var material_version := -1
	var env_version := -1
	var flash_version := -1


static func set_materials(attr_data_byte: PackedByteArray, count: int) -> void:
	_material_bytes = attr_data_byte
	_material_count = count
	_material_version += 1


static func clear_materials() -> void:
	_material_bytes = PackedByteArray()
	_material_count = 0
	_material_version += 1


# coeffs_rgb = 27 floats [c0.r,c0.g,c0.b, c1.r, ...] (9 coeffs x RGB), Godot-frame,
# A_l/pi already folded (see RelightEnvSH / core.sh_env). Empty / wrong length =>
# flat-ambient fallback. Packs to 9 x vec4 (w pad) for std430 binding 4.
#
# DC-normalization: the sidecar coeffs are the FULL recovered capture illumination;
# left raw they'd apply the env at weight ~1.0 (mean ambient luma ~0.8-0.9) IGNORING
# the ambient slider -> relit ~= unit sun + full capture light ~= double energy
# ("bloom with extra saturation", clipping). We scale ALL 9 coeffs by
# s = 1 / max(SH_C0 * luma(c00), eps) so the sphere-mean luma of ambient_sh(N) == 1.0
# (all l>=1 bands integrate to zero over the sphere, so the mean is exactly SH_C0*c00);
# the shader multiplies by the ambient slider, matching the flat fallback's energy
# budget while keeping the env's directional shape + relative tint. Normalization is
# runtime-side ONLY: the sidecar bytes / core.sh_env stay engine-agnostic ground truth.
static func set_env_sh(coeffs_rgb: PackedFloat32Array) -> void:
	if coeffs_rgb.size() != ENV_SH_COEFFS * 3:
		clear_env_sh()
		return
	var dc_luma := 0.2126 * coeffs_rgb[0] + 0.7152 * coeffs_rgb[1] + 0.0722 * coeffs_rgb[2]
	var s := 1.0 / maxf(SH_C0 * dc_luma, ENV_DC_EPS)
	var b := PackedByteArray()
	b.resize(ENV_SH_BYTES)
	for i in ENV_SH_COEFFS:
		var o := i * 16
		b.encode_float(o + 0, coeffs_rgb[i * 3 + 0] * s)
		b.encode_float(o + 4, coeffs_rgb[i * 3 + 1] * s)
		b.encode_float(o + 8, coeffs_rgb[i * 3 + 2] * s)
		b.encode_float(o + 12, 0.0)
	_env_bytes = b
	_env_active = 1
	_env_version += 1


static func clear_env_sh() -> void:
	_env_bytes = PackedByteArray()
	_env_active = 0
	_env_version += 1


# Always 144 bytes: real coeffs when active, else zeros (buffer stays bound so the
# descriptor set / pipeline need no rebuild when the env toggles).
static func _env_padded() -> PackedByteArray:
	if _env_bytes.size() == ENV_SH_BYTES:
		return _env_bytes
	var z := PackedByteArray()
	z.resize(ENV_SH_BYTES)
	return z


# Local point/spot light. `on` gates the whole term (off => meta.x = 0 => no cost
# beyond the count read). `pos`/`dir` are WORLD-space (the shader transforms each
# splat's object position to world itself). `energy` scales `color`. `range` is the
# falloff cutoff distance. `inner_deg`/`outer_deg` are the spot cone half-angles
# (full brightness inside inner, fades to 0 by outer). Equal (or inner>outer) angles
# collapse to a NEAR-HARD edge: cos_inner is nudged just above cos_outer so the
# shader's smoothstep(cos_outer, cos_inner, .) never gets edge0>=edge1 (undefined /
# NaN on many drivers). Fills slot 0 (N=1) — the buffer already carries
# MAX_FLASH_LIGHTS slots, so adding the Moon-Stone fireballs later is a
# set_flashlights([...]) that fills more slots, NOT a contract change. Mirrors
# set_light: static, called each frame by the scene.
static func set_flashlight(on: bool, pos: Vector3, dir: Vector3, color: Color,
		energy: float, range: float, inner_deg: float, outer_deg: float) -> void:
	if not on:
		clear_flashlight()
		return
	var d := dir.normalized()
	if d.length_squared() < 0.5:
		d = Vector3(0.0, 0.0, -1.0)
	# outer >= inner so cos_outer <= cos_inner. Guard the shader's smoothstep against a
	# degenerate cone (inner_deg >= outer_deg): force cos_inner strictly above cos_outer,
	# which renders as a near-hard edge instead of an undefined smoothstep(e, e, x).
	var outer := maxf(outer_deg, inner_deg)
	var cos_outer := cos(deg_to_rad(outer))
	var cos_inner: float = maxf(cos(deg_to_rad(inner_deg)), cos_outer + 1e-4)
	var b := PackedByteArray()
	b.resize(FLASH_BYTES)
	b.encode_s32(0, 1) # meta.x = active light count
	var o := FLASH_META_BYTES # slot 0
	b.encode_float(o + 0, pos.x)
	b.encode_float(o + 4, pos.y)
	b.encode_float(o + 8, pos.z)
	b.encode_float(o + 12, maxf(range, 1e-4))
	b.encode_float(o + 16, d.x)
	b.encode_float(o + 20, d.y)
	b.encode_float(o + 24, d.z)
	b.encode_float(o + 28, cos_outer)
	b.encode_float(o + 32, color.r * energy)
	b.encode_float(o + 36, color.g * energy)
	b.encode_float(o + 40, color.b * energy)
	b.encode_float(o + 44, cos_inner)
	_flash_bytes = b
	_flash_version += 1


static func clear_flashlight() -> void:
	_flash_bytes = PackedByteArray()
	_flash_version += 1


# Always FLASH_BYTES: real slots when active, else zeros (meta.x = 0 => shader skips).
# Buffer stays bound so the descriptor set / pipeline need no rebuild when it toggles.
static func _flash_padded() -> PackedByteArray:
	if _flash_bytes.size() == FLASH_BYTES:
		return _flash_bytes
	var z := PackedByteArray()
	z.resize(FLASH_BYTES)
	return z


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

	# Refresh env-SH contents if they changed (fixed 144 B => no rebuild needed).
	if bundle.env_version != _env_version:
		var env_data := _env_padded()
		ctx.device.buffer_update(bundle.env_desc.rid, 0, ENV_SH_BYTES, env_data)
		bundle.env_version = _env_version

	# Refresh local-light contents if they changed (fixed 208 B => no rebuild needed).
	if bundle.flash_version != _flash_version:
		var flash_data := _flash_padded()
		ctx.device.buffer_update(bundle.flash_desc.rid, 0, FLASH_BYTES, flash_data)
		bundle.flash_version = _flash_version

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
	b.env_desc = ctx.create_storage_buffer(ENV_SH_BYTES, _env_padded())
	b.env_version = _env_version
	b.flash_desc = ctx.create_storage_buffer(FLASH_BYTES, _flash_padded())
	b.flash_version = _flash_version
	b.descriptor_set = ctx.create_descriptor_set([
		state.descriptors["culled_splats"],
		state.descriptors["splat_instance_ids"],
		state.descriptors["instance_transforms"],
		b.material_desc,
		b.env_desc,
		b.flash_desc,
	], b.shader, 0)
	b.pipeline = ctx.create_pipeline([ceili(point_count / float(LOCAL_SIZE)), 1, 1], [b.descriptor_set], b.shader)
	return b


static func _push_constant(point_count: int) -> PackedByteArray:
	# Exactly 12 x 4 bytes = 48 bytes = 3 vec4 (Godot 4.7 requires an exact match).
	return RenderingDeviceContext.create_push_constant([
		_light_dir.x, _light_dir.y, _light_dir.z, _wrap_power,
		_light_color.x, _light_color.y, _light_color.z, _ambient,
		_mode, point_count, _trans_on, _env_active,
	])
