@tool
extends RefCounted
class_name RelightPlyLoader

# Loads an extended `splat_relight_schema 1` PLY into a RelightGaussianResource.
#
# REUSES the vendored GDGS BinaryPlyReader + GaussianResourceBuilder verbatim so
# the standard geometry (centering / covariance / std430 packing) is byte-identical
# to a GDGS import. The stock StandardPlyDecoder is NOT usable here (it requires
# f_dc_* which our schema does not carry), so this owns its per-property read loop.
#
# Our PLY stores RAW 3DGS fields (log-scale, logit-opacity, quat w,x,y,z) exactly
# as gsplat/export emit them — VERIFIED against precompute/core/{schema,ply_io}.py
# and stages/export.py (2026-07-12): export writes g["scale"]/g["opacity"] with no
# activation. So exp()/sigmoid() are applied HERE, matching StandardPlyDecoder.
#
# NO coordinate re-conversion: COLMAP->Godot happened once in export (ply_io).

const BinaryPlyReader = preload("res://addons/gdgs/importers/parsers/binary_ply_reader.gd")
const GaussianResourceBuilder = preload("res://addons/gdgs/importers/builders/gaussian_resource_builder.gd")
const RelightGaussianResourceScript = preload("res://relight/relight_gaussian_resource.gd")

const SH_C0 := 0.28209479177387814          # matches precompute gaussmath.SH_C0
const SCHEMA_VERSION := 1
const SH_FLOAT_COUNT := 48

# Fields required by the splat_relight schema (all float except label = uchar).
const REQUIRED_FLOATS := [
	"x", "y", "z",
	"scale_0", "scale_1", "scale_2",
	"rot_0", "rot_1", "rot_2", "rot_3",
	"opacity",
	"albedo_r", "albedo_g", "albedo_b",
	"nx", "ny", "nz",
	"rough", "trans",
]

static func load(path: String) -> RelightGaussianResource:
	# (1a) provenance: header must carry `comment splat_relight_schema N`.
	var ver := _read_schema_version(path)
	if ver < 0:
		push_error("[relight] %s: missing 'comment splat_relight_schema N' header" % path)
		return null
	if ver != SCHEMA_VERSION:
		push_error("[relight] %s: schema version mismatch (file v%d, loader v%d)" % [path, ver, SCHEMA_VERSION])
		return null

	# (1b) parse + require binary_little_endian (BinaryPlyReader enforces this).
	var ply := BinaryPlyReader.read(path, true)
	if not ply.get("ok", false):
		push_error("[relight] %s: %s" % [path, ply.get("message", "PLY read failed")])
		return null
	if String(ply.get("format", "")) != "binary_little_endian":
		push_error("[relight] %s: only binary_little_endian PLY supported" % path)
		return null

	var vertex := BinaryPlyReader.get_element(ply, "vertex")
	if vertex.is_empty():
		push_error("[relight] %s: no vertex element" % path)
		return null

	var property_map: Dictionary = vertex.get("property_map", {})
	for name in REQUIRED_FLOATS:
		if not property_map.has(name):
			push_error("[relight] %s: missing required property '%s'" % [path, name])
			return null
	var has_label: bool = property_map.has("label")

	var count := int(vertex.get("count", 0))
	var stride := int(vertex.get("stride", 0))
	var data: PackedByteArray = vertex.get("data", PackedByteArray())
	if count <= 0 or data.size() != count * stride:
		push_error("[relight] %s: vertex data size mismatch" % path)
		return null

	# Hoist byte offsets out of the hot loop (millions of splats).
	var o_x := int(property_map["x"]["offset"])
	var o_y := int(property_map["y"]["offset"])
	var o_z := int(property_map["z"]["offset"])
	var o_s0 := int(property_map["scale_0"]["offset"])
	var o_s1 := int(property_map["scale_1"]["offset"])
	var o_s2 := int(property_map["scale_2"]["offset"])
	var o_r0 := int(property_map["rot_0"]["offset"])
	var o_r1 := int(property_map["rot_1"]["offset"])
	var o_r2 := int(property_map["rot_2"]["offset"])
	var o_r3 := int(property_map["rot_3"]["offset"])
	var o_op := int(property_map["opacity"]["offset"])
	var o_ar := int(property_map["albedo_r"]["offset"])
	var o_ag := int(property_map["albedo_g"]["offset"])
	var o_ab := int(property_map["albedo_b"]["offset"])
	var o_nx := int(property_map["nx"]["offset"])
	var o_ny := int(property_map["ny"]["offset"])
	var o_nz := int(property_map["nz"]["offset"])
	var o_rough := int(property_map["rough"]["offset"])
	var o_trans := int(property_map["trans"]["offset"])
	var o_label := int(property_map["label"]["offset"]) if has_label else -1

	# Canonical arrays that GDGS's builder centers + packs.
	var canonical := GaussianResourceBuilder.create_canonical(count)
	var positions: PackedVector3Array = canonical["positions"]
	var scales_linear: PackedVector3Array = canonical["scales_linear"]
	var rotations: Array = canonical["rotations"]
	var opacities: PackedFloat32Array = canonical["opacities"]
	var sh_coeffs: PackedFloat32Array = canonical["sh_coeffs"]

	# Our per-splat material buffer (3 vec4 = 12 floats) + raw arrays for the gate.
	# Layout (std430, MUST match Material in relight.glsl):
	#   vec4 albedo_rough : rgb = albedo, w = rough
	#   vec4 normal_trans : xyz = object-space normal, w = trans
	#   vec4 pos_label    : xyz = object-space CENTERED position, w = label
	# The position slot is filled AFTER GaussianResourceBuilder.build() so it carries
	# the SAME centered object-space position the GDGS render path uses (the builder
	# subtracts the per-asset centroid); the flashlight/point-light pass transforms it
	# to world with the same instance matrix already used for the normal. This is our
	# GPU buffer layout, NOT the PLY schema (.vply already stores x/y/z) -> no
	# schema-version bump.
	var attr := PackedFloat32Array()
	attr.resize(count * 12)
	var albedo_rgb := PackedFloat32Array()
	albedo_rgb.resize(count * 3)
	var normal_xyz := PackedFloat32Array()
	normal_xyz.resize(count * 3)
	var rough_arr := PackedFloat32Array()
	rough_arr.resize(count)
	var trans_arr := PackedFloat32Array()
	trans_arr.resize(count)
	var label_arr := PackedByteArray()
	label_arr.resize(count)

	for i in count:
		var base := i * stride

		positions[i] = Vector3(
			data.decode_float(base + o_x),
			data.decode_float(base + o_y),
			data.decode_float(base + o_z))

		scales_linear[i] = Vector3(
			exp(data.decode_float(base + o_s0)),
			exp(data.decode_float(base + o_s1)),
			exp(data.decode_float(base + o_s2)))

		opacities[i] = 1.0 / (1.0 + exp(-data.decode_float(base + o_op)))

		# stored (w,x,y,z) -> Godot Quaternion(x,y,z,w)
		rotations[i] = Quaternion(
			data.decode_float(base + o_r1),
			data.decode_float(base + o_r2),
			data.decode_float(base + o_r3),
			data.decode_float(base + o_r0)).normalized()

		var ar := data.decode_float(base + o_ar)
		var ag := data.decode_float(base + o_ag)
		var ab := data.decode_float(base + o_ab)
		# SH-DC slot so the UNTOUCHED GDGS get_color() (0.5 + sh0*SH_C0) reproduces
		# raw albedo for RAW display; higher SH orders left at zero.
		var sh_base := i * SH_FLOAT_COUNT
		sh_coeffs[sh_base + 0] = (ar - 0.5) / SH_C0
		sh_coeffs[sh_base + 1] = (ag - 0.5) / SH_C0
		sh_coeffs[sh_base + 2] = (ab - 0.5) / SH_C0

		var nx := data.decode_float(base + o_nx)
		var ny := data.decode_float(base + o_ny)
		var nz := data.decode_float(base + o_nz)
		var ro := data.decode_float(base + o_rough)
		var tr := data.decode_float(base + o_trans)

		var a3 := i * 3
		albedo_rgb[a3 + 0] = ar
		albedo_rgb[a3 + 1] = ag
		albedo_rgb[a3 + 2] = ab
		normal_xyz[a3 + 0] = nx
		normal_xyz[a3 + 1] = ny
		normal_xyz[a3 + 2] = nz
		rough_arr[i] = ro
		trans_arr[i] = tr
		label_arr[i] = data[base + o_label] if has_label else 0

		var m := i * 12
		attr[m + 0] = ar
		attr[m + 1] = ag
		attr[m + 2] = ab
		attr[m + 3] = ro
		attr[m + 4] = nx
		attr[m + 5] = ny
		attr[m + 6] = nz
		attr[m + 7] = tr
		# m+8..11 (object-space position + label) filled after build (below), so the
		# packed position matches the builder's CENTERED geometry.

	# Byte-identical GDGS build (centering / covariance / std430 packing).
	var build_result := GaussianResourceBuilder.build(canonical)
	if not build_result.get("ok", false):
		push_error("[relight] %s: %s" % [path, build_result.get("message", "build failed")])
		return null
	var base_res: GaussianResource = build_result["resource"]

	# Fill the material buffer's object-space position slot from the builder's CENTERED
	# positions (base_res.xyz) so it matches exactly what the GDGS render path / instance
	# matrix consume; w carries the label for possible future per-light masking.
	var centered: PackedVector3Array = base_res.xyz
	for i in count:
		var m := i * 12
		attr[m + 8] = centered[i].x
		attr[m + 9] = centered[i].y
		attr[m + 10] = centered[i].z
		attr[m + 11] = float(label_arr[i])

	var res := RelightGaussianResourceScript.new()
	res.point_count = base_res.point_count
	res.point_data_float = base_res.point_data_float
	res.point_data_byte = base_res.point_data_byte
	res.xyz = base_res.xyz
	res.aabb = base_res.aabb
	res.attr_data_byte = attr.to_byte_array()
	res.relight_schema_version = ver
	res.albedo_rgb = albedo_rgb
	res.normal_xyz = normal_xyz
	res.rough = rough_arr
	res.trans = trans_arr
	res.label = label_arr
	return res


# Scan just the PLY header (cheap) for `comment splat_relight_schema N`.
# Returns N, or -1 if absent / malformed / not a PLY.
static func _read_schema_version(path: String) -> int:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return -1
	var magic := f.get_line().strip_edges()
	if magic != "ply":
		return -1
	var found := -1
	while not f.eof_reached():
		var line := f.get_line().strip_edges()
		if line == "end_header":
			break
		var parts := line.split(" ", false)
		if parts.size() >= 3 and parts[0] == "comment" and parts[1] == "splat_relight_schema":
			if parts[2].is_valid_int():
				found = int(parts[2])
	return found
