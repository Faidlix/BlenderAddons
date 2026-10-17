"""Test Object Mode parent-position snapping in Blender background mode.

Run with Blender --background --factory-startup --python this file. The test
covers object and bone parents, multiple selection, skipped objects and undo registration.
"""
import importlib
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
addon = importlib.import_module(os.environ.get('BCK_TEST_MODULE', 'Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
    addon.register()

armature = bpy.data.armatures.new('SnapArmature')
rig = bpy.data.objects.new('SnapArmature', armature)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone = armature.edit_bones.new('Hand')
bone.head = (1, 2, 3)
bone.tail = (1, 3, 3)
bpy.ops.object.mode_set(mode='POSE')
rig.pose.bones['Hand'].rotation_mode = 'XYZ'
rig.pose.bones['Hand'].rotation_euler.z = math.radians(35)
bpy.ops.object.mode_set(mode='OBJECT')
rig.matrix_world = Matrix.Translation((5, -2, 4)) @ Euler((.2, -.3, .4)).to_matrix().to_4x4()

parent = bpy.data.objects.new('SnapParent', None)
bpy.context.collection.objects.link(parent)
parent.matrix_world = Matrix.Translation((-4, 6, 2)) @ Euler((-.1, .25, .6)).to_matrix().to_4x4()

bone_child = bpy.data.objects.new('BoneProp', None)
object_child = bpy.data.objects.new('ObjectProp', None)
orphan = bpy.data.objects.new('Orphan', None)
for obj in (bone_child, object_child, orphan):
    bpy.context.collection.objects.link(obj)

bone_child.parent = rig
bone_child.parent_type = 'BONE'
bone_child.parent_bone = 'Hand'
object_child.parent = parent

bone_child.matrix_world = Matrix.LocRotScale((12, 5, -3), Euler((.4, .3, -.7)), (1.2, .8, 1.5))
object_child.matrix_world = Matrix.LocRotScale((3, -7, 8), Euler((-.5, .2, .9)), (.6, 1.4, 2.0))
orphan.matrix_world = Matrix.Translation((9, 9, 9))

def basis(obj):
    return tuple(tuple(round(obj.matrix_world[row][column], 6) for column in range(3)) for row in range(3))

def basis_close(left, right):
    return max(abs(left[row][column] - right[row][column])
               for row in range(3) for column in range(3)) < 1e-5

before = {obj.name: (obj.matrix_world.translation.copy(), basis(obj))
          for obj in (bone_child, object_child, orphan)}
for obj in bpy.context.selected_objects:
    obj.select_set(False)
for obj in (bone_child, object_child, orphan):
    obj.select_set(True)
bpy.context.view_layer.objects.active = bone_child

assert bpy.ops.faidlix_batch_clean_key.snap_to_parent_position() == {'FINISHED'}
expected_bone = (rig.matrix_world @ rig.pose.bones['Hand'].matrix).translation
assert (bone_child.matrix_world.translation - expected_bone).length < 1e-5
assert (object_child.matrix_world.translation - parent.matrix_world.translation).length < 1e-5
assert (orphan.matrix_world.translation - before['Orphan'][0]).length < 1e-5
assert basis_close(basis(bone_child), before['BoneProp'][1])
assert basis_close(basis(object_child), before['ObjectProp'][1])

assert 'UNDO' in addon.parent_snap.BCK_OT_SnapToParentPosition.bl_options

print('PARENT_SNAP_PASS object_parent bone_parent posed_world_position multi_select rotation_scale_preserved skip_orphan undo_registered')
