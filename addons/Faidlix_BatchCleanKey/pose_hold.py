"""Pose / Dope Sheet / Timeline / Graph Editor context menu > Fixed Pose > First/Last selected key.

Hold selected bones in their local pose coordinates at existing selected times.
Sample every bone at the shared boundary before editing; never bake new frames.
"""
import bpy
from bpy.props import EnumProperty
from . import core, adjust

MENUS = (bpy.types.VIEW3D_MT_pose_context_menu, bpy.types.DOPESHEET_MT_context_menu, bpy.types.GRAPH_MT_context_menu)


def hold(context, anchor):
    obj = context.object
    names = core.selected_bones(context)
    action = obj.animation_data.action if obj and obj.animation_data else None
    if not names or not action or not obj.is_editable or not action.is_editable:
        raise ValueError('請選取可編輯骨架、骨頭與目前 Action')
    if obj.animation_data.use_tweak_mode:
        raise ValueError('請先離開 NLA Tweak Mode')
    bag = adjust.bag_for(action,obj)
    curves = {(c.data_path,c.array_index):c for c in bag.fcurves}
    plans = []
    for name in names:
        bone = obj.pose.bones[name]
        prefix = bone.path_from_id()+'.'
        times = {float(p.co.x) for c in bag.fcurves if c.data_path.startswith(prefix)
                 for p in c.keyframe_points if p.select_control_point}
        if times:
            rotation = ('rotation_quaternion' if bone.rotation_mode=='QUATERNION' else
                        'rotation_axis_angle' if bone.rotation_mode=='AXIS_ANGLE' else 'rotation_euler')
            plans.append((bone,times,rotation))
    if not plans:
        raise ValueError('請同時選取骨頭並框選它們的 Key')
    times = set().union(*(p[1] for p in plans))
    reference = min(times) if anchor=='FIRST' else max(times)
    writes, skipped, held = [], [], []
    # Read all reference values first, so multi-bone results are order-independent.
    for bone,frames,rotation in plans:
        properties = ('location',rotation)
        paths = {bone.path_from_id(prop) for prop in properties}
        if any(c.lock or c.mute or c.sampled_points or any(not m.mute and m.type!='CYCLES' for m in c.modifiers)
               for c in bag.fcurves if c.data_path in paths):
            skipped.append(bone.name); continue
        held.append(bone.name)
        for prop in properties:
            path = bone.path_from_id(prop)
            for index,default in enumerate(getattr(bone,prop)):
                curve = curves.get((path,index))
                value = curve.evaluate(reference) if curve else default
                writes.append((path,index,sorted(frames),value))
    for path,index,frames,value in writes:
        curve = curves.get((path,index))
        if curve is None:
            curve = bag.fcurves.new(path,index=index);curves[path,index]=curve
        for frame in frames:
            point = next((p for p in curve.keyframe_points if abs(p.co.x-frame)<1e-5),None)
            if point is None:
                curve.keyframe_points.insert(frame,value,options={'FAST'})
        curve.update()
        points = curve.keyframe_points
        for i,point in enumerate(points):
            if not any(abs(point.co.x-f)<1e-5 for f in frames): continue
            left = (point.co.x-points[i-1].co.x)/3 if i else 1/3
            right = (points[i+1].co.x-point.co.x)/3 if i+1<len(points) else 1/3
            point.co.y = value
            point.interpolation='BEZIER'
            point.handle_left_type=point.handle_right_type='FREE'
            point.handle_left=(point.co.x-left,value)
            point.handle_right=(point.co.x+right,value)
            point.select_control_point=True
        curve.update()
    if writes:
        action.update_tag();obj.update_tag()
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
    return held,skipped,reference


class BCK_OT_PoseHold(bpy.types.Operator):
    bl_idname='faidlix_batch_clean_key.pose_hold'
    bl_label='固定姿勢'
    bl_description='以共同第一／最後選取影格固定各骨頭的位置與旋轉；使用骨頭自身座標，不固定世界位置'
    bl_options={'REGISTER','UNDO'}
    anchor: EnumProperty(items=[('FIRST','以第一個 Key 為準','以全部選取 Key 的最早影格為共同基準'),
                                ('LAST','以最後一個 Key 為準','以全部選取 Key 的最晚影格為共同基準')])

    @classmethod
    def poll(cls,context):
        return bool(context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE')

    def invoke(self,context,event):
        return context.window_manager.invoke_popup(self,width=250)

    def draw(self,context):
        self.layout.operator_context='EXEC_DEFAULT'
        for value,label in (('FIRST','以第一個 Key 為準'),('LAST','以最後一個 Key 為準')):
            self.layout.operator(self.bl_idname,text=label).anchor=value

    def execute(self,context):
        try: held,skipped,reference=hold(context,self.anchor)
        except ValueError as exc:
            self.report({'WARNING'},str(exc));return {'CANCELLED'}
        self.report({'WARNING'} if skipped else {'INFO'},f'已固定 {len(held)} 根骨頭；基準影格 {reference:g}'+
                    ('；跳過鎖定、停用或修飾器／取樣骨頭：'+'、'.join(skipped) if skipped else ''))
        return {'FINISHED'}


def menu(self,context):
    row = self.layout.row()
    row.operator_context = 'INVOKE_REGION_WIN'
    row.operator(BCK_OT_PoseHold.bl_idname,text='固定姿勢')


def register():
    bpy.utils.register_class(BCK_OT_PoseHold)
    for target in MENUS: target.append(menu)


def unregister():
    for target in reversed(MENUS): target.remove(menu)
    bpy.utils.unregister_class(BCK_OT_PoseHold)
