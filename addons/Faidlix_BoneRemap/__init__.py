import bpy
from bpy.app.handlers import persistent
from bpy.props import PointerProperty

from . import model, operators, ui, updater


bl_info = {
    "name": "Faidlix Bone Remap",
    "author": "Faidlix",
    "version": (0, 6, 5),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > Faidlix",
    "description": "Batch import and retarget armature actions",
    "category": "Animation",
}


_SYNC_GUARD = False


@persistent
def _sync_active_armature(_scene=None, _depsgraph=None):
    global _SYNC_GUARD
    if _SYNC_GUARD:
        return
    context = bpy.context
    scene = getattr(context, "scene", None)
    view_layer = getattr(context, "view_layer", None)
    if not scene or not view_layer or not hasattr(scene, "fbr_settings"):
        return
    active = view_layer.objects.active
    if (
        not active
        or active.type != "ARMATURE"
        or active.get("_fbr_temp_source", False)
    ):
        return
    settings = scene.fbr_settings
    if settings.target_armature == active.name:
        return
    try:
        _SYNC_GUARD = True
        settings.target_armature = active.name
    finally:
        _SYNC_GUARD = False


CLASSES = model.CLASSES + operators.CLASSES + updater.CLASSES + ui.CLASSES


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fbr_settings = PointerProperty(type=model.FBR_Settings)
    if _sync_active_armature not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_sync_active_armature)
    _sync_active_armature()


def unregister():
    operators.stop_animation_preview(bpy.context)
    if _sync_active_armature in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_active_armature)
    if hasattr(bpy.types.Scene, "fbr_settings"):
        del bpy.types.Scene.fbr_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
