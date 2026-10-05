import importlib.util
import json
import pathlib
import sys
import tempfile
from types import SimpleNamespace

import bpy


root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("faidlix_manager", root / "__init__.py")
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)

assert addon.ADDON_VERSION == (1, 1, 5)
assert addon.PACKAGE_ID == "faidlix_manager"
assert addon.REPOSITORY_URL.endswith("Faidlix/BlenderAddons/main/repository/index.json")
registry = addon._addon_registry()
assert registry["faidlix_manager"]["common_features"] == ["update_all"]
assert registry["blander_texture_marge"]["display_name"] == "Faidlix Texture Marge"

assert addon._canonical_repository_url(addon.REPOSITORY_URL + "?cache=123#test") == (
    "https",
    "raw.githubusercontent.com",
    "/Faidlix/BlenderAddons/main/repository/index.json",
)
with tempfile.TemporaryDirectory() as temp_dir:
    root = pathlib.Path(temp_dir)
    empty_dir = root / "empty"
    active_dir = root / "active"
    empty_dir.mkdir()
    (active_dir / addon.PACKAGE_ID).mkdir(parents=True)
    empty_repo = SimpleNamespace(
        remote_url=addon.REPOSITORY_URL,
        module="EmptyDuplicate",
        directory=str(empty_dir),
    )
    active_repo = SimpleNamespace(
        remote_url=addon.REPOSITORY_URL + "?cache=123",
        module="ActiveRepository",
        directory=str(active_dir),
    )
    context = SimpleNamespace(
        preferences=SimpleNamespace(
            extensions=SimpleNamespace(repos=[empty_repo, active_repo]),
        ),
    )
    assert addon._repository(context) == (1, active_repo)
    assert addon._repository(context, preferred_module="ActiveRepository") == (1, active_repo)
    cache_dir = active_dir / ".blender_ext"
    cache_dir.mkdir()
    (cache_dir / "index.json").write_text(
        json.dumps(
            {
                "data": [
                    {"id": addon.PACKAGE_ID},
                    {"id": "blander_texture_marge"},
                ],
            },
        ),
        encoding="utf-8",
    )
    assert addon._installed_package_count(active_repo) == 1
    assert not addon.FAIDLIXMANAGER_PT_update_all.poll(context)
    (active_dir / "blander_texture_marge").mkdir()
    assert addon._installed_package_count(active_repo) == 2
    assert addon.FAIDLIXMANAGER_PT_update_all.poll(context)

addon.register()
assert hasattr(bpy.ops.faidlix_manager, "update_all")
assert hasattr(bpy.types, "FAIDLIXMANAGER_PT_update_all")
assert addon.FAIDLIXMANAGER_PT_update_all.bl_options == {'HIDE_HEADER'}
assert addon.FAIDLIXMANAGER_PT_update_all.bl_order == -1000
addon.unregister()
assert not hasattr(bpy.types, "FAIDLIXMANAGER_PT_update_all")
print("FAIDLIX_MANAGER_HEADLESS_OK")
