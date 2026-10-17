"""Dope Sheet/Timeline right-click > 調整動作幅度.
Drag horizontally to scale selected key values/handles about each curve's mean;
left click confirms one undoable edit, right click/Esc restores the captured curves.
"""
import math
import bpy

ACTIVE=None

def capture(context):
    curves=getattr(context,'editable_fcurves',None) or ()
    result=[]
    for curve in curves:
        if curve.lock or curve.hide or curve.mute:continue
        points=list(curve.keyframe_points)
        selected=[i for i,p in enumerate(points) if p.select_control_point]
        if len(selected)<2:continue
        snapshot=[(tuple(p.co),tuple(p.handle_left),tuple(p.handle_right),p.handle_left_type,p.handle_right_type) for p in points]
        result.append((curve,selected,sum(points[i].co.y for i in selected)/len(selected),snapshot))
    return result

def apply(rows,factor,restore=False):
    for curve,selected,mean,snapshot in rows:
        chosen=set(selected)
        for i,(p,old) in enumerate(zip(curve.keyframe_points,snapshot)):
            co,left,right,lt,rt=old
            p.handle_left_type=p.handle_right_type='FREE'
            p.co=co;p.handle_left=left;p.handle_right=right
            if i in chosen and not restore:
                p.co.y=mean+(co[1]-mean)*factor
                p.handle_left.y=mean+(left[1]-mean)*factor
                p.handle_right.y=mean+(right[1]-mean)*factor
        curve.update()
        for i,(p,old) in enumerate(zip(curve.keyframe_points,snapshot)):
            if restore or i not in chosen:
                p.handle_left_type,p.handle_right_type=old[3:]
                p.co,p.handle_left,p.handle_right=old[:3]
        curve.id_data.update_tag()

class BCK_OT_Amplitude(bpy.types.Operator):
    bl_idname='faidlix_batch_clean_key.amplitude'
    bl_label='調整動作幅度'
    bl_description='各曲線至少選兩個 Key；以平均值縮放，向右放大、向左縮小，左鍵確認、右鍵取消'
    bl_options={'UNDO','BLOCKING'}
    @classmethod
    def poll(cls,context):
        s=getattr(context.window_manager,'faidlix_batch_clean_key',None)
        return bool(context.area and context.area.type=='DOPESHEET_EDITOR' and ACTIVE is None and
                    s and not s.running and not s.pending and capture(context))
    def invoke(self,context,event):
        global ACTIVE
        self.rows=capture(context)
        if not self.rows:return {'CANCELLED'}
        self.area=context.area;self.start=event.mouse_x;self.factor=1.;self.closed=False
        ACTIVE=self;context.window_manager.modal_handler_add(self)
        self.refresh(context)
        return {'RUNNING_MODAL'}
    def refresh(self,context):
        self.area.header_text_set(f'動作幅度 {self.factor:.2f}× ｜ 向右放大、向左縮小 ｜ 左鍵確認、右鍵取消')
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
        for area in context.screen.areas:area.tag_redraw()
    def finish(self,context,cancel=False):
        global ACTIVE
        if self.closed:return
        self.closed=True
        try:
            if cancel:apply(self.rows,1,restore=True)
        finally:
            ACTIVE=None
            self.area.header_text_set(None)
            self.refresh_frame(context)
    def refresh_frame(self,context):
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
        for area in context.screen.areas:area.tag_redraw()
    def modal(self,context,event):
        try:
            if event.type in {'RIGHTMOUSE','ESC'} and event.value=='PRESS':
                self.finish(context,True);return {'CANCELLED'}
            if event.type in {'LEFTMOUSE','RET','NUMPAD_ENTER'} and event.value=='PRESS':
                self.finish(context);return {'FINISHED'}
            if event.type=='MOUSEMOVE':
                self.factor=max(0.,1+(event.mouse_x-self.start)/200.)
                apply(self.rows,self.factor);self.refresh(context)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.finish(context,True);self.report({'WARNING'},str(exc));return {'CANCELLED'}
    def cancel(self,context):self.finish(context,True)

def menu(self,context):
    self.layout.separator()
    row=self.layout.row();row.operator_context='INVOKE_REGION_WIN'
    row.operator(BCK_OT_Amplitude.bl_idname)

def register():
    bpy.utils.register_class(BCK_OT_Amplitude)
    bpy.types.DOPESHEET_MT_context_menu.append(menu)

def unregister():
    if ACTIVE:ACTIVE.finish(bpy.context,True)
    bpy.types.DOPESHEET_MT_context_menu.remove(menu)
    bpy.utils.unregister_class(BCK_OT_Amplitude)
