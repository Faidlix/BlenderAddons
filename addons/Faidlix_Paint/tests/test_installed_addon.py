import addon_utils
import bpy


URL = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
repo = next(repo for repo in bpy.context.preferences.extensions.repos
            if repo.remote_url.rstrip("/") == URL.rstrip("/"))
module_name = f"bl_ext.{repo.module}.faidlix_paint"
_default, enabled = addon_utils.check(module_name)
assert enabled, module_name
addon = __import__(module_name, fromlist=['*'])
assert addon.ADDON_VERSION == (0, 4, 8)
assert addon.PACKAGE_ID == "faidlix_paint"
assert addon.GITHUB_REPOSITORY_URL == URL
assert hasattr(bpy.ops.faidlix_paint, "online_update")
assert hasattr(bpy.ops.faidlix_paint, "mask_edit")
assert hasattr(bpy.ops.faidlix_paint, "mask_to_image")

from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
toolbar = ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')
assert toolbar._tools['PAINT_TEXTURE'][0].idname == "faidlix_paint.update_view3d"
assert toolbar._tools['PAINT_TEXTURE'][1] is None

assert bpy.ops.faidlix_paint.online_update() == {'FINISHED'}
print("FAIDLIX_PAINT_INSTALLED_TEST=PASS")
print(f"INSTALLED_MODULE={module_name}")
