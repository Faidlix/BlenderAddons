import sys
from pathlib import Path

import bpy


WORKSPACE = str(Path(__file__).resolve().parents[2])
ADDON_MODULE = "Faidlix_Weight"

if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)


def reset_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


def make_mesh():
    mesh = bpy.data.meshes.new("MirrorMesh")
    mesh.from_pydata(
        [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (-1.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 0.0, 0.0),
        ],
        [],
        [(0, 1, 3, 2)],
    )
    mesh.update()
    obj = bpy.data.objects.new("MirrorMesh", mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mesh.use_paint_mask_vertex = True
    return obj


def make_collision_mesh():
    mesh = bpy.data.meshes.new("CollisionMesh")
    mesh.from_pydata(
        [
            (-1.0, 0.00, 0.0),
            (-1.0, 0.10, 0.0),
            (1.0, 0.05, 0.0),
            (1.0, 0.18, 0.0),
        ],
        [],
        [(0, 2, 3, 1)],
    )
    mesh.update()
    obj = bpy.data.objects.new("CollisionMesh", mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mesh.use_paint_mask_vertex = True
    return obj


def make_single_target_mesh():
    mesh = bpy.data.meshes.new("SingleTargetMesh")
    mesh.from_pydata(
        [
            (-1.0, 0.00, 0.0),
            (-1.0, 0.10, 0.0),
            (1.0, 0.05, 0.0),
        ],
        [],
        [(0, 2, 1)],
    )
    mesh.update()
    obj = bpy.data.objects.new("SingleTargetMesh", mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mesh.use_paint_mask_vertex = True
    return obj


def set_selected(obj, indices):
    if obj.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for vertex in obj.data.vertices:
        vertex.select = vertex.index in indices
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')


def set_weight(obj, group_name, vertex_index, weight):
    group = obj.vertex_groups.get(group_name) or obj.vertex_groups.new(name=group_name)
    group.add([vertex_index], weight, 'REPLACE')


def weights(obj, vertex_index):
    return {
        obj.vertex_groups[item.group].name: round(item.weight, 6)
        for item in obj.data.vertices[vertex_index].groups
    }


reset_scene()
result_enable = bpy.ops.preferences.addon_enable(module=ADDON_MODULE)
assert result_enable == {'FINISHED'}
addon = sys.modules[ADDON_MODULE]
assert addon._CONTEXT_MENU is bpy.types.VIEW3D_PT_paint_weight_context_menu
assert bpy.context.scene.faidlix_weight_smart_match is True

name_cases = {
    "RightHand": "LeftHand",
    "righthand": "lefthand",
    "RIGHTHAND": "LEFTHAND",
    "Hand.L": "Hand.R",
    "hand.r": "hand.l",
    "HAND_L": "HAND_R",
    "Hand-r": "Hand-l",
    "Spine": "Spine",
}
for source, expected in name_cases.items():
    actual = addon.mirror_group_name(source)
    assert actual == expected, (source, actual, expected)

assert addon.ADDON_VERSION == (1, 3, 2)
assert addon.GITHUB_REPOSITORY_URL == (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
assert addon._latest_version_from_index({
    "data": [
        {"id": "other", "version": "9.0.0"},
        {"id": "faidlix_weight", "version": "1.1.0"},
        {"id": "faidlix_weight", "version": "1.3.2"},
    ]
}) == (1, 3, 2)
assert addon._normalized_repository_url(addon.GITHUB_REPOSITORY_URL) == (
    addon._normalized_repository_url(
        addon.GITHUB_REPOSITORY_URL + "?cache=1791649385#download"
    )
)
assert hasattr(bpy.ops.faidlix_weight, "online_update")

# Global one-to-one assignment must move a flexible source to its second
# candidate so a constrained source can keep the only target it can use.
assignment = addon._assign_unique_targets({
    10: [(0.10, 0.10, 100), (0.20, 0.20, 101)],
    11: [(0.11, 0.11, 100)],
})
assert assignment == {10: 101, 11: 100}, assignment
assert addon._assign_unique_targets({
    12: [(0.01, 0.01, 100), (0.20, 0.20, 102)],
}, {100}) == {12: 102}

obj = make_mesh()
set_weight(obj, "RightHand", 0, 0.75)
set_weight(obj, "Spine", 0, 0.25)
set_weight(obj, "OldTarget", 1, 1.0)

# One side, Flip off: selected source 0 copies to mirror 1.
bpy.context.scene.faidlix_weight_flip = False
set_selected(obj, {0})
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
assert weights(obj, 0) == {"RightHand": 0.75, "Spine": 0.25}
assert weights(obj, 1) == {"LeftHand": 0.75, "Spine": 0.25}

# One side, Flip on: opposite 3 copies back onto selected 2.
set_weight(obj, "LeftHand", 3, 0.6)
set_weight(obj, "Spine", 3, 0.4)
set_weight(obj, "OldSelected", 2, 1.0)
bpy.context.scene.faidlix_weight_flip = True
set_selected(obj, {2})
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
assert weights(obj, 2) == {"RightHand": 0.6, "Spine": 0.4}

# Both sides: Flip is forced and the original snapshots are exchanged.
set_weight(obj, "RightHand", 0, 0.9)
obj.vertex_groups["Spine"].add([0], 0.1, 'REPLACE')
obj.vertex_groups["LeftHand"].add([1], 0.2, 'REPLACE')
obj.vertex_groups["Spine"].add([1], 0.8, 'REPLACE')
bpy.context.scene.faidlix_weight_flip = False
set_selected(obj, {0, 1})
assert addon._selection_has_bilateral_pair(obj) is True
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
assert weights(obj, 0) == {"RightHand": 0.2, "Spine": 0.8}
assert weights(obj, 1) == {"LeftHand": 0.9, "Spine": 0.1}

# Locked-group conflict cancels atomically.
locked = obj.vertex_groups["Spine"]
locked.lock_weight = True
before_left = weights(obj, 0)
before_right = weights(obj, 1)
set_selected(obj, {0})
try:
    bpy.ops.faidlix_weight.mirror_selected()
except RuntimeError as exc:
    assert "locked vertex groups would change: Spine" in str(exc)
else:
    raise AssertionError("Locked-group conflict should cancel with an error")
assert weights(obj, 0) == before_left
assert weights(obj, 1) == before_right
locked.lock_weight = False

# Smart fallback: a nearby, topologically matching point receives the full
# replacement even when it is outside the strict X-mirror tolerance.
if obj.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
obj.data.vertices[3].co.x = 1.08
obj.data.vertices[3].co.y = 0.94
obj.data.update()
for group in obj.vertex_groups:
    group.remove([2, 3])
set_weight(obj, "Left_LowerArm", 2, 0.7)
set_weight(obj, "Left_Hand", 2, 0.3)
set_weight(obj, "Right_LowerArm", 3, 0.646)
set_weight(obj, "Right_Hand", 3, 0.024)
set_weight(obj, "Right_ThumbProximal", 3, 0.227)
set_weight(obj, "Right_ThumbIntermediate", 3, 0.103)
bpy.context.scene.faidlix_weight_flip = False
set_selected(obj, {2})
bpy.context.scene.faidlix_weight_smart_match = False
before_smart = weights(obj, 3)
assert bpy.ops.faidlix_weight.mirror_selected() == {'CANCELLED'}
assert weights(obj, 3) == before_smart
bpy.context.scene.faidlix_weight_smart_match = True
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
assert weights(obj, 3) == {"Right_LowerArm": 0.7, "Right_Hand": 0.3}

# Center-only selection is skipped safely.
set_selected(obj, {4})
assert bpy.ops.faidlix_weight.mirror_selected() == {'CANCELLED'}

# Two nearby sources initially prefer the same target. Smart Match must assign
# both targets one-to-one instead of cancelling with "multiple sources".
reset_scene()
obj = make_collision_mesh()
set_weight(obj, "Left_First", 0, 1.0)
set_weight(obj, "Left_Second", 1, 1.0)
set_weight(obj, "OldTargetA", 2, 1.0)
set_weight(obj, "OldTargetB", 3, 1.0)
bpy.context.scene.faidlix_weight_flip = False
bpy.context.scene.faidlix_weight_smart_match = True
set_selected(obj, {0, 1})
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
collision_results = [weights(obj, 2), weights(obj, 3)]
assert all(len(result) == 1 for result in collision_results)
assert {next(iter(result)) for result in collision_results} == {
    "Right_First",
    "Right_Second",
}
assert all(next(iter(result.values())) == 1.0 for result in collision_results)

# If there is only one viable target, copy one source and skip the unmatched
# source instead of cancelling every valid operation.
reset_scene()
obj = make_single_target_mesh()
set_weight(obj, "Left_First", 0, 1.0)
set_weight(obj, "Left_Second", 1, 1.0)
set_weight(obj, "OldTarget", 2, 1.0)
bpy.context.scene.faidlix_weight_flip = False
bpy.context.scene.faidlix_weight_smart_match = True
set_selected(obj, {0, 1})
assert bpy.ops.faidlix_weight.mirror_selected() == {'FINISHED'}
single_result = weights(obj, 2)
assert len(single_result) == 1
assert next(iter(single_result)) in {"Right_First", "Right_Second"}
assert next(iter(single_result.values())) == 1.0

bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.preferences.addon_disable(module=ADDON_MODULE)
assert not hasattr(bpy.types.Scene, "faidlix_weight_flip")
assert not hasattr(bpy.types.Scene, "faidlix_weight_smart_match")

print("FAIDLIX_WEIGHT_TEST=PASS")
print("NAME_CASES=8")
print("MIRROR_FORWARD=True")
print("FLIP_REVERSE=True")
print("BILATERAL_FORCED_SWAP=True")
print("LOCKED_GROUP_ATOMIC_CANCEL=True")
print("SMART_NEARBY_FULL_REPLACE=True")
print("SMART_ONE_TO_ONE_ASSIGNMENT=True")
print("SMART_CONFLICT_SKIPS_UNMATCHED=True")
print("CENTER_SKIP=True")
print("CONTEXT_MENU=VIEW3D_PT_paint_weight_context_menu")
