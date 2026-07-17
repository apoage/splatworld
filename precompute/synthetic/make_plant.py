"""Synthetic two-sided-leaf plant generator + multi-view renderer (headless Blender bpy).

Purpose (D7 sign-recovery research substrate — tasks/2026-07-17-synthetic-plant-gt.md):
build a plant whose leaves have KNOWN per-face orientation and a DISTINCT adaxial (top,
dark/waxy/low-reflectance) vs abaxial (bottom, pale/matte/high-reflectance) appearance —
the reflectance asymmetry that carries the front/back SIGN (round-2 research: transmission
is sign-blind by reciprocity; reflectance is the cue). Render a multi-view orbit under a
KNOWN directional sun and export everything needed to (a) reconstruct with our pipeline and
(b) transfer ground-truth sign to each splat by nearest leaf.

Run headless:
  blender --background --python precompute/synthetic/make_plant.py -- --out <dir> [--views N] [--res R] [--samples S]

Outputs under <out>/:
  render/r_XXX.png            multi-view images
  transforms.json             NeRF-style intrinsics + per-frame camera_to_world (Blender frame)
  scene_gt.json               sun direction (world) + per-leaf {centroid, adaxial_normal} GT
  plant.blend                 the scene (for inspection)
  plant_mesh.ply              leaf mesh (ascii) for nearest-face GT transfer after reconstruction

Coordinate note: all matrices/vectors are in BLENDER world frame (Z up, camera looks -Z,
up +Y). Conversion to our COLMAP/Godot convention happens downstream, documented where used.
Deterministic: fixed layout math, no RNG seeding required (a small LCG gives repeatable jitter).
"""
import bpy, bmesh, json, math, os, sys
from mathutils import Vector, Matrix, Euler


def _argv():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    d = {"out": "assets/synthetic/plant01", "views": 24, "res": 512, "samples": 48, "leaves": 12}
    i = 0
    while i < len(a):
        k = a[i].lstrip("-")
        if k in d:
            d[k] = a[i + 1]; i += 2
        else:
            i += 1
    for k in ("views", "res", "samples", "leaves"):
        d[k] = int(d[k])
    return d


def _lcg(seed):
    s = seed & 0xFFFFFFFF
    while True:
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        yield s / 0x7FFFFFFF


def _clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _two_sided_leaf_material():
    # ONE material, shaded by Geometry.Backfacing: front (face-normal side) = ADAXIAL
    # (dark, glossy, low reflectance), back = ABAXIAL (pale, matte, high reflectance).
    m = bpy.data.materials.new("leaf_two_sided")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    mix = nt.nodes.new("ShaderNodeMixShader")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    adax = nt.nodes.new("ShaderNodeBsdfPrincipled")  # front / adaxial: dark waxy
    abax = nt.nodes.new("ShaderNodeBsdfPrincipled")  # back  / abaxial: pale matte
    adax.inputs["Base Color"].default_value = (0.045, 0.16, 0.03, 1.0)
    adax.inputs["Roughness"].default_value = 0.30
    abax.inputs["Base Color"].default_value = (0.42, 0.55, 0.34, 1.0)
    abax.inputs["Roughness"].default_value = 0.92
    # Mix factor = Backfacing (0 front -> adax, 1 back -> abax)
    nt.links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    nt.links.new(adax.outputs["BSDF"], mix.inputs[1])
    nt.links.new(abax.outputs["BSDF"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return m


def _stem_material():
    m = bpy.data.materials.new("stem")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = (0.18, 0.12, 0.05, 1.0)
        b.inputs["Roughness"].default_value = 0.8
    return m


def build_plant(n_leaves):
    leaf_mat = _two_sided_leaf_material()
    stem_mat = _stem_material()
    # stem
    bpy.ops.mesh.primitive_cylinder_add(radius=0.03, depth=1.4, location=(0, 0, 0.7))
    stem = bpy.context.active_object
    stem.name = "stem"
    stem.data.materials.append(stem_mat)

    rng = _lcg(1234)
    objs = []
    for i in range(n_leaves):
        t = i / max(n_leaves - 1, 1)
        z = 0.25 + t * 1.05
        az = i * 2.399963  # golden-angle phyllotaxy
        tilt = math.radians(35.0 + 40.0 * next(rng))   # up-tilt of the blade
        length = 0.28 + 0.12 * next(rng)
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 0, z))
        leaf = bpy.context.active_object
        leaf.name = "leaf_%02d" % i
        leaf.scale = (0.09, length, 1.0)
        # orient: face normal (local +Z) tilts outward+up = ADAXIAL up
        leaf.rotation_euler = Euler((tilt, 0.0, az), "XYZ")
        # push the blade out from the stem along its azimuth
        r = 0.12
        leaf.location = (math.sin(az) * r, math.cos(az) * r, z)
        leaf.data.materials.append(leaf_mat)
        objs.append(leaf)
    # Blender computes matrix_world LAZILY — force the depsgraph to apply the transforms we
    # just set BEFORE reading them, or adaxial_normal/centroid export as stale identity (the
    # sun_dir=0,0,-1 bug). Read GT in a second pass after the update.
    bpy.context.view_layer.update()
    leaves = []  # (obj, adaxial_world_normal, centroid_world)
    for leaf in objs:
        n_world = (leaf.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()
        leaves.append((leaf, n_world, leaf.matrix_world.translation.copy()))
    return stem, leaves


def setup_sun():
    # KNOWN directional sun. Store its shining direction (world). Blender Sun points along
    # its local -Z; set a rotation and record the resulting world direction.
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 5))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.rotation_euler = Euler((math.radians(52.0), 0.0, math.radians(35.0)), "XYZ")
    bpy.context.view_layer.update()  # apply the rotation before reading matrix_world (lazy eval)
    sun_dir = (sun.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()  # travel dir
    # a dim sky so back/shadowed faces aren't pure black (still lets asymmetry show)
    world = bpy.data.worlds.new("w"); bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)
        bg.inputs["Strength"].default_value = 0.3
    return sun, sun_dir


def setup_render(res, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        sc.cycles.device = "CPU"  # robust headless; asset is tiny
    except Exception:
        pass
    sc.cycles.samples = samples
    # Denoising off: makes the render independent of the build's OpenImageDenoise support
    # (the old apt Blender 4.3 lacked it) and keeps output deterministic. Bump samples if noisy.
    try:
        sc.cycles.use_denoising = False
    except Exception:
        pass
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.film_transparent = False


def add_camera():
    bpy.ops.object.camera_add(location=(0, -3, 1))
    cam = bpy.context.active_object
    cam.data.lens = 50.0
    cam.data.sensor_width = 36.0
    bpy.context.scene.camera = cam
    return cam


def look_at(cam, target):
    d = (cam.location - target)
    cam.rotation_euler = d.to_track_quat("Z", "Y").to_euler()


def render_orbit(cam, out, n_views, res):
    render_dir = os.path.join(out, "render")
    os.makedirs(render_dir, exist_ok=True)
    target = Vector((0, 0, 0.75))
    radius = 3.2
    frames = []
    sc = bpy.context.scene
    for k in range(n_views):
        az = 2.0 * math.pi * k / n_views
        # elevations sweep high->low and a few BELOW horizon (see undersides = abaxial views)
        el = math.radians(55.0) * math.cos(math.pi * k / n_views)  # +55 down through 0
        if k % 5 == 0:
            el = math.radians(-25.0)  # a below-horizon view every 5th
        cam.location = target + Vector((
            radius * math.cos(el) * math.sin(az),
            -radius * math.cos(el) * math.cos(az),
            radius * math.sin(el) + 0.75,
        ))
        look_at(cam, target)
        bpy.context.view_layer.update()
        fp = os.path.join(render_dir, "r_%03d.png" % k)
        sc.render.filepath = fp
        bpy.ops.render.render(write_still=True)
        frames.append({
            "file_path": "render/r_%03d.png" % k,
            "transform_matrix": [list(row) for row in cam.matrix_world],  # cam_to_world, Blender frame
        })
    cam_angle_x = 2.0 * math.atan(cam.data.sensor_width / (2.0 * cam.data.lens))
    return {"camera_angle_x": cam_angle_x, "w": res, "h": res, "frames": frames}


def export_gt(out, leaves, sun_dir):
    gt = {
        "convention": "blender_world (Z up, cam looks -Z / up +Y); sun_dir = light travel direction",
        "sun_dir_world": list(sun_dir),
        "leaves": [
            {"name": lf.name, "centroid": list(c), "adaxial_normal": list(n)}
            for (lf, n, c) in leaves
        ],
    }
    with open(os.path.join(out, "scene_gt.json"), "w") as f:
        json.dump(gt, f, indent=1)


def export_mesh_ply(out, leaves):
    # Merge leaf faces into one ascii PLY with a per-vertex adaxial normal (for nearest-face
    # GT transfer after reconstruction). Minimal: one quad per leaf, normal = adaxial.
    verts = []
    faces = []
    vnormals = []
    for (lf, n, c) in leaves:
        base = len(verts)
        for co in [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]:
            wco = lf.matrix_world @ Vector(co)
            verts.append(wco)
            vnormals.append(n)
        faces.append((base, base + 1, base + 2, base + 3))
    path = os.path.join(out, "plant_mesh.ply")
    with open(path, "w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write("element vertex %d\n" % len(verts))
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property float nx\nproperty float ny\nproperty float nz\n")
        f.write("element face %d\n" % len(faces))
        f.write("property list uchar int vertex_indices\n")
        f.write("end_header\n")
        for v, nn in zip(verts, vnormals):
            f.write("%f %f %f %f %f %f\n" % (v.x, v.y, v.z, nn.x, nn.y, nn.z))
        for fc in faces:
            f.write("4 %d %d %d %d\n" % fc)


def main():
    cfg = _argv()
    out = cfg["out"]
    if not os.path.isabs(out):
        out = os.path.join(os.getcwd(), out)
    os.makedirs(out, exist_ok=True)
    _clear()
    stem, leaves = build_plant(cfg["leaves"])
    sun, sun_dir = setup_sun()
    setup_render(cfg["res"], cfg["samples"])
    cam = add_camera()
    tf = render_orbit(cam, out, cfg["views"], cfg["res"])
    with open(os.path.join(out, "transforms.json"), "w") as f:
        json.dump(tf, f, indent=1)
    export_gt(out, leaves, sun_dir)
    export_mesh_ply(out, leaves)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "plant.blend"))
    print("SYNPLANT_DONE out=%s views=%d leaves=%d sun_dir=%.3f,%.3f,%.3f"
          % (out, cfg["views"], len(leaves), sun_dir.x, sun_dir.y, sun_dir.z))


if __name__ == "__main__":
    main()
