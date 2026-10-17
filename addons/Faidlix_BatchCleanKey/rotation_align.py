"""Pose context menu > Rotation Align > Previous/Next.

Align selected rotation keys to one reference outside the shared selection range.
Only equivalent Euler/axis-angle turns and quaternion signs are changed.
"""
import math
import bpy
from bpy.props import EnumProperty
from . import core, adjust


def align(context, direction):
    obj = context.object
    names = core.selected_bones(context)
    action = obj.animation_data.action if obj and obj.animation_data else None
    if not names or not action or not action.is_editable or not obj.is_editable:
        raise ValueError('請選取可編輯骨架、骨頭與目前 Action')
    if obj.animation_data.use_tweak_mode:
        raise ValueError('請先離開 NLA Tweak Mode')
    bag = adjust.bag_for(action, obj)
    groups = []
    for name in names:
        bone = obj.pose.bones[name]
        prop = ('rotation_quaternion' if bone.rotation_mode == 'QUATERNION' else
                'rotation_axis_angle' if bone.rotation_mode == 'AXIS_ANGLE' else 'rotation_euler')
        path = bone.path_from_id(prop)
        curves = {c.array_index:c for c in bag.fcurves if c.data_path == path}
        if curves:
            times = {float(p.co.x) for c in curves.values() for p in c.keyframe_points if p.select_control_point}
            groups.append((bone, prop, path, curves, times))
    selected = set().union(*(g[4] for g in groups)) if groups else set()
    if not selected:
        frame = context.scene.frame_current_final
        groups = [(b, prop, path, cs, {float(p.co.x) for c in cs.values() for p in c.keyframe_points if abs(p.co.x-frame)<1e-5})
                  for b, prop, path, cs, _ in groups]
        selected = set().union(*(g[4] for g in groups)) if groups else set()
    if not selected:
        raise ValueError('請框選旋轉 Key，或移到已有旋轉 Key 的影格')
    boundary = min(selected) if direction == 'PREVIOUS' else max(selected)
    edits, inserts, skipped = [], [], []
    for bone, prop, path, curves, times in groups:
        if not times:
            continue
        if any(c.lock or c.mute or c.sampled_points or any(not m.mute and m.type != 'CYCLES' for m in c.modifiers) for c in curves.values()):
            skipped.append(bone.name+'（鎖定、停用或含修飾器／取樣）'); continue
        candidates = {float(p.co.x) for c in curves.values() for p in c.keyframe_points
                      if (p.co.x < boundary-1e-5 if direction == 'PREVIOUS' else p.co.x > boundary+1e-5)}
        if not candidates:
            skipped.append(bone.name+'（沒有範圍外參考 Key）'); continue
        reference = max(candidates) if direction == 'PREVIOUS' else min(candidates)
        defaults = tuple(getattr(bone, prop))
        def values(frame):
            return [curves[i].evaluate(frame) if i in curves else v for i,v in enumerate(defaults)]
        ref = values(reference)
        for frame in sorted(times):
            vals = values(frame)
            if prop == 'rotation_quaternion':
                if sum(x*x for x in vals)<1e-12 or sum(x*x for x in ref)<1e-12:
                    skipped.append(bone.name+'（無效 Quaternion）'); continue
                sign = -1 if sum(x*y for x,y in zip(vals,ref)) < 0 else 1
                transforms = [(i, sign, 0.0) for i in range(4)] if sign < 0 else []
            else:
                axes = range(3) if prop == 'rotation_euler' else (0,)
                transforms = [(i,1,math.tau*round((ref[i]-vals[i])/math.tau)) for i in axes]
            for i,scale,offset in transforms:
                if scale == 1 and abs(offset)<1e-10: continue
                curve = curves.get(i)
                point = next((p for p in curve.keyframe_points if abs(p.co.x-frame)<1e-5),None) if curve else None
                if point:
                    edits.append((curve,point,scale,offset))
                elif prop == 'rotation_quaternion':
                    # All four components must change sign together; add only at selected times.
                    inserts.append((path,i,frame,scale*vals[i]+offset))
    for curve,point,scale,offset in edits:
        coords = [tuple(point.co),tuple(point.handle_left),tuple(point.handle_right)]
        point.co.y = scale*coords[0][1]+offset
        point.handle_left = (coords[1][0],scale*coords[1][1]+offset)
        point.handle_right = (coords[2][0],scale*coords[2][1]+offset)
    for path,i,frame,value in inserts:
        curve = bag.fcurves.find(path,index=i) or bag.fcurves.new(path,index=i)
        point = curve.keyframe_points.insert(frame,value)
        point.interpolation='BEZIER'
        point.handle_left_type=point.handle_right_type='AUTO_CLAMPED'
        point.select_control_point=True
    if edits or inserts:
        touched = {c.as_pointer() for c,_,_,_ in edits}
        added = {(path,i) for path,i,_,_ in inserts}
        for curve in bag.fcurves:
            if curve.as_pointer() in touched or (curve.data_path,curve.array_index) in added:
                curve.update()
        action.update_tag(); obj.update_tag()
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
    return len(edits)+len(inserts), sorted(set(skipped))


class BCK_OT_RotationAlign(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.rotation_align'
    bl_label = '旋轉對齊'
    bl_description = '保持姿勢，將選取旋轉 Key 的圈數／正負號對齊範圍外共同參考 Key'
    bl_options = {'REGISTER','UNDO'}
    direction: EnumProperty(items=[('PREVIOUS','對齊前方','以框選範圍前最近的旋轉 Key 為共同參考'),
                                   ('NEXT','對齊後方','以框選範圍後最近的旋轉 Key 為共同參考')])

    @classmethod
    def poll(cls,context):
        return bool(context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE')

    def invoke(self,context,event):
        return context.window_manager.invoke_popup(self,width=230)

    def draw(self,context):
        self.layout.operator_context='EXEC_DEFAULT'
        for direction,label in (('PREVIOUS','對齊前方'),('NEXT','對齊後方')):
            self.layout.operator(self.bl_idname,text=label).direction=direction

    def execute(self,context):
        try:
            changed,skipped=align(context,self.direction)
        except ValueError as exc:
            self.report({'WARNING'},str(exc)); return {'CANCELLED'}
        self.report({'WARNING'} if skipped else {'INFO'},f'已對齊 {changed} 個旋轉 Key'+('；跳過：'+'、'.join(skipped) if skipped else ''))
        return {'FINISHED'}


def menu(self,context):
    self.layout.operator(BCK_OT_RotationAlign.bl_idname,text='旋轉對齊')


def register():
    bpy.utils.register_class(BCK_OT_RotationAlign)
    bpy.types.VIEW3D_MT_pose_context_menu.append(menu)


def unregister():
    bpy.types.VIEW3D_MT_pose_context_menu.remove(menu)
    bpy.utils.unregister_class(BCK_OT_RotationAlign)
