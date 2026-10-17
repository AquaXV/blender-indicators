"""Screen-space drawing of an Indicator."""

import math

import blf
import bpy
import gpu
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

DASH = 6.0
GAP = 4.0
MARKER = 6.0
FONT_SIZE = 12.0
# Distance between the move line and its label.
LABEL_OFFSET = 10.0
SHADOW = (0.0, 0.0, 0.0, 0.5)
# Each extra full turn widens the arc so multiple turns read as a spiral.
SPIRAL = 0.15


def _pos(points):
    return {"pos": [(p.x, p.y, 0.0) for p in points]}


def _lines(coords, color, width):
    if not coords:
        return
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'LINES', _pos(coords))
    shader.bind()
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    for col, w in ((SHADOW, width + 2.0), (color, width)):
        shader.uniform_float("lineWidth", w)
        shader.uniform_float("color", col)
        batch.draw(shader)


def _disc(center, radius, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    for col, r in ((SHADOW, radius + 1.0), (color, radius)):
        batch = batch_for_shader(shader, 'TRI_FAN', _pos([center] + _circle(center, r, 16)))
        shader.uniform_float("color", col)
        batch.draw(shader)


def _circle(center, radius, segments=48):
    return [
        center + Vector((math.cos(t), math.sin(t))) * radius
        for t in (math.tau * i / segments for i in range(segments + 1))
    ]


def _solid(points):
    return [p for a, b in zip(points, points[1:]) for p in (a, b)]


def _dashed(points, dash, gap):
    period = dash + gap
    out = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        length = (b - a).length
        if length == 0.0:
            continue
        k = math.floor(total / period)
        while k * period < total + length:
            lo = max(k * period, total)
            hi = min(k * period + dash, total + length)
            if hi > lo:
                out += [a.lerp(b, (lo - total) / length), a.lerp(b, (hi - total) / length)]
            k += 1
        total += length
    return out


def _length_text(scene, length):
    units = scene.unit_settings
    return bpy.utils.units.to_string(
        units.system, 'LENGTH', length * units.scale_length, precision=4, split_unit=units.use_separate
    )


def _angle_text(scene, angle):
    if scene.unit_settings.system_rotation == 'RADIANS':
        return "%.3f rad" % angle
    return "%.1f°" % math.degrees(angle)


def _label(text, point, outward, color, ui):
    """Draw text next to a screen point, pushed away from it along outward."""
    font = 0
    blf.size(font, FONT_SIZE * ui)
    width, height = blf.dimensions(font, text)
    outward = outward.normalized() if outward.length > 0.0 else Vector((0.0, 1.0))
    corner = point + outward * LABEL_OFFSET * ui
    # Shift the box so its nearest corner sits at the offset point, keeping it clear of the drawing.
    x = corner.x - (width if outward.x < 0.0 else 0.0)
    y = corner.y - (height if outward.y < 0.0 else 0.0)
    blf.color(font, *color[:3], 1.0)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.8)
    blf.shadow_offset(font, 1, -1)
    blf.position(font, x, y, 0.0)
    blf.draw(font, text)
    blf.disable(font, blf.SHADOW)


def _view_perpendicular(rv3d, axis):
    for local in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)):
        v = rv3d.view_rotation @ Vector(local)
        v -= axis * v.dot(axis)
        if v.length > 1e-6:
            return v.normalized()
    return axis.orthogonal().normalized()


def draw(context, ind, prefs):
    region = context.region
    rv3d = context.region_data
    if rv3d is None:
        return

    def to2d(p):
        return location_3d_to_region_2d(region, rv3d, p)

    ui = context.preferences.system.ui_scale
    width = prefs.line_width * ui
    radius = prefs.radius * ui
    dash, gap = DASH * ui, GAP * ui
    start_col = tuple(prefs.start_color)
    delta_col = tuple(prefs.delta_color)

    gpu.state.blend_set('ALPHA')

    if ind.translation is not None:
        a = to2d(ind.anchor)
        b = to2d(ind.anchor + ind.translation)
        if a is not None and b is not None:
            _lines(_dashed([a, b], dash, gap), delta_col, width)
            if prefs.show_values:
                side = Vector((-(b - a).y, (b - a).x))
                if side.y < 0.0:
                    side = -side
                _label(_length_text(context.scene, ind.translation.length), (a + b) / 2, side, delta_col, ui)
        if b is not None:
            _disc(b, 2.0 * ui, delta_col)

    center = to2d(ind.pivot)
    if center is not None and ind.rotation is not None:
        axis, angle, direction = ind.rotation
        edge = region_2d_to_location_3d(region, rv3d, center + Vector((1.0, 0.0)), ind.pivot)
        world_radius = radius * (edge - ind.pivot).length
        if direction is None:
            direction = _view_perpendicular(rv3d, axis)
        side = axis.cross(direction)
        steps = max(2, int(abs(angle) / math.tau * 64) + 1)
        arc = []
        for i in range(steps + 1):
            t = angle * i / steps
            r = world_radius * (1.0 + SPIRAL * abs(t) / math.tau)
            arc.append(to2d(ind.pivot + (direction * math.cos(t) + side * math.sin(t)) * r))
        if None not in arc:
            _lines(_dashed([center, arc[0]], dash, gap), start_col, width)
            _lines(_solid([center, arc[-1]]), delta_col, width)
            _lines(_solid(arc), delta_col, width)
            if prefs.show_values:
                # The axis sign is arbitrary, so only the magnitude is meaningful.
                _label(_angle_text(context.scene, abs(angle)), arc[-1], arc[-1] - center, delta_col, ui)

    if center is not None and ind.scale is not None:
        _lines(_dashed(_circle(center, radius), dash, gap), start_col, width)
        scaled = min(max(radius * abs(ind.scale), 2.0 * ui), radius * 8.0)
        ring = _circle(center, scaled)
        # A negative (mirrored) scale is drawn dashed.
        _lines(_dashed(ring, dash, gap) if ind.scale < 0.0 else _solid(ring), delta_col, width)
        if prefs.show_values:
            diagonal = Vector((1.0, 1.0)).normalized()
            _label("×%.3f" % ind.scale, center + diagonal * scaled, diagonal, delta_col, ui)

    start = to2d(ind.start)
    if start is not None:
        _lines(_solid(_circle(start, MARKER * ui, 24)), start_col, width)
        _disc(start, 1.5 * ui, start_col)

    gpu.state.blend_set('NONE')
