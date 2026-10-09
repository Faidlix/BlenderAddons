import importlib
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT.parent))

addon = importlib.import_module(os.environ.get("FBR_TEST_MODULE", "Faidlix_BoneRemap"))
_calibrate_ik_pole_angle = importlib.import_module(
    f"{addon.__name__}.operators"
)._calibrate_ik_pole_angle


def main():
    if not hasattr(bpy.types.Scene, "fbr_settings"):
        addon.register()
    armature = bpy.data.armatures.new("MirroredStraightData")
    obj = bpy.data.objects.new("MirroredStraight", armature)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for side, x in (("L", 1.0), ("R", -1.0)):
        upper = armature.edit_bones.new(f"UpperLeg.{side}")
        upper.head = (x, 0, 2)
        upper.tail = (x, 0, 1)
        lower = armature.edit_bones.new(f"LowerLeg.{side}")
        lower.parent = upper
        lower.head = (x, 0, 1)
        lower.tail = (x, 0, 0)
        foot = armature.edit_bones.new(f"Foot.{side}")
        foot.parent = lower
        foot.head = (x, 0, 0)
        foot.tail = (x, -0.2, 0)
    bpy.ops.object.mode_set(mode="OBJECT")
    for side in ("L", "R"):
        constraint = obj.pose.bones[f"LowerLeg.{side}"].constraints.new("IK")
        constraint.pole_target = obj
        constraint.pole_subtarget = f"Foot.{side}"
        constraint.pole_angle = 0.7
        mapping = SimpleNamespace(ik_pole_bone=f"Foot.{side}", ik_pole_length=1.0)
        _calibrate_ik_pole_angle(bpy.context, obj, f"Foot.{side}", mapping, constraint)
        expected = 0.0 if side == "L" else math.pi
        assert abs(constraint.pole_angle - expected) < 1e-5, (side, constraint.pole_angle)

    # A non-mirrored pair must not receive a name-based 180-degree override.
    bpy.ops.object.mode_set(mode="EDIT")
    armature.edit_bones["Foot.R"].tail.x -= 0.1
    bpy.ops.object.mode_set(mode="OBJECT")
    right = obj.pose.bones["LowerLeg.R"].constraints[0]
    right.pole_angle = 0.7
    _calibrate_ik_pole_angle(
        bpy.context, obj, "Foot.R",
        SimpleNamespace(ik_pole_bone="Foot.R", ik_pole_length=1.0), right,
    )
    assert abs(right.pole_angle - 0.7) < 1e-5, right.pole_angle
    print("FBR_POLE_MIRROR_OK")


if __name__ == "__main__":
    main()
