@tool
extends GaussianResource
class_name RelightGaussianResource

# Extended relightable Gaussian resource (schema `splat_relight_schema 1`).
#
# is-a GaussianResource so it drops straight into GaussianSplatNode.gaussian and
# flows through the UNTOUCHED GDGS render path (the standard 60-float/240-byte
# point_data_byte is populated exactly as GDGS builds it). The relight compute
# pass consumes `attr_data_byte` — a per-splat std430 material buffer packed as
# three vec4 (48 bytes/splat), SAME splat order as point_data_byte:
#     vec4(albedo.rgb, rough)
#     vec4(nx, ny, nz, trans)
#     vec4(pos_obj.xyz, label)   # object-space CENTERED position (point/spot light L)
#
# The raw per-property arrays are kept for the headless data gate (range / unit /
# label checks); they are not consumed at render time.

@export var attr_data_byte: PackedByteArray          # per-splat material buffer, 48 B/splat
@export var relight_schema_version: int = 0

# Raw material attributes (data-gate only; render reads attr_data_byte).
@export var albedo_rgb: PackedFloat32Array           # count * 3
@export var normal_xyz: PackedFloat32Array           # count * 3
@export var rough: PackedFloat32Array                # count
@export var trans: PackedFloat32Array                # count
@export var label: PackedByteArray                   # count
