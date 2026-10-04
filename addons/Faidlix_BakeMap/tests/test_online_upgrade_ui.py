import importlib
import os
import time
import tomllib

import bpy


REPOSITORY_URL = "https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json"
repo = next(
    repo for repo in bpy.context.preferences.extensions.repos
    if repo.remote_url.split('?', 1)[0].rstrip('/') == REPOSITORY_URL
)
MODULE = f"bl_ext.{repo.module}.faidlix_bakemap"
EXPECTED_VERSION = (2, 3, 9)
started_at = time.monotonic()
version_before = None


def finish(success, message):
    print(message)
    bpy.ops.wm.quit_blender()
    if not success:
        raise RuntimeError(message)
    return None


def check_updated():
    addon = importlib.import_module(MODULE)
    manifest_path = os.path.join(os.path.dirname(addon.__file__), "blender_manifest.toml")
    with open(manifest_path, 'rb') as handle:
        disk_version = tuple(int(part) for part in tomllib.load(handle)['version'].split('.'))
    if disk_version == EXPECTED_VERSION:
        print("FAIDLIX_BAKEMAP_ONLINE_UPGRADE_UI=PASS")
        print(f"VERSION_BEFORE={version_before}")
        print(f"VERSION_ON_DISK={disk_version}")
        bpy.ops.wm.quit_blender()
        return None
    if time.monotonic() - started_at > 45.0:
        return finish(False, f"Timed out waiting for update: {disk_version}")
    return 0.5


def begin_update():
    global version_before
    addon = importlib.import_module(MODULE)
    version_before = addon.ADDON_VERSION
    if version_before >= EXPECTED_VERSION:
        return finish(False, f"Expected an older installed version, got {version_before}")
    result = bpy.ops.faidlix.online_update('EXEC_DEFAULT')
    if result != {'FINISHED'}:
        return finish(False, f"Online Update returned {result}")
    bpy.app.timers.register(check_updated, first_interval=0.5)
    return None


bpy.app.timers.register(begin_update, first_interval=0.5)
