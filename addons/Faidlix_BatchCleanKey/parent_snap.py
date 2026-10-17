"""Object Mode context menu > 吸附到母物件位置.

Select one or more editable child objects, right-click in Object Mode, then run
the command. It moves each object origin to its object parent or posed parent
bone while preserving the object's world rotation and scale.
"""
import bpy


def target_position(obj):
    """Return the current world position of an object's effective parent."""
    parent = obj.parent
    if parent is None:
        return None
    if obj.parent_type == 'BONE':
        if parent.type != 'ARMATURE' or not obj.parent_bone:
            return None
        bone = parent.pose.bones.get(obj.parent_bone)
        if bone is None:
            return None
        return (parent.matrix_world @ bone.matrix).translation.copy()
    return parent.matrix_world.translation.copy()


def snap_selected(context):
    moved = []
    skipped = []
    for obj in context.selected_editable_objects:
        target = target_position(obj)
        if target is None:
            skipped.append(obj.name)
            continue
        # Mutating only the translation avoids decomposing/recomposing a
        # parent-relative matrix, which can alter rotation with scaled parents.
        obj.matrix_world.translation = target
        obj.update_tag()
        moved.append(obj.name)
    return moved, skipped


class BCK_OT_SnapToParentPosition(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.snap_to_parent_position'
    bl_label = '吸附到母物件位置'
    bl_description = '移到目前母物件或母骨頭的世界位置，保留世界旋轉與縮放'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.mode == 'OBJECT' and any(
            obj.parent is not None for obj in context.selected_editable_objects))

    def execute(self, context):
        moved, skipped = snap_selected(context)
        if not moved:
            self.report({'WARNING'}, '選取物件沒有有效的母物件或母骨頭')
            return {'CANCELLED'}
        message = f'已吸附 {len(moved)} 個物件到母物件位置'
        if skipped:
            message += '；略過：' + '、'.join(skipped)
        self.report({'WARNING'} if skipped else {'INFO'}, message)
        return {'FINISHED'}


def menu(self, context):
    self.layout.separator()
    self.layout.operator(BCK_OT_SnapToParentPosition.bl_idname)


def register():
    bpy.utils.register_class(BCK_OT_SnapToParentPosition)
    bpy.types.VIEW3D_MT_object_context_menu.append(menu)


def unregister():
    bpy.types.VIEW3D_MT_object_context_menu.remove(menu)
    bpy.utils.unregister_class(BCK_OT_SnapToParentPosition)
