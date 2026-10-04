import importlib.util
import pathlib
import sys
from types import SimpleNamespace

import bpy


root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "blander_peferance",
    root / "__init__.py",
    submodule_search_locations=[str(root)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (1, 1, 0)
assert addon.PACKAGE_ID == "blander_peferance"

bpy.context.preferences.use_preferences_save = False
bpy.context.preferences.filepaths.use_load_ui = True
original_draw = bpy.types.TOPBAR_HT_upper_bar.draw_left
addon.register()
assert bpy.context.preferences.filepaths.use_load_ui is False
assert addon.keep_load_ui_disabled in bpy.app.handlers.load_post
assert hasattr(bpy.ops.blander_peferance, "apply")
assert hasattr(bpy.ops.blander_peferance, "toggle_translation")
assert bpy.types.TOPBAR_HT_upper_bar.draw_left is addon._draw_left_with_translation

view = bpy.context.preferences.view
view.language = "en_US"
view.use_translate_interface = False
view.use_translate_tooltips = False
view.use_translate_reports = False
view.use_translate_new_dataname = False
translation_preferences = SimpleNamespace(
    translation_active=False,
    original_language="",
    original_interface=True,
    original_tooltips=True,
    original_reports=True,
    original_new_data=True,
)
addon.activate_traditional_chinese(translation_preferences)
assert translation_preferences.translation_active is True
assert view.language == "zh_HANT"
assert view.use_translate_interface is True
assert view.use_translate_tooltips is True
assert view.use_translate_reports is True
assert view.use_translate_new_dataname is True
assert bpy.app.translations.pgettext_iface("Add Armature") == "新增骨架"

addon.restore_original_language(translation_preferences)
assert translation_preferences.translation_active is False
assert view.language == "en_US"
assert view.use_translate_interface is False
assert view.use_translate_tooltips is False
assert view.use_translate_reports is False
assert view.use_translate_new_dataname is False

bpy.context.preferences.filepaths.use_load_ui = True
addon.keep_load_ui_disabled("")
assert bpy.context.preferences.filepaths.use_load_ui is False

addon.unregister()
assert addon.keep_load_ui_disabled not in bpy.app.handlers.load_post
assert bpy.types.TOPBAR_HT_upper_bar.draw_left is original_draw
print("BLANDER_PEFERANCE_HEADLESS_OK")
