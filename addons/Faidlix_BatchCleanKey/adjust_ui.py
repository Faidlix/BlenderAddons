"""Observe native pose transforms, then apply one atomic selected-key edit."""
import time, math
import bpy
from bpy.props import BoolProperty,EnumProperty,StringProperty
from mathutils import Matrix
from . import adjust, adjust_hud
WATCH=None
REQUEST=None
IK_POLICY={}

def state(context): return context.window_manager.faidlix_batch_clean_key

def last_transform(context):
 ops=context.window_manager.operators
 return ops[-1].as_pointer() if ops else 0

def menu(self,context):
 if context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE':
  self.layout.separator()
  self.layout.operator('faidlix_batch_clean_key.adjust_toggle',text='動作一起調整：開／關' if state(context).adjust_toolbar_visible else '動作一起調整選取 Keys',icon='ACTION')

def draw(layout,context):
 s=state(context); box=layout.box()
 row=box.row(align=True)
 row.operator('faidlix_batch_clean_key.adjust_toggle',text='動作一起調整：開' if s.adjust_enabled else ('動作一起調整：關' if s.adjust_toolbar_visible else '動作一起調整選取 Keys'),depress=s.adjust_enabled,icon='ACTION')
 if s.adjust_toolbar_visible: row.operator('faidlix_batch_clean_key.adjust_close',text='關閉')
 if s.adjust_enabled:
  box.prop(s,'adjust_mode',expand=True)
  if s.adjust_mode=='KEEP_PATH':
   obj=bpy.data.objects.get(WATCH.object_name) if WATCH else context.object
   if obj: box.prop_search(s,'adjust_root',obj.data,'bones',text='主控骨')
  box.label(text='G／R／S 或操作軸確認後，立即套用選取 Keys')
  box.label(text='必要軸只補同影格 Key；Esc 取消當次調整')

class BCK_OT_AdjustIK(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_ik'
 bl_label='動作一起調整：未選取的 IK 控制骨'
 choice: EnumProperty(items=[('AUTO','自動加入',''),('SELECTED','維持原選取','')],default='AUTO')
 signature: StringProperty()
 names: StringProperty()
 def invoke(self,context,event): return context.window_manager.invoke_props_dialog(self,width=460,confirm_text='確認選擇')
 def draw(self,context):
  self.layout.label(text='IK Target／Pole 未選取，或沒有選到 Key：')
  for n in self.names.split('|'): self.layout.label(text=n)
  self.layout.prop(self,'choice',expand=True)
  self.layout.label(text='確認後請重新開始 G／R／S 或操作軸調整')
 def execute(self,context):
  IK_POLICY[self.signature]=self.choice
  state(context).last_result='IK 設定已確認，請開始調整'
  return {'FINISHED'}

class BCK_OT_AdjustToggle(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_toggle'
 bl_label='動作一起調整選取 Keys'
 @classmethod
 def poll(cls,context):
  return bool(context.object and context.object.type=='ARMATURE' and context.object.mode=='POSE' and not state(context).running and not state(context).pending)
 def execute(self,context):
  s=state(context)
  if s.adjust_toolbar_visible:
   s.adjust_enabled=not s.adjust_enabled
   return {'FINISHED'}
  from . import ui
  if ui.rig(context)!=context.object:
   self.report({'ERROR'},'請讓目前操作骨架與外掛指定骨架一致'); return {'CANCELLED'}
  try: adjust.capture(context,context.object)
  except ValueError as exc:
   self.report({'ERROR'},str(exc)); return {'CANCELLED'}
  s.adjust_enabled=True; s.adjust_toolbar_visible=True
  IK_POLICY.clear()
  if not s.adjust_root:
   active=context.object.data.bones.active
   s.adjust_root=active.name if active else context.object.data.bones[0].name
  return bpy.ops.faidlix_batch_clean_key.adjust_watch('INVOKE_DEFAULT')

class BCK_OT_AdjustWatch(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_watch'
 bl_label='動作一起調整模式'
 bl_options={'INTERNAL'}
 def invoke(self,context,event):
  global WATCH
  WATCH=self; self.object_name=context.object.name; self.action_name=context.object.animation_data.action.name
  self.window=context.window; self.screen=context.screen; self.area=context.area; self.request=None; self.auto=None
  self.hud=bpy.types.SpaceView3D.draw_handler_add(adjust_hud.draw,(self,),'WINDOW','POST_PIXEL')
  self.timer=context.window_manager.event_timer_add(.08,window=context.window)
  context.window_manager.modal_handler_add(self)
  return {'RUNNING_MODAL'}
 def restore_auto(self,context):
  if self.auto is not None:
   context.scene.tool_settings.use_keyframe_insert_auto=self.auto; self.auto=None
 def stop(self,context):
  global WATCH
  self.restore_auto(context); self.request=None
  state(context).adjust_enabled=False; state(context).adjust_toolbar_visible=False
  if self.hud: bpy.types.SpaceView3D.draw_handler_remove(self.hud,'WINDOW'); self.hud=None
  if self.timer: context.window_manager.event_timer_remove(self.timer); self.timer=None
  if WATCH==self: WATCH=None
 def modal(self,context,event):
  global REQUEST
  s=state(context); obj=bpy.data.objects.get(self.object_name)
  from . import ui
  if not s.adjust_toolbar_visible or not obj or obj.mode!='POSE' or context.object!=obj or ui.rig(context)!=obj or context.screen!=self.screen or not obj.animation_data or not obj.animation_data.action or obj.animation_data.action.name!=self.action_name:
   self.stop(context); return {'FINISHED'}
  if event.type=='LEFTMOUSE' and event.value=='PRESS':
   button=adjust_hud.hit(context,event,self)
   if button: adjust_hud.click(context,button); return {'RUNNING_MODAL'}
  if not s.adjust_enabled:
   self.restore_auto(context); self.request=None
   return {'PASS_THROUGH'}
  if s.running or s.pending: return {'PASS_THROUGH'}
  if event.type in {'G','R','S','LEFTMOUSE'} and event.value=='PRESS' and not self.request and not event.ctrl and not event.alt:
   if context.area.type!='VIEW_3D' or not context.region or context.region.type!='WINDOW': return {'PASS_THROUGH'}
   try:
    r=adjust.capture(context,obj)
    if s.adjust_mode=='KEEP_PATH' and s.adjust_root not in obj.pose.bones: raise ValueError('請先指定主控骨')
    missing=adjust.missing_ik(obj,r['times']) if s.adjust_mode!='LOCAL' else []
    sig=repr((obj.name,tuple(sorted(r['times'])),tuple(missing)))
    if missing and sig not in IK_POLICY:
     bpy.ops.faidlix_batch_clean_key.adjust_ik('INVOKE_DEFAULT',signature=sig,names='|'.join(missing))
     return {'RUNNING_MODAL'}
    added=missing if IK_POLICY.get(sig)=='AUTO' else []
    if added:
     for n in added: obj.pose.bones[n].select=True
    r['selected']=sorted(set(r['selected'])|set(added))
    r['added']=added; r['mode']=s.adjust_mode; r['root']=s.adjust_root
    self.request=r; self.operator_pointer=last_transform(context)
    self.started=time.monotonic(); self.auto=context.scene.tool_settings.use_keyframe_insert_auto
    r['auto']=self.auto
    context.scene.tool_settings.use_keyframe_insert_auto=False
   except ValueError as exc:
    s.last_result=str(exc)
    if event.type!='LEFTMOUSE': self.report({'WARNING'},str(exc)); return {'RUNNING_MODAL'}
  if event.type=='TIMER' and self.request:
   # Native transform's own modal handler runs before this observer.
   active=[o.bl_idname for o in context.window.modal_operators]
   if any(n.startswith('TRANSFORM_OT_') for n in active): return {'PASS_THROUGH'}
   pointer=last_transform(context)
   if pointer!=self.operator_pointer:
    op=context.window_manager.operators[-1]
    if op.bl_idname in {'TRANSFORM_OT_translate','TRANSFORM_OT_rotate','TRANSFORM_OT_resize'}:
     r=self.request; deltas=adjust.native_deltas(r,obj)
     unchanged=all(max(abs(d[i][j]-Matrix.Identity(4)[i][j]) for i in range(4) for j in range(4))<1e-6 for d in deltas.values())
     self.restore_auto(context); self.request=None
     if not unchanged:
      # Remove the native preview undo step: one subsequent key edit is one Undo.
      r['deltas']={n:tuple(tuple(row) for row in d) for n,d in deltas.items()}
      if not bpy.ops.ed.undo.poll(): s.last_result='無法建立安全復原步驟，取消動作一起調整'; return {'PASS_THROUGH'}
      bpy.ops.ed.undo()
      restore_context(context,r)
      bpy.ops.ed.undo_push(message='動作一起調整（操作前）')
      state(context).adjust_enabled=True; state(context).adjust_toolbar_visible=True
      REQUEST=r
      bpy.ops.faidlix_batch_clean_key.adjust_apply('INVOKE_DEFAULT')
    else:
     r=self.request; self.restore_auto(context); self.request=None
     if op.bl_idname.startswith('TRANSFORM_OT_'):
      bpy.ops.ed.undo(); restore_context(context,r)
      state(context).adjust_enabled=True
      state(context).last_result='此變換不支援動作一起調整，已取消；請使用 G／R／S'
   elif time.monotonic()-self.started>.2:
    self.restore_auto(context); self.request=None
  return {'PASS_THROUGH'}
 def cancel(self,context): self.stop(context)

def restore_context(context,r):
 obj=bpy.data.objects[r['object']]
 s=state(context); s.target_armature=obj; s.adjust_mode=r['mode']; s.adjust_root=r['root']
 for bone in obj.pose.bones:
  bone.select=bone.name in r['selected']
  for prop,value in r['defaults'][bone.name].items(): setattr(bone,prop,value)
 if r['active'] in obj.data.bones: obj.data.bones.active=obj.data.bones[r['active']]
 bag=adjust.bag_for(obj.animation_data.action,obj)
 for path,index,selected,points in r['key_selection']:
  c=bag.fcurves.find(path,index=index)
  if not c: continue
  c.select=selected; selection={f:(a,b,d) for f,a,b,d in points}
  for p in c.keyframe_points:
   if float(p.co.x) in selection:
    p.select_control_point,p.select_left_handle,p.select_right_handle=selection[float(p.co.x)]
 context.scene.tool_settings.use_keyframe_insert_auto=r['auto']
 context.scene.tool_settings.transform_pivot_point=r['pivot']
 context.scene.cursor.location=r['cursor']
 context.scene.frame_end=max(context.scene.frame_end,r['range'][1])
 context.scene.frame_start=r['range'][0]; context.scene.frame_end=r['range'][1]
 context.scene.frame_set(math.floor(r['frame']),subframe=r['frame']-math.floor(r['frame']))

class BCK_OT_AdjustApply(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_apply'
 bl_label='套用動作一起調整 Keys'
 bl_options={'UNDO','INTERNAL'}
 def invoke(self,context,event):
  global REQUEST
  if not REQUEST: return {'CANCELLED'}
  self.request=REQUEST; REQUEST=None
  try: self.steps=adjust.steps(self.request,self.request['deltas'],self.request['mode'],self.request['root'],self.request['added'])
  except ValueError as exc: self.report({'ERROR'},str(exc)); return {'CANCELLED'}
  s=state(context); s.running=True; s.cancel_requested=False; s.progress=0
  self.committing=False
  self.timer=context.window_manager.event_timer_add(.04,window=context.window)
  context.window_manager.modal_handler_add(self); return {'RUNNING_MODAL'}
 def finish(self,context):
  context.window_manager.event_timer_remove(self.timer)
  s=state(context); s.running=False; s.progress=0; s.cancel_requested=False
  context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
  from . import ui
  ui.refresh(context); ui.redraw(context)
 def modal(self,context,event):
  s=state(context)
  if WATCH and event.type=='LEFTMOUSE' and event.value=='PRESS':
   button=adjust_hud.hit(context,event,WATCH)
   if button: adjust_hud.click(context,button)
  if event.type=='ESC' or s.cancel_requested:
   self.steps.close(); s.last_result='已取消動作一起調整，原 Keys 保留'; self.finish(context); return {'CANCELLED'}
  if event.type!='TIMER': return {'RUNNING_MODAL'}
  try:
   deadline=time.perf_counter()+.008
   while True:
    done,total,text=next(self.steps); s.progress=min(.99,(.85 if self.committing else 0)+(.15 if self.committing else .85)*done/max(1,total)); s.progress_text=text
    if time.perf_counter()>=deadline: break
  except StopIteration as end:
   try:
    if not self.committing:
     self.steps=adjust.commit_steps(self.request,end.value); self.committing=True
     return {'RUNNING_MODAL'}
    count=end.value
    s.last_result=f'已動作一起調整 {len(self.request["times"])} 骨骼，補 {count} 個同影格 Keys'
    self.finish(context)
    return {'FINISHED'}
   except Exception as exc:
    s.last_result='未完成：'+str(exc); self.report({'ERROR'},str(exc)); self.finish(context); return {'CANCELLED'}
  except Exception as exc:
   s.last_result='未完成：'+str(exc); self.report({'ERROR'},str(exc)); self.finish(context); return {'CANCELLED'}
  from . import ui
  ui.redraw(context); return {'RUNNING_MODAL'}

class BCK_OT_AdjustClose(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_close'
 bl_label='關閉工具列與動作一起調整模式'
 def execute(self,context):
  adjust_hud.click(context,'close'); return {'FINISHED'}

BONE_ITEMS=[]
def root_items(self,context):
 global BONE_ITEMS
 obj=bpy.data.objects.get(WATCH.object_name) if WATCH else context.object
 names=tuple(b.name for b in obj.data.bones) if obj and obj.type=='ARMATURE' else ()
 if tuple(item[0] for item in BONE_ITEMS)!=names: BONE_ITEMS=[(n,n,'') for n in names]
 return BONE_ITEMS

class BCK_OT_AdjustSettings(bpy.types.Operator):
 bl_idname='faidlix_batch_clean_key.adjust_settings'
 bl_label='選取主控骨'
 bl_property='bone'
 bone: EnumProperty(items=root_items)
 @classmethod
 def poll(cls,context):
  s=state(context)
  return s.adjust_enabled and s.adjust_mode=='KEEP_PATH' and not s.running and not s.pending
 def invoke(self,context,event):
  context.window_manager.invoke_search_popup(self)
  return {'CANCELLED'}
 def execute(self,context):
  obj=bpy.data.objects.get(WATCH.object_name) if WATCH else context.object
  if not obj or self.bone not in obj.data.bones: return {'CANCELLED'}
  state(context).adjust_root=self.bone
  from . import ui
  ui.redraw(context)
  return {'FINISHED'}

CLASSES=(BCK_OT_AdjustClose,BCK_OT_AdjustSettings,BCK_OT_AdjustIK,BCK_OT_AdjustToggle,BCK_OT_AdjustWatch,BCK_OT_AdjustApply)
@bpy.app.handlers.persistent
def reset_after_load(_):
 global WATCH,REQUEST
 if WATCH:
  WATCH.auto=None
  try: WATCH.stop(bpy.context)
  except Exception: WATCH=None
 REQUEST=None; IK_POLICY.clear()
 if hasattr(bpy.context.window_manager,'faidlix_batch_clean_key'):
  state(bpy.context).adjust_enabled=False; state(bpy.context).adjust_toolbar_visible=False

def register():
 for cls in CLASSES: bpy.utils.register_class(cls)
 bpy.types.VIEW3D_MT_pose_context_menu.append(menu)
 bpy.app.handlers.load_post.append(reset_after_load)
def unregister():
 global REQUEST
 if WATCH:
  try: WATCH.stop(bpy.context)
  except Exception: pass
 REQUEST=None; IK_POLICY.clear()
 bpy.types.VIEW3D_MT_pose_context_menu.remove(menu)
 if reset_after_load in bpy.app.handlers.load_post: bpy.app.handlers.load_post.remove(reset_after_load)
 for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)
