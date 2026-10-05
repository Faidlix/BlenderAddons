import importlib
import json
import os
import sys
import time
import tomllib

import bpy
from bpy.types import Operator


PACKAGE_ID = "faidlix_bone_remap"
ADDON_VERSION = (0, 6, 7)
GITHUB_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
)


def _base_url(url):
    return str(url).split("?", 1)[0].rstrip("/")


def _fresh_url():
    return f"{GITHUB_REPOSITORY_URL}?cache={int(time.time())}"


def _find_repo(context):
    for index, repo in enumerate(context.preferences.extensions.repos):
        if _base_url(repo.remote_url) == _base_url(GITHUB_REPOSITORY_URL):
            return index, repo
    return None, None


def _ensure_repo(context):
    index, repo = _find_repo(context)
    if repo:
        repo.enabled = True
        repo.use_sync_on_startup = True
        repo.remote_url = _fresh_url()
        return index, repo
    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Blender Add-ons",
        remote_url=_fresh_url(),
        use_sync_on_startup=True,
        type="REMOTE",
    )
    if result != {"FINISHED"}:
        return None, None
    return _find_repo(context)


def _version_tuple(value):
    try:
        values = tuple(int(part) for part in str(value).split("."))
    except (TypeError, ValueError):
        return ()
    return (values + (0, 0, 0))[:3]


def _remote_version(repo):
    index_path = os.path.join(repo.directory, ".blender_ext", "index.json")
    with open(index_path, "r", encoding="utf8") as handle:
        payload = json.load(handle)
    versions = [
        _version_tuple(item.get("version"))
        for item in payload.get("data", ())
        if item.get("id") == PACKAGE_ID
    ]
    version = max((item for item in versions if item), default=())
    if not version:
        raise RuntimeError("GitHub 倉庫沒有 Faidlix Bone Remap 套件")
    return version


def _set_status(context, message, clear_after=None):
    settings = getattr(context.scene, "fbr_settings", None)
    if settings:
        settings.update_status = message
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    if clear_after:
        scene_name = context.scene.name
        expected = message

        def clear_status():
            scene = bpy.data.scenes.get(scene_name)
            current = getattr(scene, "fbr_settings", None) if scene else None
            if current and current.update_status == expected:
                current.update_status = ""
            return None

        bpy.app.timers.register(clear_status, first_interval=clear_after)


def _installed_version(repo_directory):
    manifest_path = os.path.join(repo_directory, PACKAGE_ID, "blender_manifest.toml")
    if not os.path.isfile(manifest_path):
        return ()
    with open(manifest_path, "rb") as handle:
        return _version_tuple(tomllib.load(handle).get("version"))


def _schedule_reload(module_name, expected_version, repo_directory, scene_name):
    started = time.monotonic()

    def reload_addon():
        if _installed_version(repo_directory) < expected_version:
            if time.monotonic() - started < 60.0:
                return 0.5
            scene = bpy.data.scenes.get(scene_name)
            settings = getattr(scene, "fbr_settings", None) if scene else None
            if settings:
                settings.update_status = "更新失敗：安裝逾時"
            return None
        module = sys.modules.get(module_name)
        if not module:
            return None
        try:
            module.unregister()
            importlib.invalidate_caches()
            module = importlib.reload(module)
            module.register()
            scene = bpy.data.scenes.get(scene_name)
            settings = getattr(scene, "fbr_settings", None) if scene else None
            if settings:
                settings.update_status = "更新完成，已套用最新版"
                expected = settings.update_status

                def clear_status():
                    current_scene = bpy.data.scenes.get(scene_name)
                    current = (
                        getattr(current_scene, "fbr_settings", None)
                        if current_scene
                        else None
                    )
                    if current and current.update_status == expected:
                        current.update_status = ""
                    return None

                bpy.app.timers.register(clear_status, first_interval=4.0)
        except Exception as exc:
            scene = bpy.data.scenes.get(scene_name)
            settings = getattr(scene, "fbr_settings", None) if scene else None
            if settings:
                settings.update_status = f"已安裝，但重新載入失敗：{exc}"
        return None

    bpy.app.timers.register(reload_addon, first_interval=1.0)


class FBR_OT_online_update(Operator):
    bl_idname = "fbr.online_update"
    bl_label = "線上更新"
    bl_description = "從 Faidlix/BlanderBoneRemap GitHub main 檢查並安裝較新版本"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "fbr_settings", None)
        return bool(settings and not settings.update_status)

    def execute(self, context):
        if not getattr(bpy.app, "online_access", False):
            _set_status(context, "請先開啟 Allow Online Access", clear_after=4.0)
            self.report({"ERROR"}, "請先在 Preferences > System 開啟 Allow Online Access")
            return {"CANCELLED"}
        _set_status(context, "正在檢查更新…")
        index, repo = _ensure_repo(context)
        if repo is None:
            _set_status(context, "更新失敗：無法建立 GitHub 倉庫", clear_after=4.0)
            return {"CANCELLED"}
        try:
            if bpy.ops.extensions.repo_sync(repo_index=index) != {"FINISHED"}:
                raise RuntimeError("倉庫同步未完成")
            remote = _remote_version(repo)
        except Exception as exc:
            _set_status(context, f"更新失敗：{exc}", clear_after=5.0)
            return {"CANCELLED"}
        if remote <= ADDON_VERSION:
            _set_status(context, "已是最新版本", clear_after=3.0)
            self.report({"INFO"}, "Faidlix Bone Remap 已是最新版本")
            return {"FINISHED"}
        if bpy.app.background:
            _set_status(context, "背景模式無法安裝更新", clear_after=4.0)
            return {"CANCELLED"}
        _set_status(context, f"正在安裝 {'.'.join(map(str, remote))}…")
        try:
            result = bpy.ops.extensions.package_install(
                "EXEC_DEFAULT",
                repo_index=index,
                pkg_id=PACKAGE_ID,
                enable_on_install=True,
            )
        except Exception as exc:
            _set_status(context, f"更新失敗：{exc}", clear_after=5.0)
            return {"CANCELLED"}
        if result != {"FINISHED"}:
            _set_status(context, "更新失敗：安裝未完成", clear_after=4.0)
            return {"CANCELLED"}
        _set_status(context, f"已安裝 {'.'.join(map(str, remote))}，正在套用…")
        bpy.ops.wm.save_userpref()
        _schedule_reload(__package__, remote, repo.directory, context.scene.name)
        return {"FINISHED"}


CLASSES = (FBR_OT_online_update,)
