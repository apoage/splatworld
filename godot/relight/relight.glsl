#[compute]
#version 460

// M2a relight pass. Runs ONCE per frame, immediately after GDGS's projection pass
// and before its sort, writing the shaded per-splat color into the culled_splats
// buffer (RasterizeData.color.rgb) that the GDGS rasterizer consumes. Only .rgb is
// written; .a (opacity, set by projection) is preserved. Shading is CLAUDE.md
// verbatim: direct + cheap wrap-translucency + ambient, PLUS optional local
// point/spot lights (flashlight) that ADD the same direct+back term with a
// per-splat local L, inverse-square range falloff, and a smooth spot cone.

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
	vec4 pos_label;    // xyz = object-space CENTERED position, w = label
};

layout(std430, set = 0, binding = 3) restrict readonly buffer MaterialBuffer {
	Material materials[];
};

// Local light slots (flashlight now; Moon-Stone fireballs later). FIXED-SIZE array
// so N=1 today extends to N=2..MAX_FLASH_LIGHTS without another buffer/shader contract
// change — only the CPU-side setter grows. Populated by RelightPass.set_flashlight;
// flash.meta.x = active light count (0 => no local light this frame). Each slot:
//   pos_range   : xyz = world position,          w = range (falloff cutoff distance)
//   dir_cone    : xyz = spot axis (world, unit),  w = cos(outer cone half-angle)
//   color_cone  : rgb = color * energy,           w = cos(inner cone half-angle)
// std430: ivec4 header (16 B) + MAX_FLASH_LIGHTS * 3 vec4 (48 B each). MUST match
// RelightPass.MAX_FLASH_LIGHTS / FLASH_* byte layout.
const int MAX_FLASH_LIGHTS = 4;
struct FlashLight {
	vec4 pos_range;
	vec4 dir_cone;
	vec4 color_cone;
};
layout(std430, set = 0, binding = 5) restrict readonly buffer FlashBuffer {
	ivec4 meta; // x = active light count
	FlashLight lights[MAX_FLASH_LIGHTS];
} flash;

// Recovered ambient environment (deg-2 real SH), Godot post-flip frame, with the
// Lambertian band factors already folded in (c_lm = (A_l/pi)*L_lm). Populated by
// RelightPass.set_env_sh from the *_env_sh.json sidecar; consumed ONLY when
// pc.misc.w != 0, else the flat pc.light_color.w ambient is used (fallback). Each
// entry: xyz = c_lm RGB, w = pad (9 x vec4 = 144 bytes). The bound coeffs are
// DC-NORMALIZED at bind time (RelightPass.set_env_sh scales all 9 by 1/(SH_C0*luma(c00)))
// so ambient_sh(N) has UNIT sphere-mean luma; the ambient slider (pc.light_color.w)
// below then scales env strength exactly like the flat fallback (same energy budget,
// env keeps only its directional shape + relative tint). The raw sidecar bytes are
// unchanged on disk — this energy normalization lives ONLY here at runtime.
layout(std430, set = 0, binding = 4) restrict readonly buffer EnvSHBuffer {
	vec4 env_sh[9];
} env;

// 3 x vec4 = 48 bytes, matched exactly by RelightPass.create_push_constant (Godot 4.7).
layout(push_constant) restrict readonly uniform Params {
	vec4 light_dir_ws; // xyz = light TRAVEL direction (world), w = wrap_power
	vec4 light_color;  // rgb = light color, w = ambient (flat fallback)
	ivec4 misc;        // x = mode (0=raw,1=relit), y = point_count, z = trans_on, w = use_env_sh
} pc;

const int MODE_RAW = 0;

// Real degree-2 SH basis constants + evaluation order. MUST match
// precompute/core/sh_env.py (_C0.._C2c and the 9-term ordering) — that module is
// the single source of truth; the data gate dumps those constants and asserts
// these literals equal them. ambient_sh(N) = sum_lm c_lm * Y_lm(N); the c_lm come
// pre-flipped and pre-folded from the sidecar, so evaluate the basis and NOTHING
// else (no coordinate re-flip, no re-application of A_l/pi).
const float SH_C0  = 0.28209479177387814; // 0.5*sqrt(1/pi)      -> Y00
const float SH_C1  = 0.4886025119029199;  // 0.5*sqrt(3/pi)      -> Y1-1 (y), Y10 (z), Y11 (x)
const float SH_C2a = 1.0925484305920792;  // 0.5*sqrt(15/pi)     -> Y2-2 (xy), Y2-1 (yz), Y21 (xz)
const float SH_C2b = 0.31539156525252005; // 0.25*sqrt(5/pi)     -> Y20 (3z^2-1)
const float SH_C2c = 0.5462742152960396;  // 0.25*sqrt(15/pi)    -> Y22 (x^2-y^2)

vec3 ambient_sh(vec3 n) {
	float x = n.x, y = n.y, z = n.z;
	vec3 c = env.env_sh[0].rgb * SH_C0;
	c += env.env_sh[1].rgb * (SH_C1 * y);
	c += env.env_sh[2].rgb * (SH_C1 * z);
	c += env.env_sh[3].rgb * (SH_C1 * x);
	c += env.env_sh[4].rgb * (SH_C2a * x * y);
	c += env.env_sh[5].rgb * (SH_C2a * y * z);
	c += env.env_sh[6].rgb * (SH_C2b * (3.0 * z * z - 1.0));
	c += env.env_sh[7].rgb * (SH_C2a * x * z);
	c += env.env_sh[8].rgb * (SH_C2c * (x * x - y * y));
	return c;
}

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

	mat4 model = instance_model_matrices[si.x];
	// Rotation-only for the normal; mat3() drops the visibility flag GDGS stores in
	// model[0][3]. Exact for a rigid instance.
	mat3 model3 = mat3(model);
	vec3 N = normalize(model3 * normal_obj);
	vec3 L = normalize(-pc.light_dir_ws.xyz);

	float direct = max(dot(N, L), 0.0);
	// cheap wrap translucency; inert while trans == 0 (placeholder assets)
	float back = trans * pow(max(dot(-N, L), 0.0) * 0.5 + 0.5, wrap_power);
	// CLAUDE.md ambient term: recovered env-SH when a sidecar is bound
	// (pc.misc.w != 0), else the flat scalar fallback. N is the world-space
	// normal already used by the direct term; the sidecar coeffs are in the same
	// Godot world frame, so no re-flip is applied here. The bound env coeffs are
	// DC-normalized (unit sphere-mean luma) at bind time, so the ambient slider
	// (pc.light_color.w) scales the env shape to the SAME energy budget as the flat
	// fallback -> env-on vs env-off differ in directional SHAPE, not overall energy.
	vec3 ambient_rgb = (pc.misc.w != 0) ? pc.light_color.w * ambient_sh(N) : vec3(ambient);
	vec3 color = albedo * (direct + back) * light_color + albedo * ambient_rgb;

	// Local point/spot lights (flashlight; Moon-Stone fireballs later). Each ADDS a
	// second `direct + back` evaluation with a per-splat local L, using the SAME
	// albedo/normal/trans math, scaled by inverse-square range falloff * smooth cone.
	// Object-space (centered) position -> world with the SAME instance matrix as N.
	// RAW mode already returned above, so this never leaks into raw output.
	int n_flash = flash.meta.x;
	if (n_flash > 0) {
		vec3 pos_ws = (model * vec4(m.pos_label.xyz, 1.0)).xyz;
		for (int i = 0; i < MAX_FLASH_LIGHTS; ++i) {
			if (i >= n_flash) break;
			FlashLight fl = flash.lights[i];
			vec3 to_light = fl.pos_range.xyz - pos_ws;
			float dist = length(to_light);
			vec3 Lf = to_light / max(dist, 1e-4);
			// inverse-square with a smooth range window that reaches 0 at `range`.
			float range = max(fl.pos_range.w, 1e-4);
			float inv_sq = 1.0 / (1.0 + dist * dist);
			float range_win = clamp(1.0 - (dist * dist) / (range * range), 0.0, 1.0);
			float falloff = inv_sq * range_win;
			// smooth spot cone: 1 inside inner half-angle, 0 outside outer half-angle.
			float cos_a = dot(-Lf, fl.dir_cone.xyz);
			float cone = smoothstep(fl.dir_cone.w, fl.color_cone.w, cos_a);
			float w = falloff * cone;
			if (w <= 0.0) continue;
			float direct_f = max(dot(N, Lf), 0.0);
			float back_f = trans * pow(max(dot(-N, Lf), 0.0) * 0.5 + 0.5, wrap_power);
			color += albedo * (direct_f + back_f) * fl.color_cone.rgb * w;
		}
	}

	culled_buffer[id].color = vec4(color, prev.a);
}
