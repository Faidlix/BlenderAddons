bl_info = {
    "name": "Blander Peferance",
    "author": "Faidlix",
    "version": (1, 1, 0),
    "blender": (5, 1, 0),
    "location": "Preferences and Topbar before Workspace Tabs",
    "description": "Keep UI defaults and toggle Traditional Chinese",
    "category": "System",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, StringProperty
from bpy.types import AddonPreferences, Operator

from .translations import TRANSLATIONS


ADDON_VERSION = (1, 1, 0)
PACKAGE_ID = "blander_peferance"
MODULE_ID = __package__ or __name__
TRANSLATION_DOMAIN = f"{__name__}.supplemental"
_ORIGINAL_DRAW_LEFT = None
_TRANSLATIONS_REGISTERED = False


def _save_preferences():
    if not bpy.context.preferences.use_preferences_save:
        return
    try:
        bpy.ops.wm.save_userpref()
    except (RuntimeError, AttributeError):
        pass


def disable_load_ui(*, save=False):
    """Disable loading a blend file's saved interface by default."""
    filepaths = bpy.context.preferences.filepaths
    changed = filepaths.use_load_ui
    if changed:
        filepaths.use_load_ui = False
    if changed and save:
        _save_preferences()
    return changed


@persistent
def keep_load_ui_disabled(_filepath):
    # A user may explicitly enable Load UI for one file. Restore the safe
    # default only after that file has loaded.
    disable_load_ui(save=True)


def _addon_preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(MODULE_ID)
    return addon.preferences if addon else None


def _tag_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def activate_traditional_chinese(preferences):
    view = bpy.context.preferences.view
    preferences.original_language = view.language
    preferences.original_interface = view.use_translate_interface
    preferences.original_tooltips = view.use_translate_tooltips
    preferences.original_reports = view.use_translate_reports
    preferences.original_new_data = view.use_translate_new_dataname

    view.language = "zh_HANT"
    view.use_translate_interface = True
    view.use_translate_tooltips = True
    view.use_translate_reports = True
    view.use_translate_new_dataname = True
    preferences.translation_active = True


def restore_original_language(preferences):
    view = bpy.context.preferences.view
    language = preferences.original_language
    enum_items = view.bl_rna.properties["language"].enum_items
    if language and language in enum_items:
        view.language = language
    view.use_translate_interface = preferences.original_interface
    view.use_translate_tooltips = preferences.original_tooltips
    view.use_translate_reports = preferences.original_reports
    view.use_translate_new_dataname = preferences.original_new_data
    preferences.translation_active = False


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


class BLANDERPEFERANCE_OT_toggle_translation(Operator):
    bl_idname = "blander_peferance.toggle_translation"
    bl_label = "切換繁體中文 / 原語系"
    bl_description = "第一次切換為繁體中文；再按一次恢復原本的語系設定"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        preferences = _addon_preferences(context)
        if preferences is None:
            self.report({'ERROR'}, "Blander Peferance preferences are unavailable")
            return {'CANCELLED'}

        if preferences.translation_active:
            restore_original_language(preferences)
            message = "已恢復原本的語系設定"
        else:
            activate_traditional_chinese(preferences)
            message = "已切換為繁體中文"

        _tag_redraw()
        _save_preferences()
        self.report({'INFO'}, message)
        return {'FINISHED'}


class BLANDERPEFERANCE_AP_preferences(AddonPreferences):
    bl_idname = MODULE_ID

    translation_active: BoolProperty(default=False, options={'HIDDEN'})
    original_language: StringProperty(default="en_US", options={'HIDDEN'})
    original_interface: BoolProperty(default=True, options={'HIDDEN'})
    original_tooltips: BoolProperty(default=True, options={'HIDDEN'})
    original_reports: BoolProperty(default=True, options={'HIDDEN'})
    original_new_data: BoolProperty(default=False, options={'HIDDEN'})

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

        layout.separator()
        row = layout.row()
        row.label(
            text="目前為繁體中文" if self.translation_active else "目前為原本語系",
            icon='WORLD',
        )
        layout.operator(
            BLANDERPEFERANCE_OT_toggle_translation.bl_idname,
            text="恢復原本語系" if self.translation_active else "切換為繁體中文",
            icon='WORLD',
            depress=self.translation_active,
        )
        layout.label(text="上方工作區分頁前也有相同的地球按鈕。")
        layout.label(text="未提供翻譯資料的第三方外掛，部分專有文字可能維持原文。", icon='INFO')


def _draw_translation_toggle(layout, context):
    preferences = _addon_preferences(context)
    active = bool(preferences and preferences.translation_active)
    row = layout.row(align=True)
    row.operator(
        BLANDERPEFERANCE_OT_toggle_translation.bl_idname,
        text="",
        icon='WORLD',
        depress=active,
    )


def _draw_left_with_translation(self, context):
    """Blender's standard left Topbar plus a button before workspace tabs."""
    from bl_ui.space_topbar import TOPBAR_MT_editor_menus

    layout = self.layout
    window = context.window
    screen = context.screen

    TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    layout.separator(type='LINE')
    _draw_translation_toggle(layout, context)

    if not screen.show_fullscreen:
        layout.template_ID_tabs(
            window,
            "workspace",
            new="workspace.add",
            menu="TOPBAR_MT_workspace_menu",
        )
    else:
        layout.operator(
            "screen.back_to_previous",
            icon='SCREEN_BACK',
            text="Back to Previous",
        )


CLASSES = (
    BLANDERPEFERANCE_OT_apply,
    BLANDERPEFERANCE_OT_toggle_translation,
    BLANDERPEFERANCE_AP_preferences,
)


def _install_topbar_button():
    global _ORIGINAL_DRAW_LEFT
    header = bpy.types.TOPBAR_HT_upper_bar
    if _ORIGINAL_DRAW_LEFT is None:
        _ORIGINAL_DRAW_LEFT = header.draw_left
    header.draw_left = _draw_left_with_translation


def _remove_topbar_button():
    global _ORIGINAL_DRAW_LEFT
    if _ORIGINAL_DRAW_LEFT is None:
        return
    header = bpy.types.TOPBAR_HT_upper_bar
    if header.draw_left is _draw_left_with_translation:
        header.draw_left = _ORIGINAL_DRAW_LEFT
    _ORIGINAL_DRAW_LEFT = None


def register():
    global _TRANSLATIONS_REGISTERED
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if keep_load_ui_disabled not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(keep_load_ui_disabled)

    try:
        bpy.app.translations.register(TRANSLATION_DOMAIN, TRANSLATIONS)
        _TRANSLATIONS_REGISTERED = True
    except ValueError:
        _TRANSLATIONS_REGISTERED = False

    _install_topbar_button()
    disable_load_ui(save=True)
    _tag_redraw()


def unregister():
    global _TRANSLATIONS_REGISTERED
    if keep_load_ui_disabled in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(keep_load_ui_disabled)
    _remove_topbar_button()

    if _TRANSLATIONS_REGISTERED:
        try:
            bpy.app.translations.unregister(TRANSLATION_DOMAIN)
        except ValueError:
            pass
        _TRANSLATIONS_REGISTERED = False

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _tag_redraw()
