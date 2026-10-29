import bpy
from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty, IntProperty

MODE_PROPS = {
    'OBJECT': "show_object",
    'EDIT_MESH': "show_edit_mesh",
    'POSE': "show_pose",
}
KIND_PROPS = {
    'TRANSLATE': "show_move",
    'ROTATE': "show_rotate",
    'RESIZE': "show_scale",
}


def get():
    return bpy.context.preferences.addons[__package__].preferences


def mode_enabled(context):
    name = MODE_PROPS.get(context.mode)
    return name is not None and getattr(get(), name)


def kind_enabled(kind):
    return getattr(get(), KIND_PROPS[kind])


class TransformIndicatorPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    enabled: BoolProperty(
        name="Transform Indicator",
        description="Show the transform indicator",
        default=True,
    )
    use_hotkeys: BoolProperty(
        name="Capture on G/R/S",
        description="Record the exact start state when G, R or S is pressed",
        default=True,
    )
    use_watcher: BoolProperty(
        name="Detect Other Transforms",
        description=(
            "Also show the indicator for transforms started from menus, tools or other keys. "
            "The start state is read on the first redrawn frame"
        ),
        default=True,
    )
    show_object: BoolProperty(name="Object Mode", default=True)
    show_edit_mesh: BoolProperty(name="Mesh Edit Mode", default=True)
    show_pose: BoolProperty(name="Pose Mode", default=True)
    show_move: BoolProperty(name="Move", description="Show the indicator while moving", default=True)
    show_rotate: BoolProperty(name="Rotate", description="Show the indicator while rotating", default=True)
    show_scale: BoolProperty(name="Scale", description="Show the indicator while scaling", default=True)
    show_values: BoolProperty(
        name="Show Values",
        description="Label the indicator with the distance, angle or scale factor, in scene units",
        default=True,
    )
    start_color: FloatVectorProperty(
        name="Start",
        subtype='COLOR_GAMMA',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 0.9),
    )
    delta_color: FloatVectorProperty(
        name="Delta",
        subtype='COLOR_GAMMA',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.65, 0.15, 0.9),
    )
    line_width: FloatProperty(name="Line Width", default=1.5, min=1.0, max=6.0)
    radius: IntProperty(
        name="Radius",
        description="Size of the rotation arc and scale rings, in pixels",
        default=40,
        min=10,
        max=200,
        subtype='PIXEL',
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True

        col = layout.column(heading="Start State")
        col.prop(self, "use_hotkeys")
        col.prop(self, "use_watcher")

        col = layout.column(heading="Show In")
        col.prop(self, "show_object")
        col.prop(self, "show_edit_mesh")
        col.prop(self, "show_pose")

        col = layout.column()
        col.prop(self, "show_values")
        col.prop(self, "start_color")
        col.prop(self, "delta_color")
        col.prop(self, "line_width")
        col.prop(self, "radius")
