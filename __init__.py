"""Show where a G/R/S transform started and how far it has moved, rotated or scaled."""

import time
import traceback

import bpy

from . import draw, prefs, session

POLL_INTERVAL = 0.05
# How long a hotkey capture waits for its transform to show up before it is dropped.
START_TIMEOUT = 0.5
KEYMAPS = ("Object Mode", "Mesh", "Pose")
HOTKEYS = ('G', 'R', 'S')
TOGGLE_KEY = 'T'

_session = None
_draw_handle = None
_keymap_items = []


def _tag_redraw(window):
    if window is None or window.screen is None:
        return
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def _watch_end():
    global _session
    current = _session
    if current is None:
        return None
    window = current.find_window(bpy.context.window_manager)
    if window is not None and session.running_transform(window) is not None:
        current.op_seen = True
        return POLL_INTERVAL
    if not current.op_seen and time.monotonic() - current.created < START_TIMEOUT:
        return POLL_INTERVAL
    _session = None
    _tag_redraw(window)
    return None


def _start(context):
    global _session
    try:
        _session = session.Session.capture(context)
    except Exception:
        traceback.print_exc()
        _session = session.Session(context.window)
    if not bpy.app.timers.is_registered(_watch_end):
        bpy.app.timers.register(_watch_end, first_interval=POLL_INTERVAL)


def _draw_callback():
    context = bpy.context
    window = context.window
    if window is None:
        return
    kind = session.running_transform(window)
    if kind is None:
        return
    p = prefs.get()
    if not p.enabled:
        return
    if _session is None:
        if not p.use_watcher or not prefs.mode_enabled(context):
            return
        _start(context)
    current = _session
    if current is None or current.failed or current.window_ptr != window.as_pointer():
        return
    try:
        ind = current.measure(context, kind)
        if ind is not None and prefs.kind_enabled(kind):
            draw.draw(context, ind, p)
    except Exception:
        current.failed = True
        traceback.print_exc()


class TRANSFORM_INDICATOR_OT_capture(bpy.types.Operator):
    """Record the start state of the transform this key starts, then pass the key on"""

    bl_idname = "transform_indicator.capture"
    bl_label = "Capture Transform Start"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        area = context.area
        return area is not None and area.type == 'VIEW_3D' and prefs.get().enabled and prefs.mode_enabled(context)

    def invoke(self, context, event):
        if prefs.get().use_hotkeys:
            _start(context)
        return {'PASS_THROUGH'}


class TRANSFORM_INDICATOR_OT_toggle(bpy.types.Operator):
    """Turn the transform indicator on or off"""

    bl_idname = "transform_indicator.toggle"
    bl_label = "Toggle Transform Indicator"

    def execute(self, context):
        p = prefs.get()
        p.enabled = not p.enabled
        self.report({'INFO'}, "Transform Indicator " + ("on" if p.enabled else "off"))
        return {'FINISHED'}


class VIEW3D_PT_transform_indicator(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_parent_id = 'VIEW3D_PT_overlay'
    bl_label = "Transform Indicator"

    def draw_header(self, context):
        self.layout.prop(prefs.get(), "enabled", text="")

    def draw(self, context):
        p = prefs.get()
        col = self.layout.column()
        col.active = p.enabled
        col.prop(p, "show_move")
        col.prop(p, "show_rotate")
        col.prop(p, "show_scale")


CLASSES = (
    prefs.TransformIndicatorPreferences,
    TRANSFORM_INDICATOR_OT_capture,
    TRANSFORM_INDICATOR_OT_toggle,
    VIEW3D_PT_transform_indicator,
)


def _register_keymaps():
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return
    for name in KEYMAPS:
        km = keyconfig.keymaps.new(name=name, space_type='EMPTY')
        for key in HOTKEYS:
            kmi = km.keymap_items.new(TRANSFORM_INDICATOR_OT_capture.bl_idname, key, 'PRESS')
            _keymap_items.append((km, kmi))
    km = keyconfig.keymaps.new(name="3D View", space_type='VIEW_3D')
    kmi = km.keymap_items.new(TRANSFORM_INDICATOR_OT_toggle.bl_idname, TOGGLE_KEY, 'PRESS', shift=True, alt=True)
    _keymap_items.append((km, kmi))


def register():
    global _draw_handle
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_keymaps()
    _draw_handle = bpy.types.SpaceView3D.draw_handler_add(_draw_callback, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handle, _session
    if bpy.app.timers.is_registered(_watch_end):
        bpy.app.timers.unregister(_watch_end)
    _session = None
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    for km, kmi in _keymap_items:
        km.keymap_items.remove(kmi)
    _keymap_items.clear()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
