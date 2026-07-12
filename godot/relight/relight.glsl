#[compute]
#version 460

// M2a relight pass. Runs ONCE per frame, immediately after GDGS's projection pass
// and before its sort, writing the shaded per-splat color into the culled_splats
// buffer (RasterizeData.color.rgb) that the GDGS rasterizer consumes. Only .rgb is
// written; .a (opacity, set by projection) is preserved. Shading is CLAUDE.md
// verbatim: direct + cheap wrap-translucency + flat ambient.

layout(local_size_x = 256, local_size_y = 1, local_size_z = 1) in;

// MUST match GDGS gsplat_projection.glsl / gsplat_render.glsl exactly (16 floats).
struct RasterizeData {
	vec2 image_pos;
	vec2 pos_xy;
	vec3 conic;
	float pos_z;
	vec4 color;
	vec4 depth_data;
};

layout(std430, set = 0, binding = 0) restrict buffer CulledBuffer {
	RasterizeData culled_buffer[];
};

layout(std430, set = 0, binding = 1) restrict readonly buffer SplatInstanceIdsBuffer {
	uvec2 splat_instance_data[]; // x = instance id, y = unique splat data index
};

layout(std430, set = 0, binding = 2) restrict readonly buffer InstanceTransformsBuffer {
	mat4 instance_model_matrices[];
};

struct Material {
	vec4 albedo_rough; // rgb = albedo (SH deg0), w = roughness
	vec4 normal_trans; // xyz = object-space unit normal, w = transmission
};

layout(std430, set = 0, binding = 3) restrict readonly buffer MaterialBuffer {
	Material materials[];
};

// 3 x vec4 = 48 bytes, matched exactly by RelightPass.create_push_constant (Godot 4.7).
layout(push_constant) restrict readonly uniform Params {
	vec4 light_dir_ws; // xyz = light TRAVEL direction (world), w = wrap_power
	vec4 light_color;  // rgb = light color, w = ambient
	ivec4 misc;        // x = mode (0=raw,1=relit), y = point_count, z = trans_on, w = pad
} pc;

const int MODE_RAW = 0;

void main() {
	uint id = gl_GlobalInvocationID.x;
	if (id >= uint(pc.misc.y)) return;

	uvec2 si = splat_instance_data[id];
	Material m = materials[si.y];

	vec3 albedo = m.albedo_rough.rgb;
	vec4 prev = culled_buffer[id].color; // preserve alpha (opacity)

	if (pc.misc.x == MODE_RAW) {
		culled_buffer[id].color = vec4(albedo, prev.a);
		return;
	}

	vec3 normal_obj = m.normal_trans.xyz;
	float trans = (pc.misc.z != 0) ? m.normal_trans.w : 0.0;
	float wrap_power = pc.light_dir_ws.w;
	float ambient = pc.light_color.w;
	vec3 light_color = pc.light_color.rgb;

	// Rotation-only instance transform (M2a single instance); mat3() drops the
	// visibility flag GDGS stores in model[0][3]. Exact for a rigid instance.
	mat3 model3 = mat3(instance_model_matrices[si.x]);
	vec3 N = normalize(model3 * normal_obj);
	vec3 L = normalize(-pc.light_dir_ws.xyz);

	float direct = max(dot(N, L), 0.0);
	// cheap wrap translucency; inert while trans == 0 (placeholder assets)
	float back = trans * pow(max(dot(-N, L), 0.0) * 0.5 + 0.5, wrap_power);
	vec3 color = albedo * (direct + back) * light_color + albedo * ambient;

	culled_buffer[id].color = vec4(color, prev.a);
}
