from pathlib import Path

import bpy


package = None
installed = None
for repo in bpy.context.preferences.extensions.repos:
    candidate = f"bl_ext.{repo.module}.faidlix_bone_remap"
    try:
        installed = __import__(candidate, fromlist=["*"])
    except ModuleNotFoundError:
        continue
    package = candidate
    break

assert installed is not None and package is not None, "找不到已安裝的 faidlix_bone_remap"
assert installed.ui.ADDON_VERSION == (0, 6, 6), installed.ui.ADDON_VERSION

test_path = (
    Path(__file__).resolve().parents[1]
    / "addons"
    / "Faidlix_BoneRemap"
    / "tests"
    / "test_project_retarget.py"
)
source = test_path.read_text(encoding="utf-8")
source = source.replace(
    "import Faidlix_BoneRemap as addon",
    f"import {package} as addon",
)
source = source.replace(
    "from Faidlix_BoneRemap.model",
    f"from {package}.model",
)
source = source.replace(
    "from Faidlix_BoneRemap.retarget",
    f"from {package}.retarget",
)
source = source.replace(
    "from Faidlix_BoneRemap.operators",
    f"from {package}.operators",
)
namespace = {"__file__": str(test_path), "__name__": "__main__"}
exec(compile(source, str(test_path), "exec"), namespace)

print("INSTALLED_PACKAGE=" + package)
print("INSTALLED_PACKAGE_PATH=" + str(next(iter(installed.__path__))))
print("INSTALLED_PACKAGE_VERSION=" + ".".join(map(str, installed.ui.ADDON_VERSION)))
