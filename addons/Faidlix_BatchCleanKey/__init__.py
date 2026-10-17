"""Action Editor extension. Enable in Blender; open the Faidlix sidebar."""
from . import core, ui, compose, compose_ui, adjust, adjust_ui, rotation_align, pose_hold

ADDON_VERSION = '1.8.3'
bl_info = {'name': 'Action Editor', 'author': 'Faidlix',
           'version': (1, 8, 3), 'blender': (5, 2, 0), 'category': 'Animation'}

populate = ui.populate
BCK_OT_Select = ui.BCK_OT_Select
BCK_OT_Batch = ui.BCK_OT_Batch
BCK_PT_View3D = ui.BCK_PT_View3D
BCK_PT_DopeSheet = ui.BCK_PT_DopeSheet
BCK_PT_Graph = ui.BCK_PT_Graph


def register():
    compose_ui.register()
    ui.register()
    adjust_ui.register()
    rotation_align.register()
    pose_hold.register()


def unregister():
    pose_hold.unregister()
    rotation_align.unregister()
    adjust_ui.unregister()
    compose_ui.unregister()
    ui.unregister()
