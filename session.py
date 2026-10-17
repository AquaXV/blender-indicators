"""Start-state capture and per-frame measurement of a running transform.

The running operator tells which mode is active (it changes when G/R/S is pressed
mid-transform, and Blender restores the selection first). The amount is measured
from how the selection moved since the start.
"""

import math
import time
from dataclasses import dataclass

import bmesh
import numpy as np
from mathutils import Matrix, Vector

TRANSFORM_OPS = {
    "TRANSFORM_OT_translate": 'TRANSLATE',
    "TRANSFORM_OT_rotate": 'ROTATE',
    "TRANSFORM_OT_trackball": 'ROTATE',
    "TRANSFORM_OT_resize": 'RESIZE',
    "transform.translate": 'TRANSLATE',
    "transform.rotate": 'ROTATE',
    "transform.trackball": 'ROTATE',
    "transform.resize": 'RESIZE',
}
MAX_SAMPLES = 32
ANGLE_EPS = 1e-4
RATIO_EPS = 1e-4


def running_transform(window):
    """Return 'TRANSLATE', 'ROTATE' or 'RESIZE' while such a transform is modal in window."""
    for op in window.modal_operators:
        kind = TRANSFORM_OPS.get(op.bl_idname)
        if kind is not None:
            return kind
    return None


def _wrap(angle):
    return (angle + math.pi) % math.tau - math.pi


@dataclass
class Indicator:
    start: Vector
    pivot: Vector
    anchor: Vector
    translation: Vector = None
    # (axis, signed angle, start direction or None for view based).
    rotation: tuple = None
    scale: float = None


class _Elements:
    """Selected elements of one mode. read(depsgraph, i) returns a world matrix or position."""

    def __init__(self, start, read, has_matrices, tracked=None, active_position=None):
        self.start = start
        self.read = read
        self.has_matrices = has_matrices
        self.tracked = tracked
        self.active_position = active_position

    def positions(self, values):
        return [m.translation for m in values] if self.has_matrices else values


def _object_elements(context, depsgraph):
    objects = list(context.selected_objects)

    def read(depsgraph, i):
        return objects[i].evaluated_get(depsgraph).matrix_world.copy()

    start = [read(depsgraph, i) for i in range(len(objects))]
    active = context.active_object
    tracked = objects.index(active) if active in objects else None
    active_position = start[tracked].translation.copy() if tracked is not None else None
    return _Elements(start, read, True, tracked, active_position)


def _pose_elements(context, depsgraph):
    bones = [(pb.id_data, pb.name) for pb in context.selected_pose_bones or ()]

    def read(depsgraph, i):
        ob, name = bones[i]
        ob_eval = ob.evaluated_get(depsgraph)
        return ob_eval.matrix_world @ ob_eval.pose.bones[name].matrix

    start = [read(depsgraph, i) for i in range(len(bones))]
    active = context.active_pose_bone
    key = (active.id_data, active.name) if active is not None else None
    tracked = bones.index(key) if key in bones else None
    active_position = start[tracked].translation.copy() if tracked is not None else None
    return _Elements(start, read, True, tracked, active_position)


def _mesh_elements(context, depsgraph):
    # BMVert references stay valid for the whole transform; a ReferenceError ends the session.
    verts = []
    start = []
    for ob in context.objects_in_mode_unique_data:
        if ob.type != 'MESH':
            continue
        matrix = ob.matrix_world.copy()
        for v in bmesh.from_edit_mesh(ob.data).verts:
            if v.select:
                verts.append((matrix, v))
                start.append(matrix @ v.co)

    def read(depsgraph, i):
        matrix, v = verts[i]
        return matrix @ v.co

    active_position = None
    ob = context.edit_object
    if ob is not None and ob.type == 'MESH':
        elem = bmesh.from_edit_mesh(ob.data).select_history.active
        if isinstance(elem, bmesh.types.BMVert):
            active_position = ob.matrix_world @ elem.co
        elif isinstance(elem, bmesh.types.BMEdge):
            active_position = ob.matrix_world @ ((elem.verts[0].co + elem.verts[1].co) / 2)
        elif isinstance(elem, bmesh.types.BMFace):
            active_position = ob.matrix_world @ elem.calc_center_median()
    return _Elements(start, read, False, None, active_position)


ELEMENT_READERS = {
    'OBJECT': _object_elements,
    'EDIT_MESH': _mesh_elements,
    'POSE': _pose_elements,
}


def _median(positions):
    return sum(positions, Vector()) / len(positions)


def _pivot(context, positions, active_position):
    pivot = context.scene.tool_settings.transform_pivot_point
    if pivot == 'CURSOR':
        return context.scene.cursor.location.copy()
    if pivot == 'ACTIVE_ELEMENT' and active_position is not None:
        return active_position.copy()
    if pivot == 'BOUNDING_BOX_CENTER':
        lo = Vector(map(min, zip(*positions)))
        hi = Vector(map(max, zip(*positions)))
        return (lo + hi) / 2
    return _median(positions)


def _pick_samples(positions, pivot, tracked):
    """Farthest element from the pivot first, then the tracked one, then an even spread."""
    farthest = max(range(len(positions)), key=lambda i: (positions[i] - pivot).length_squared)
    picks = [farthest]
    if tracked is not None and tracked != farthest:
        picks.append(tracked)
    step = max(1, len(positions) // MAX_SAMPLES)
    for i in range(0, len(positions), step):
        if len(picks) >= MAX_SAMPLES:
            break
        if i not in picks:
            picks.append(i)
    return picks


def _span(x):
    """Orthonormal rows spanning the rows of x."""
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    if s[0] < 1e-9:
        return vt[:0]
    return vt[s > 1e-6 * s[0]]


def _rotation_fit(x, y):
    """Linear map taking rows of x to rows of y, completed as a rotation where x spans no direction."""
    basis = _span(x)
    if len(basis) == 0:
        return None
    linear = np.linalg.lstsq(x, y, rcond=None)[0].T
    images = [linear @ b for b in basis]
    if len(basis) == 1:
        return Vector(basis[0]).rotation_difference(Vector(images[0])).to_matrix() * np.linalg.norm(images[0])
    if len(basis) == 2:
        normal = np.cross(images[0], images[1])
        length = np.linalg.norm(normal)
        if length < 1e-12:
            return None
        images.append(normal / math.sqrt(length))
        basis = np.vstack([basis, np.cross(basis[0], basis[1])])
    return Matrix((np.column_stack(images) @ basis).tolist())


def _scale_fit(x, y):
    """Linear map taking rows of x to rows of y, identity where x spans no direction."""
    if len(_span(x)) == 0:
        return None
    return Matrix((np.eye(3) + np.linalg.lstsq(x, y - x, rcond=None)[0].T).tolist())


ODD_FLIPS = ((1, 1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, -1), (-1, -1, -1))
ALL_FLIPS = ODD_FLIPS + ((-1, -1, 1), (-1, 1, -1), (1, -1, -1))


def _polar(linear, prefer_scale):
    """Split a linear map into a proper rotation and signed scales; a mirror becomes a negative scale.

    A 180 degree turn and a two-axis mirror look the same; prefer_scale reads it as the mirror.
    """
    u, s, vt = np.linalg.svd(np.array(linear))
    best = None
    for flips in ALL_FLIPS if prefer_scale else ODD_FLIPS:
        rotation = u @ np.diag(flips) @ vt
        if np.linalg.det(rotation) > 0 and (best is None or np.trace(rotation) > np.trace(best[0])):
            best = rotation, flips
    rotation, flips = best
    return Matrix(rotation.tolist()), [float(a * b) for a, b in zip(s, flips)]


def _dominant(scales):
    """A negative (mirroring) scale if any, otherwise the one that differs most from 1."""
    return max(scales, key=lambda r: (r < 0, abs(math.log(abs(r))) if abs(r) > 1e-9 else math.inf))


class Session:
    def __init__(self, window, elements=None, pivot=None, anchor=None):
        self.window_ptr = window.as_pointer()
        self.elements = elements
        self.pivot = pivot
        self.anchor = anchor
        self.created = time.monotonic()
        self.op_seen = False
        self.failed = elements is None
        self.kind = None
        self.ref_axis = None
        self.angle = 0.0
        if elements is not None:
            positions = elements.positions(elements.start)
            self.samples = _pick_samples(positions, pivot, elements.tracked)
            self.start = [elements.start[i] for i in self.samples]
            self.tracked_slot = self.samples.index(elements.tracked) if elements.tracked is not None else 0

    @classmethod
    def capture(cls, context):
        """Record the selection before (or at the first frame of) a transform.

        Returns an inert session when there is nothing to track, so the watcher
        does not retry on every redraw.
        """
        reader = ELEMENT_READERS.get(context.mode)
        elements = reader(context, context.evaluated_depsgraph_get()) if reader is not None else None
        if elements is None or not elements.start:
            return cls(context.window)
        positions = elements.positions(elements.start)
        pivot = _pivot(context, positions, elements.active_position)
        # Translation is drawn from the selection, not from a pivot outside it.
        pivot_type = context.scene.tool_settings.transform_pivot_point
        anchor = _median(positions) if pivot_type in {'CURSOR', 'INDIVIDUAL_ORIGINS'} else pivot
        return cls(context.window, elements, pivot, anchor)

    def find_window(self, window_manager):
        for window in window_manager.windows:
            if window.as_pointer() == self.window_ptr:
                return window
        return None

    def _update_angle(self, axis, angle):
        """Accumulate a signed angle so turns past 180 degrees keep growing.

        The axis follows the measurement every frame (trackball rotation drifts);
        the previous axis only keeps its sign continuous.
        """
        if axis is None or abs(angle) < ANGLE_EPS:
            self.angle = round(self.angle / math.tau) * math.tau
            return
        axis = axis.normalized()
        if self.ref_axis is not None and axis.dot(self.ref_axis) < 0.0:
            axis, angle = -axis, -angle
        self.ref_axis = axis
        self.angle += _wrap(angle - _wrap(self.angle))

    def _rotation(self, direction):
        if abs(self.angle) <= ANGLE_EPS:
            return None
        axis = self.ref_axis
        if direction is not None:
            direction = direction - axis * direction.dot(axis)
            direction = direction.normalized() if direction.length > 1e-9 else None
        return axis, self.angle, direction

    def _linear_delta(self, kind, p0, p1, current):
        if self.elements.has_matrices:
            m0 = self.start[self.tracked_slot].to_3x3()
            m1 = current[self.tracked_slot].to_3x3()
            if abs(m0.determinant()) < 1e-12:
                return None
            return m1 @ m0.inverted()
        x = np.array(p0)
        y = np.array(p1)
        pivot = np.array(self.pivot)
        if kind == 'RESIZE':
            return _scale_fit(x - pivot, y - pivot)
        # Centered on the samples so rotation about individual origins also fits.
        linear = _rotation_fit(x - x.mean(axis=0), y - y.mean(axis=0))
        if linear is None:
            linear = _rotation_fit(x - pivot, y - pivot)
        return linear

    def measure(self, context, kind):
        if self.failed:
            return None
        if kind != self.kind:
            # Switching mode restores the selection, so measuring restarts.
            self.kind = kind
            self.ref_axis = None
            self.angle = 0.0
        elements = self.elements
        depsgraph = context.evaluated_depsgraph_get()
        current = [elements.read(depsgraph, i) for i in self.samples]
        p0 = elements.positions(self.start)
        p1 = elements.positions(current)
        ind = Indicator(start=self.pivot, pivot=self.pivot, anchor=self.anchor)

        if kind == 'TRANSLATE':
            ind.start = self.anchor
            delta = p1[self.tracked_slot] - p0[self.tracked_slot]
            if delta.length > 1e-6:
                ind.translation = delta
            return ind

        linear = self._linear_delta(kind, p0, p1, current)
        if linear is None:
            return ind
        rotation, scales = _polar(linear, prefer_scale=kind == 'RESIZE')
        if kind == 'ROTATE':
            axis, angle = rotation.to_quaternion().to_axis_angle()
            if angle > math.pi:
                angle -= math.tau
            self._update_angle(axis, angle)
            ind.rotation = self._rotation(None if elements.has_matrices else p0[0] - self.pivot)
        else:
            ratio = _dominant(scales)
            if abs(ratio - 1.0) > RATIO_EPS:
                ind.scale = ratio
        return ind
