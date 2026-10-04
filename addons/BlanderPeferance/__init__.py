bl_info = {
    "name": "Blander Peferance",
    "author": "Faidlix",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "Preferences > Add-ons > Blander Peferance",
    "description": "Keep the current Blender UI when opening blend files",
    "category": "System",
}

import bpy
from bpy.app.handlers import persistent
from bpy.types import AddonPreferences, Operator


ADDON_VERSION = (1, 0, 0)
PACKAGE_ID = "blander_peferance"
MODULE_ID = __package__ or __name__


def disable_load_ui(*, save=False):
    """Disable loading a blend file's saved interface by default."""
    filepaths = bpy.context.preferences.filepaths
    changed = filepaths.use_load_ui
    if changed:
        filepaths.use_load_ui = False
    if changed and save:
        bpy.ops.wm.save_userpref()
    return changed


@persistent
def keep_load_ui_disabled(_filepath):
    # A user may still explicitly enable Load UI for the file being opened.
    # After that file has loaded, restore the safe default for the next open.
    disable_load_ui(save=True)


class BLANDERPEFERANCE_OT_apply(Operator):
    bl_idname = "blander_peferance.apply"
    bl_label = "套用：預設不讀取 UI"
    bl_description = "開啟 blend 檔案時保留目前介面；仍可在檔案視窗手動勾選讀取 UI"
    bl_options = {'INTERNAL'}

    def execute(self, _context):
        changed = disable_load_ui(save=True)
        message = "已關閉預設讀取 UI" if changed else "預設讀取 UI 已是關閉狀態"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class BLANDERPEFERANCE_AP_preferences(AddonPreferences):
    bl_idname = MODULE_ID

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        enabled = not context.preferences.filepaths.use_load_ui
        row = layout.row()
        row.label(
            text="預設不讀取檔案 UI" if enabled else "目前會讀取檔案 UI",
            icon='CHECKMARK' if enabled else 'ERROR',
        )
        layout.operator(BLANDERPEFERANCE_OT_apply.bl_idname, icon='PREFERENCES')
        layout.label(text="需要時仍可在開啟檔案視窗手動勾選「讀取 UI」。")


CLASSES = (
    BLANDERPEFERANCE_OT_apply,
    BLANDERPEFERANCE_AP_preferences,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if keep_load_ui_disabled not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(keep_load_ui_disabled)
    disable_load_ui(save=True)


def unregister():
    if keep_load_ui_disabled in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(keep_load_ui_disabled)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
