bl_info = {
    "name": "Faidlix Manager",
    "author": "Faidlix",
    "version": (1, 1, 3),
    "blender": (5, 2, 0),
    "location": "3D View > Sidebar > Faidlix",
    "description": "Update installed Faidlix extensions together",
    "category": "System",
}

import json
import os
import tomllib

import addon_utils
import bpy
from bpy.types import Operator, Panel


ADDON_VERSION = (1, 1, 3)
PACKAGE_ID = "faidlix_manager"
REGISTRY_FILENAME = "addon_registry.json"
REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
STATE_KEY = "_faidlix_manager_update_state"


def _version(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, TypeError, ValueError):
        return ()


def _repository(context):
    for index, repo in enumerate(context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


def _ensure_repository(context):
    index, repo = _repository(context)
    if repo is not None:
        repo.enabled = True
        repo.use_sync_on_startup = True
        return index, repo
    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Blender Add-ons",
        remote_url=REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    return _repository(context) if result == {'FINISHED'} else (None, None)


def _repository_index(repo):
    path = os.path.join(repo.directory, ".blender_ext", "index.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"data": []}


def _installed_version(package_dir):
    path = os.path.join(package_dir, "blender_manifest.toml")
    try:
        with open(path, "rb") as handle:
            return _version(tomllib.load(handle).get("version"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()


def _addon_registry():
    path = os.path.join(os.path.dirname(__file__), REGISTRY_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if data.get("schema_version") != 1:
        return {}
    return {
        item["package_id"]: item
        for item in data.get("addons", [])
        if isinstance(item, dict) and item.get("package_id")
    }


def _supports_common_feature(item, feature):
    return feature in item.get("common_features", [])


def _outdated_packages(repo):
    result = []
    registry = _addon_registry()
    for item in _repository_index(repo).get("data", []):
        package_id = item.get("id", "")
        latest = _version(item.get("version"))
        package_dir = os.path.join(repo.directory, package_id)
        registration = registry.get(package_id, {})
        if (
            not package_id
            or not _supports_common_feature(registration, "update_all")
            or not os.path.isdir(package_dir)
        ):
            continue
        current = _installed_version(package_dir)
        if current and latest > current:
            module_name = f"bl_ext.{repo.module}.{package_id}"
            enabled = addon_utils.check(module_name)[1]
            result.append((package_id, latest, enabled, registration.get("update_order", 100)))
    result.sort(key=lambda item: (item[0] == PACKAGE_ID, item[3], item[0]))
    return result


def _state():
    return bpy.app.driver_namespace.setdefault(
        STATE_KEY,
        {"running": False, "done": 0, "total": 0, "errors": 0, "message": ""},
    )


def _installed_package_count(repo):
    registry = _addon_registry()
    return sum(
        1
        for item in _repository_index(repo).get("data", [])
        if (
            item.get("id")
            and _supports_common_feature(registry.get(item["id"], {}), "update_all")
            and os.path.isdir(os.path.join(repo.directory, item["id"]))
        )
    )


def _reset_completion_state():
    state = _state()
    if state["running"]:
        return None
    state.update(done=0, total=0, errors=0, message="")
    _redraw()
    return None


def _finish_update(state):
    state["running"] = False
    state["message"] = (
        "全部更新完成"
        if not state["errors"]
        else f"更新完成（{state['errors']} 個失敗）"
    )
    bpy.ops.wm.save_userpref()
    _redraw()
    bpy.app.timers.register(_reset_completion_state, first_interval=1.0)


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


class FAIDLIXMANAGER_OT_update_all(Operator):
    bl_idname = "faidlix_manager.update_all"
    bl_label = "全部更新"
    bl_description = "同步共用來源，並更新所有已安裝的 Faidlix 外掛"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return not _state()["running"]

    def execute(self, context):
        context.preferences.system.use_online_access = True
        repo_index, repo = _ensure_repository(context)
        if repo is None:
            self.report({'ERROR'}, "無法建立 Faidlix Blender Add-ons 更新來源")
            return {'CANCELLED'}
        try:
            if bpy.ops.extensions.repo_sync(repo_index=repo_index) != {'FINISHED'}:
                raise RuntimeError("同步未完成")
        except RuntimeError as exc:
            self.report({'ERROR'}, f"同步失敗：{exc}")
            return {'CANCELLED'}

        items = _outdated_packages(repo)
        if not items:
            bpy.ops.wm.save_userpref()
            state = _state()
            state.update(
                running=False,
                done=0,
                total=0,
                errors=0,
                message="全部更新完成",
            )
            _redraw()
            bpy.app.timers.register(_reset_completion_state, first_interval=1.0)
            self.report({'INFO'}, "已安裝的 Faidlix 外掛都是最新版")
            return {'FINISHED'}

        state = _state()
        state.update(running=True, done=0, total=len(items), errors=0, message="")

        def update_next():
            if not items:
                _finish_update(state)
                return None
            package_id, latest, enabled, _update_order = items.pop(0)
            if package_id == PACKAGE_ID:
                # The manager is intentionally last. Finish every UI/state
                # write before replacing this package, then return without
                # touching any class or RNA owned by the old module.
                state["done"] += 1
                state["message"] = "全部更新完成"
                state["running"] = False
                bpy.ops.wm.save_userpref()
                _redraw()
                bpy.app.timers.register(_reset_completion_state, first_interval=1.0)
                bpy.ops.extensions.package_install(
                    repo_index=repo_index,
                    pkg_id=package_id,
                    enable_on_install=enabled,
                )
                return None
            try:
                result = bpy.ops.extensions.package_install(
                    repo_index=repo_index,
                    pkg_id=package_id,
                    enable_on_install=enabled,
                )
                if result != {'FINISHED'}:
                    raise RuntimeError(str(result))
                state["message"] = f"{package_id} {'.'.join(map(str, latest))}"
            except Exception as exc:
                state["errors"] += 1
                state["message"] = f"{package_id}: {exc}"
                print(f"Faidlix Manager update failed: {package_id}: {exc}")
            state["done"] += 1
            _redraw()
            return 0.5

        bpy.app.timers.register(update_next, first_interval=0.1)
        self.report({'INFO'}, f"開始更新 {len(items)} 個 Faidlix 外掛")
        return {'FINISHED'}


class FAIDLIXMANAGER_PT_update_all(Panel):
    bl_label = "Faidlix Manager"
    bl_idname = "FAIDLIXMANAGER_PT_update_all"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Faidlix"
    bl_order = -100
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header_preset(self, _context):
        row = self.layout.row(align=True)
        row.alignment = 'RIGHT'
        row.label(text=f"v{'.'.join(map(str, ADDON_VERSION))}")

    @classmethod
    def poll(cls, context):
        _index, repo = _repository(context)
        return repo is not None and _installed_package_count(repo) >= 2

    def draw(self, _context):
        state = _state()
        layout = self.layout
        row = layout.row()
        row.enabled = not state["running"]
        if state["running"]:
            text = f"全部更新（{state['done']}/{state['total']}）"
        elif state["message"]:
            text = state["message"]
        else:
            text = "全部更新"
        row.operator(FAIDLIXMANAGER_OT_update_all.bl_idname, text=text, icon='FILE_REFRESH')


CLASSES = (FAIDLIXMANAGER_OT_update_all, FAIDLIXMANAGER_PT_update_all)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
