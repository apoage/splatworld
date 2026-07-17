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
// D7 sign-agnostic prototype (docs/d7-synthesis-2026-07-17.md): the binding-5 buffer
// also carries the sign mode + the params the sign-agnostic lobes need, so the push
// constant is NOT touched. meta.y = sign_mode (0 signed / 1 sign-free wrap / 2
// flip-toward-camera). cam_sign.xyz = camera WORLD position (mode 2 orients the normal
// toward it); cam_sign.w = the sign-free wrap w (mode 1). Both are always populated
// (RelightPass._binding5_bytes) so mode 1/2 stay valid regardless of flashlight state.
layout(std430, set = 0, binding = 5) restrict readonly buffer FlashBuffer {
	ivec4 meta; // x = active light count, y = sign_mode, z = viz_mode (facing-debug overlay)
	FlashLight lights[MAX_FLASH_LIGHTS];
	vec4 cam_sign; // xyz = camera world pos (mode 2), w = sign-free wrap w (mode 1)
} flash;

// D7 sign modes for the diffuse direct lobe. Mode 0 is the shipped signed behavior and
// MUST stay byte-identical when selected (default).
const int SIGN_SIGNED = 0; // max(dot(N,L),0)                        — current shipped path
const int SIGN_WRAP   = 1; // sign-free two-sided wrap (abs first)   — consensus lobe
const int SIGN_FLIP   = 2; // flip N toward camera, then signed      — published 3DGS convention

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

// D7 diffuse direct lobe with a selectable sign policy. V = splat->camera unit dir,
// w = sign-free wrap width. SIGN_SIGNED reproduces max(dot(N,L),0) EXACTLY (mode-0
// byte-identity). SIGN_WRAP takes abs FIRST (half-Lambert on signed N.L is NOT
// sign-agnostic) then wrap-normalizes by (1+w) twice, so a flat |N.L|==1 face reads
// 1/(1+w) — not 1.0 (plain abs, which reads flat) and not a signed lobe. SIGN_FLIP
// orients N toward the camera (published convention) then shades signed.
float direct_lobe(vec3 N, vec3 L, vec3 V, int sign_mode, float w) {
	if (sign_mode == SIGN_WRAP) {
		return clamp((abs(dot(N, L)) + w) / (1.0 + w), 0.0, 1.0) / (1.0 + w);
	} else if (sign_mode == SIGN_FLIP) {
		vec3 Nv = (dot(N, V) >= 0.0) ? N : -N;
		return max(dot(Nv, L), 0.0);
	}
	return max(dot(N, L), 0.0);
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

	// D7 sign-agnostic prototype: object->world splat position (also reused by the
	// flashlight block below), view dir, and the sign mode + wrap from binding 5.
	// sign_mode == SIGN_SIGNED (0) => direct_lobe is byte-identical to the shipped path.
	vec3 pos_ws = (model * vec4(m.pos_label.xyz, 1.0)).xyz;
	vec3 V = normalize(flash.cam_sign.xyz - pos_ws);
	int sign_mode = flash.meta.y;
	float sign_w = flash.cam_sign.w;

	// D7 facing-debug overlay (viewer key G; binding-5 meta.z, orthogonal to raw/relit so
	// no mode-field collision). Colors the RAW world normal's facing vs a reference —
	// green = front/toward, magenta = back/away, brightness ~|dot| — so the shader's sign
	// DOMAINS and the isolated flipped splats behind the closeup noise are directly visible.
	// Uses raw N (before any sign policy) => shows the DATA's sign, independent of sign_mode.
	// viz 1 = N.L (sun; == the signed lobe's lit/shadow map), 2 = N.V (camera; == mode-2's
	// flip target set), 3 = N.up (world up; the "lit from underground" absolute view).
	// viz 0 => off (byte-identical). RAW mode already returned above, so it never leaks there.
	int viz_mode = flash.meta.z;
	if (viz_mode != 0) {
		vec3 vref = (viz_mode == 2) ? V : ((viz_mode == 3) ? vec3(0.0, 1.0, 0.0) : L);
		float vd = dot(N, vref);
		vec3 vc = (vd >= 0.0) ? vec3(0.15, 1.0, 0.25) : vec3(1.0, 0.10, 0.55);
		vc *= mix(0.30, 1.0, clamp(abs(vd), 0.0, 1.0));
		culled_buffer[id].color = vec4(vc, prev.a);
		return;
	}

	float direct = direct_lobe(N, L, V, sign_mode, sign_w);
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
			// Local lights use the SAME sign policy as the sun (byte-identical in mode 0).
			float direct_f = direct_lobe(N, Lf, V, sign_mode, sign_w);
			float back_f = trans * pow(max(dot(-N, Lf), 0.0) * 0.5 + 0.5, wrap_power);
			color += albedo * (direct_f + back_f) * fl.color_cone.rgb * w;
		}
	}

	culled_buffer[id].color = vec4(color, prev.a);
}
