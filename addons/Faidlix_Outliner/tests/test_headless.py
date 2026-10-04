import os
import sys

import bpy


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from Faidlix_Outliner.core import (  # noqa: E402
    STATE_ALL,
    STATE_NONE,
    STATE_PARTIAL,
    apply_restriction,
    collection_objects,
    object_hierarchy,
    selection_state,
    set_selected,
    target_objects,
)


bpy.ops.wm.read_factory_settings(use_empty=True)

root = bpy.data.objects.new("Root", None)
child = bpy.data.objects.new("Child", None)
grandchild = bpy.data.objects.new("Grandchild", None)
other = bpy.data.objects.new("Other", None)
child.parent = root
grandchild.parent = child

main = bpy.data.collections.new("Main")
nested = bpy.data.collections.new("Nested")
bpy.context.scene.collection.children.link(main)
main.children.link(nested)
main.objects.link(root)
nested.objects.link(child)
nested.objects.link(grandchild)
nested.objects.link(other)

hierarchy = object_hierarchy(root)
assert [obj.name for obj in hierarchy] == ["Root", "Child", "Grandchild"]
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_NONE

set_selected(hierarchy, True, bpy.context.view_layer)
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_ALL
grandchild.select_set(False)
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_PARTIAL
set_selected(hierarchy, False, bpy.context.view_layer)
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_NONE

collection_result = collection_objects(main)
assert {obj.name for obj in collection_result} == {"Root", "Child", "Grandchild", "Other"}
assert {obj.name for obj in target_objects(bpy.context.scene)} == {
    "Root",
    "Child",
    "Grandchild",
    "Other",
}

# Blender rejects selection for hidden or selection-locked objects. Hierarchy
# selection must reveal/unlock them first so every object is genuinely selected.
child.hide_set(True, view_layer=bpy.context.view_layer)
grandchild.hide_viewport = True
other.hide_select = True
set_selected(collection_result, True, bpy.context.view_layer)
assert selection_state(collection_result, bpy.context.view_layer) == STATE_ALL
assert child.hide_get(view_layer=bpy.context.view_layer) is False
assert grandchild.hide_viewport is False
assert other.hide_select is False
assert root.select_get(view_layer=bpy.context.view_layer) is True

apply_restriction(collection_result, "VIEWPORT", True, bpy.context.view_layer)
assert all(obj.hide_viewport for obj in collection_result)
apply_restriction(collection_result, "SELECT", True, bpy.context.view_layer)
assert all(obj.hide_select for obj in collection_result)
apply_restriction(collection_result, "RENDER", True, bpy.context.view_layer)
assert all(obj.hide_render for obj in collection_result)

import Faidlix_Outliner  # noqa: E402

assert Faidlix_Outliner.ADDON_VERSION == (0, 2, 16)
assert Faidlix_Outliner._latest_version_from_index(
    {
        "data": [
            {"id": "unrelated", "version": "9.0.0"},
            {"id": "faidlix_outliner", "version": "0.1.0"},
            {"id": "faidlix_outliner", "version": "0.2.16"},
        ]
    }
) == (0, 2, 16)

original_header_draw = bpy.types.OUTLINER_HT_header.draw
Faidlix_Outliner.register()
assert hasattr(bpy.ops.faidlix_outliner, "toggle_target")
assert hasattr(bpy.ops.faidlix_outliner, "online_update")
assert bpy.types.OUTLINER_HT_header.draw is Faidlix_Outliner._draw_outliner_header
checkbox_property = Faidlix_Outliner.FAIDLIXOUTLINER_Preferences.bl_rna.properties["checkbox_x"]
assert checkbox_property.default == 42  # Legacy preference retained for updates.
assert Faidlix_Outliner.OVERLAY_BOX_SIZE == 14
assert Faidlix_Outliner.OVERLAY_ICON_GAP == 9
assert Faidlix_Outliner.CHECKBOX_DEFAULT_X == 42
assert Faidlix_Outliner.TREE_CONTENT_OFFSET == 0
assert Faidlix_Outliner.TREE_RESET_OFFSET == 4096
assert Faidlix_Outliner.LAYOUT_VERSION == 5
eye_property = Faidlix_Outliner.FAIDLIXOUTLINER_Preferences.bl_rna.properties["show_batch_eye"]
assert eye_property.default is True

toggle_kind = bpy.ops.faidlix_outliner.toggle_target.get_rna_type().properties["target_kind"]
restriction_kind = bpy.ops.faidlix_outliner.toggle_restriction.get_rna_type().properties["target_kind"]
assert "SCENE" in {item.identifier for item in toggle_kind.enum_items}
assert "SCENE" in {item.identifier for item in restriction_kind.enum_items}
assert "ARMATURE" in {item.identifier for item in toggle_kind.enum_items}

apply_restriction(collection_result, "SELECT", False, bpy.context.view_layer)
apply_restriction(collection_result, "VIEWPORT", False, bpy.context.view_layer)
set_selected(hierarchy, False, bpy.context.view_layer)
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="OBJECT",
    target_name="Root",
    action="AUTO",
)
assert result == {"FINISHED"}
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_ALL
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="OBJECT",
    target_name="Root",
    action="SUBTRACT",
)
assert result == {"FINISHED"}
assert selection_state(hierarchy, bpy.context.view_layer) == STATE_NONE

# The Scene Collection root controls every scene object, including objects
# Blender refuses to select natively because they are hidden or locked.
child.hide_set(True, view_layer=bpy.context.view_layer)
grandchild.hide_viewport = True
other.hide_select = True
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="SCENE",
    target_name=bpy.context.scene.name,
    action="AUTO",
)
assert result == {"FINISHED"}
assert Faidlix_Outliner._effective_selection_state(
    collection_result, bpy.context.view_layer
) == STATE_ALL
assert child.hide_get(view_layer=bpy.context.view_layer) is True
assert grandchild.hide_viewport is True
assert other.hide_select is True
assert {"Child", "Grandchild", "Other"}.issubset(Faidlix_Outliner._logical_selection())
assert root.select_get(view_layer=bpy.context.view_layer) is True
assert Faidlix_Outliner._effective_target_state(root, bpy.context.view_layer) == STATE_ALL
batch_names = {obj.name for obj in Faidlix_Outliner._objects_for_batch(bpy.context, root)}
assert batch_names == {
    "Root",
    "Child",
    "Grandchild",
    "Other",
}, batch_names

# Clicking a restriction on a fully selected row batches across every current
# native/logical selection instead of changing only the clicked object.
result = bpy.ops.faidlix_outliner.toggle_restriction(
    target_kind="OBJECT",
    target_name="Root",
    restriction="HIDE",
)
assert result == {"FINISHED"}
assert all(obj.hide_get(view_layer=bpy.context.view_layer) for obj in collection_result)
result = bpy.ops.faidlix_outliner.toggle_restriction(
    target_kind="OBJECT",
    target_name="Root",
    restriction="HIDE",
)
assert result == {"FINISHED"}
assert not any(obj.hide_get(view_layer=bpy.context.view_layer) for obj in collection_result)

result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="SCENE",
    target_name=bpy.context.scene.name,
    action="SUBTRACT",
)
assert result == {"FINISHED"}
assert Faidlix_Outliner._effective_selection_state(
    collection_result, bpy.context.view_layer
) == STATE_NONE
assert not Faidlix_Outliner._logical_selection()

child.hide_set(False, view_layer=bpy.context.view_layer)
grandchild.hide_viewport = False
other.hide_select = False

# Armature data rows have their own checkbox. Armature object checkboxes also
# include every bone, while hidden bones remain logically selected.
armature = bpy.data.armatures.new("RigData")
rig = bpy.data.objects.new("Rig", armature)
main.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
armature.edit_bones.new("RootBone")
armature.edit_bones.new("HiddenBone")
bpy.ops.object.mode_set(mode="OBJECT")
rig.select_set(False)

result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="ARMATURE",
    target_name="RigData",
    action="AUTO",
)
assert result == {"FINISHED"}
assert all(bone.select for bone in rig.pose.bones)
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="ARMATURE",
    target_name="RigData",
    action="SUBTRACT",
)
assert result == {"FINISHED"}
assert not any(bone.select for bone in rig.pose.bones)
armature.bones["HiddenBone"].hide = True
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="OBJECT",
    target_name="Rig",
    action="AUTO",
)
assert result == {"FINISHED"}
assert rig.select_get(view_layer=bpy.context.view_layer)
assert rig.pose.bones["RootBone"].select
assert Faidlix_Outliner._bone_key(
    armature, armature.bones["HiddenBone"]
) in Faidlix_Outliner._logical_selection()
result = bpy.ops.faidlix_outliner.toggle_target(
    target_kind="OBJECT",
    target_name="Rig",
    action="SUBTRACT",
)
assert result == {"FINISHED"}
armature.bones["HiddenBone"].hide = False

# Restriction batching is based on the clicked object itself being selected,
# not on all of its bones also being selected. This matches Blender multi-
# selection behavior when clicking an eye icon on an Armature object.
for pose_bone in rig.pose.bones:
    pose_bone.select = False
set_selected(collection_result, False, bpy.context.view_layer, reveal_hidden=False)
root.select_set(True, view_layer=bpy.context.view_layer)
rig.select_set(True, view_layer=bpy.context.view_layer)
assert Faidlix_Outliner._effective_target_state(rig, bpy.context.view_layer) == STATE_PARTIAL
assert {obj.name for obj in Faidlix_Outliner._objects_for_batch(bpy.context, rig)} == {
    "Root",
    "Rig",
}
result = bpy.ops.faidlix_outliner.toggle_restriction(
    target_kind="OBJECT",
    target_name="Rig",
    restriction="HIDE",
)
assert result == {"FINISHED"}
assert root.hide_get(view_layer=bpy.context.view_layer)
assert rig.hide_get(view_layer=bpy.context.view_layer)
result = bpy.ops.faidlix_outliner.toggle_restriction(
    target_kind="OBJECT",
    target_name="Rig",
    restriction="HIDE",
)
assert result == {"FINISHED"}
assert not root.hide_get(view_layer=bpy.context.view_layer)
assert not rig.hide_get(view_layer=bpy.context.view_layer)

# Modal drag painting reuses one fixed value for each newly crossed hierarchy.
assert Faidlix_Outliner._apply_custom_drag_target(
    bpy.context, root, "EYE", True
) == 3
assert all(obj.hide_get(view_layer=bpy.context.view_layer) for obj in hierarchy)
assert Faidlix_Outliner._apply_custom_drag_target(
    bpy.context, root, "EYE", False
) == 3
assert not any(obj.hide_get(view_layer=bpy.context.view_layer) for obj in hierarchy)

assert Faidlix_Outliner._apply_custom_drag_target(
    bpy.context, root, "CHECKBOX", False
) == 3
assert Faidlix_Outliner._effective_target_state(root, bpy.context.view_layer) == STATE_NONE

result = bpy.ops.faidlix_outliner.toggle_restriction(
    target_kind="COLLECTION",
    target_name="Main",
    restriction="RENDER",
)
assert result == {"FINISHED"}
assert not any(obj.hide_render for obj in collection_result)

Faidlix_Outliner.unregister()
assert bpy.types.OUTLINER_HT_header.draw is original_header_draw

print("FAIDLIX_OUTLINER_HEADLESS=PASS")

