"""Viewport toolbar for the selected-key transform session."""
import bpy,blf,gpu
from gpu_extras.batch import batch_for_shader
LABELS=(('toggle','一起調整'),('PATH','連同路徑'),('KEEP_PATH','保留路徑'),('LOCAL','局部姿勢'),('settings','主控骨'),('close','×'))
def bounds(region,state):
 scale=bpy.context.preferences.system.ui_scale
 widths=[118,90,90,90,90,30] if state.adjust_mode=='KEEP_PATH' else [118,90,90,90,0,30]
 widths=[w*scale for w in widths]; total=sum(widths)+8*scale
 x=max(8*scale,(region.width-total)/2); top=region.height-50*scale; h=30*scale
 result={}
 for (name,label),w in zip(LABELS,widths):
  if w: result[name]=(x,top-h,x+w-2*scale,top)
  x+=w
 return result

def draw(owner):
 from . import adjust_ui
 context=bpy.context
 if not owner.area or context.area!=owner.area or not context.region or context.region.type!='WINDOW': return
 s=adjust_ui.state(context)
 if not s.adjust_toolbar_visible: return
 shader=gpu.shader.from_builtin('UNIFORM_COLOR'); gpu.state.blend_set('ALPHA')
 try:
  for name,(x,y,right,top) in bounds(context.region,s).items():
   active=s.adjust_enabled if name=='toggle' else name==s.adjust_mode
   color=(.12,.32,.58,.95) if active else (.12,.12,.12,.94)
   batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(x,y),(right,y),(right,top),(x,top)]})
   shader.bind(); shader.uniform_float('color',color); batch.draw(shader)
   text=dict(LABELS)[name]
   if name=='toggle': text+='：開' if s.adjust_enabled else '：關'
   if name=='settings': text='主控骨 ▾'
   blf.size(0,int(13*context.preferences.system.ui_scale)); blf.color(0,1,1,1,1)
   w,h=blf.dimensions(0,text); blf.position(0,x+(right-x-w)/2,y+(top-y-h)/2,0); blf.draw(0,text)
 finally: gpu.state.blend_set('NONE')

def hit(context,event,owner):
 if context.area!=owner.area or not context.region or context.region.type!='WINDOW': return None
 x,y=event.mouse_x-context.region.x,event.mouse_y-context.region.y
 from . import adjust_ui
 for name,(left,bottom,right,top) in bounds(context.region,adjust_ui.state(context)).items():
  if left<=x<=right and bottom<=y<=top: return name
 return None

def click(context,name):
 from . import adjust_ui
 s=adjust_ui.state(context)
 if name=='close':
  s.adjust_enabled=False; s.adjust_toolbar_visible=False
  if s.running: s.cancel_requested=True
 elif name=='toggle':
  s.adjust_enabled=not s.adjust_enabled
  if not s.adjust_enabled and s.running: s.cancel_requested=True
 elif s.running: return
 elif name in {'PATH','KEEP_PATH','LOCAL'}: s.adjust_mode=name
 elif name=='settings': bpy.ops.faidlix_batch_clean_key.adjust_settings('INVOKE_DEFAULT')
 from . import ui
 ui.redraw(context)
