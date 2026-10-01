"""Renders the hero: a glass Erlenmeyer flask with teal liquid, PNG sequence with alpha.

Run: Blender -b -P hero_flask.py -- <out_dir> [frames] [size]
Lathed from a profile so it matches the product's flask silhouette.
"""

import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
OUT = argv[0] if argv else "/tmp/hero"
FRAMES = int(argv[1]) if len(argv) > 1 else 1
SIZE = int(argv[2]) if len(argv) > 2 else 1080

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Outer profile (radius, height): lip, neck, shoulder, cone, rounded base.
OUTER = [
    (0.0, 0.0),
    (0.95, 0.0),
    (1.08, 0.06),
    (1.13, 0.2),
    (0.42, 1.55),
    (0.36, 1.75),
    (0.36, 2.45),
    (0.44, 2.5),
    (0.44, 2.6),
    (0.30, 2.6),
]
LIQUID_TOP = 0.78


def lathe(name, profile, steps=96):
    verts, faces = [], []
    n = len(profile)
    for s in range(steps):
        a = 2 * math.pi * s / steps
        for r, z in profile:
            verts.append((r * math.cos(a), r * math.sin(a), z))
    for s in range(steps):
        for i in range(n - 1):
            a0, a1 = s * n + i, ((s + 1) % steps) * n + i
            faces.append((a0, a1, a1 + 1, a0 + 1))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    return obj


def cone_radius(z):
    # Inner radius of the cone wall at height z (between the base and the shoulder).
    return 1.13 + (0.42 - 1.13) * (z - 0.2) / (1.55 - 0.2)


glass = lathe("Glass", OUTER)
sol = glass.modifiers.new("Thick", "SOLIDIFY")
sol.thickness = 0.045
sol.offset = -1
sub = glass.modifiers.new("Sub", "SUBSURF")
sub.levels = sub.render_levels = 2

liq_profile = [
    (0.0, 0.07),
    (0.9, 0.07),
    (1.02, 0.14),
    (cone_radius(0.25) - 0.06, 0.25),
    (cone_radius(LIQUID_TOP) - 0.06, LIQUID_TOP),
    (0.0, LIQUID_TOP),
]
liquid = lathe("Liquid", liq_profile)
ls = liquid.modifiers.new("Sub", "SUBSURF")
ls.levels = ls.render_levels = 2

flask = bpy.data.objects.new("Flask", None)
scene.collection.objects.link(flask)
glass.parent = flask
liquid.parent = flask


def mat_glass():
    m = bpy.data.materials.new("GlassMat")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1)
    b.inputs["Roughness"].default_value = 0.02
    b.inputs["IOR"].default_value = 1.45
    b.inputs["Transmission Weight"].default_value = 1.0
    return m


def mat_liquid():
    m = bpy.data.materials.new("LiquidMat")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    # Vertical gradient teal -> blue, the brand seed into Google blue.
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.0, 0.22, 0.20, 1)
    ramp.color_ramp.elements[1].color = (0.01, 0.42, 0.48, 1)
    nt.links.new(coord.outputs["Object"], sep.inputs[0])
    nt.links.new(sep.outputs["Z"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.12
    b.inputs["Transmission Weight"].default_value = 0.15
    b.inputs["Subsurface Weight"].default_value = 0.0
    nt.links.new(ramp.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 0.08
    b.inputs["Coat Weight"].default_value = 1.0
    return m


glass.data.materials.append(mat_glass())
liquid.data.materials.append(mat_liquid())


# Lights: a big soft key plus brand-colored rims that orbit, so reflections travel.
def area(name, loc, color, power, size):
    d = bpy.data.lights.new(name, "AREA")
    d.color = color
    d.energy = power
    d.size = size
    o = bpy.data.objects.new(name, d)
    o.location = loc
    scene.collection.objects.link(o)
    c = o.constraints.new("TRACK_TO")
    c.target = flask
    return o


rig = bpy.data.objects.new("Rig", None)
scene.collection.objects.link(rig)
area("Key", (3, -4, 5), (1, 1, 1), 900, 5)
for name, loc, col in (
    ("RimTeal", (-4, 2, 2.5), (0.3, 0.9, 0.8)),
    ("RimBlue", (4, 3, 1.5), (0.4, 0.6, 1.0)),
    ("RimWarm", (0, 4, 4), (1.0, 0.85, 0.5)),
):
    area(name, loc, col, 700, 3).parent = rig

world = bpy.data.worlds.new("W")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1.0, 1.0, 1.0, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
scene.world = world

cam_d = bpy.data.cameras.new("Cam")
cam_d.lens = 70
cam = bpy.data.objects.new("Cam", cam_d)
cam.location = (0, -9.2, 3.3)
cam.rotation_euler = (math.radians(78), 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam

# Motion: a gentle sway and the light rig orbiting once.
scene.frame_start = 1
scene.frame_end = FRAMES
# Spin about the flask's own axis first, then sway in world space. In the
# default XYZ order the sway is applied inside the spin, so after the quarter
# turn it points 90 degrees away from where the loop began and the loop jumps.
# The lathes have 96 segments, so a quarter turn lands on the same geometry.
flask.rotation_mode = "ZXY"
for f in range(1, FRAMES + 1):
    t = (f - 1) / max(1, FRAMES)
    flask.rotation_euler = (
        math.radians(6 * math.sin(2 * math.pi * t)),
        math.radians(5 * math.sin(2 * math.pi * t + 1)),
        2 * math.pi * t * 0.25,
    )
    flask.location = (0, 0, 0.08 * math.sin(2 * math.pi * t))
    flask.keyframe_insert("rotation_euler", frame=f)
    flask.keyframe_insert("location", frame=f)
    rig.rotation_euler = (0, 0, 2 * math.pi * t)
    rig.keyframe_insert("rotation_euler", frame=f)

r = scene.render
r.engine = "CYCLES"
scene.cycles.device = "GPU"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
# Background kernel specialization crashed Blender 5.2 mid-render (Metal
# binary-archive serialization); the generic kernels are stable.
if hasattr(prefs, "kernel_optimization_level"):
    prefs.kernel_optimization_level = "OFF"
prefs.get_devices()
for d in prefs.devices:
    d.use = True
scene.cycles.samples = int(argv[3]) if len(argv) > 3 else 32
scene.cycles.adaptive_threshold = 0.03
scene.cycles.use_denoising = True
scene.cycles.transparent_max_bounces = 16
scene.cycles.transmission_bounces = 16
r.film_transparent = True
scene.cycles.film_transparent_glass = False
r.resolution_x = r.resolution_y = SIZE
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
r.filepath = OUT + "/flask_"
scene.view_settings.view_transform = "AgX"
# Resume support: argv[4] is the first frame to render (keys still cover the whole loop).
scene.frame_start = int(argv[4]) if len(argv) > 4 else 1
bpy.ops.render.render(animation=True)
