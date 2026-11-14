"""Smoke-test a BakeMap ZIP installed in an isolated Blender profile.

Run after `extension install-file -r user_default -e <zip>` with the same
BLENDER_USER_RESOURCES value. The extension must already be enabled.
"""

import importlib

import addon_utils
import bpy


MODULE = "bl_ext.user_default.faidlix_bakemap"
_default, enabled = addon_utils.check(MODULE)
assert enabled, MODULE
addon = importlib.import_module(MODULE)
assert addon.ADDON_VERSION == (2, 3, 30)
assert hasattr(bpy.types.Scene, "faidlix_bakemap")
assert hasattr(bpy.types, "FAIDLIX_OT_uv_merge_self_to_nearest")
assert hasattr(bpy.types, "FAIDLIX_OT_uv_merge_island_to_nearest")
assert hasattr(bpy.types, "FAIDLIX_MT_uv_merge_to_nearest")
assert addon._UV_COUNTERPART_DRAW_HANDLE is not None
assert bpy.context.scene.faidlix_bakemap.show_uv_counterparts
print("FAIDLIX_BAKEMAP_LOCAL_PACKAGE_TEST=PASS")
