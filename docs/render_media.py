"""Render the README GIFs headless with the add-on's own measuring and drawing code.

    BLENDER_USER_RESOURCES=<scratch dir with the add-on in extensions/user_default>
    blender -b --factory-startup --python docs/render_media.py

Each frame moves the default cube, measures it with a Session and draws the viewport
plus the indicator into an offscreen buffer. ffmpeg turns the frames into a GIF
and the last frame into a PNG.
"""

import importlib
import math
import os
import subprocess
import sys
from types import SimpleNamespace

import addon_utils
import bpy
import gpu
import numpy as np
from mathutils import Euler, Matrix, Vector

MODULE = "bl_ext.user_default.transform_indicator"
OUT = os.path.dirname(os.path.abspath(__file__))
WIDTH, HEIGHT = 800, 450
UI_SCALE = 1.5
FPS = 30
HOLD = 20


def ease(t):
    return t * t * (3.0 - 2.0 * t)


def setup():
    gpu.init()
    addon_utils.enable(MODULE, default_set=True)
    addon = importlib.import_module(MODULE)
    screen = bpy.data.screens["Layout"]
    area = next(a for a in screen.areas if a.type == 'VIEW_3D')
    space = area.spaces.active
    space.overlay.show_stats = False
    space.overlay.show_extras = False
    region = next(r for r in area.regions if r.type == 'WINDOW')
    camera = bpy.data.objects["Camera"]
    camera.location = (10.0, -9.2, 6.8)
    camera.rotation_euler = Euler((math.radians(63), 0.0, math.radians(47)))
    bpy.context.view_layer.update()
    view = camera.matrix_world.inverted()
    proj = camera.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=WIDTH, y=HEIGHT)
    rv3d = SimpleNamespace(
        perspective_matrix=proj @ view,
        view_matrix=view,
        is_perspective=True,
        view_perspective='PERSP',
        view_rotation=view.inverted().to_quaternion(),
    )
    ctx = SimpleNamespace(
        region=SimpleNamespace(width=WIDTH, height=HEIGHT),
        region_data=rv3d,
        preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=UI_SCALE)),
        scene=bpy.context.scene,
    )
    return addon, space, region, view, proj, ctx


def render_frame(addon, space, region, view, proj, ctx, offscreen, ind):
    with offscreen.bind():
        offscreen.draw_view3d(
            bpy.context.scene, bpy.context.view_layer, space, region, view, proj, do_color_management=True
        )
        if ind is not None:
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(
                    Matrix.Translation((-1.0, -1.0, 0.0)) @ Matrix.Diagonal((2.0 / WIDTH, 2.0 / HEIGHT, 1.0, 1.0))
                )
                addon.draw.draw(ctx, ind, addon.prefs.get())
        pixels = np.array(offscreen.texture_color.read().to_list(), dtype=np.float32)
    # An RGBA8 texture reads back as 0-255 values.
    return np.clip(pixels, 0.0, 255.0).astype(np.uint8)[::-1].tobytes()


def record(name, kind, pose, frames):
    """pose(t) sets the cube for t in [0, 1]; the GIF holds the last frame for a moment."""
    addon, space, region, view, proj, ctx = setup_state
    cube = bpy.data.objects["Cube"]
    start = cube.matrix_world.copy()
    window = bpy.context.window_manager.windows[0]
    with bpy.context.temp_override(window=window):
        session = addon.session.Session.capture(bpy.context)
    offscreen = gpu.types.GPUOffScreen(WIDTH, HEIGHT)
    raw = os.path.join(OUT, name + ".raw")
    with open(raw, "wb") as f:
        for i in range(frames + HOLD):
            pose(cube, start, ease(min(i / (frames - 1), 1.0)))
            bpy.context.view_layer.update()
            ind = session.measure(bpy.context, kind)
            frame = render_frame(addon, space, region, view, proj, ctx, offscreen, ind)
            f.write(frame)
    offscreen.free()
    cube.matrix_world = start
    bpy.context.view_layer.update()
    gif = os.path.join(OUT, name + ".gif")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", raw,
            "-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
            gif,
        ],
        check=True,
    )
    os.remove(raw)
    png = os.path.join(OUT, name + ".png")
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{WIDTH}x{HEIGHT}", "-i", "-",
            "-frames:v", "1", png,
        ],
        input=frame,
        check=True,
    )
    print("wrote", gif, png)


def move(cube, start, t):
    cube.matrix_world = Matrix.Translation(Vector((2.2, 1.6, 0.9)) * t) @ start


def rotate(cube, start, t):
    cube.matrix_world = Matrix.Rotation(math.radians(420.0) * t, 4, 'Z') @ start


def scale(cube, start, t):
    factor = 1.0 + 0.7 * math.sin(t * math.pi * 1.5)
    cube.matrix_world = start @ Matrix.Scale(factor, 4)


setup_state = setup()
record("move", 'TRANSLATE', move, 50)
record("rotate", 'ROTATE', rotate, 70)
record("scale", 'RESIZE', scale, 60)
sys.exit(0)
