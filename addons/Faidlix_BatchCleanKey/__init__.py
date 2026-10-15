"""Action Editor extension. Enable in Blender; open the Faidlix sidebar."""
from . import core, ui, compose, compose_ui, adjust, adjust_ui

ADDON_VERSION = '1.7.2'
bl_info = {'name': 'Action Editor', 'author': 'Faidlix',
           'version': (1, 7, 2), 'blender': (5, 2, 0), 'category': 'Animation'}

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


def unregister():
    adjust_ui.unregister()
    compose_ui.unregister()
    ui.unregister()
