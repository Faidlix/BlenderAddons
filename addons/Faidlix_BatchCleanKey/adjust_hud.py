"""Viewport toolbar for the selected-key transform session."""
import bpy,blf,gpu,time
from gpu_extras.batch import batch_for_shader
LABELS=(('toggle','多影格同步調整'),('PATH','連同路徑'),('KEEP_PATH','保留路徑'),('settings','主控骨'),('close','關閉'))
TIPS={
 'PATH':('Transform with Path','依目前中心點調整選取骨骼；移動路徑一起轉向。'),
 'KEEP_PATH':('Preserve Path','以主控骨各影格位置為中心轉向；保留原本移動路徑。'),
 'settings':('Reference Bone','指定保留路徑的主控骨；選取後立即生效。'),
}

def bounds(region,state):
 scale=bpy.context.preferences.system.ui_scale; top=region.height-50*scale; h=30*scale
 width=230; x=max(8*scale,(region.width-(width+60)*scale)/2)
 rows=[[('toggle',width),('close',60)]]
 if state.adjust_enabled:
  rows.append([('PATH',width/2),('KEEP_PATH',width/2)])
  if state.adjust_mode=='KEEP_PATH': rows.append([('settings',width)])
 result={}
 for row in rows:
  left=x
  for name,w in row:
   result[name]=(left,top-h,left+(w-2)*scale,top); left+=w*scale
  top-=h+4*scale
 return result

def hover(context,event,owner):
 name=hit(context,event,owner)
 if name!=getattr(owner,'hover_name',None):
  owner.hover_name=name; owner.hover_since=time.monotonic()
 if owner.area: owner.area.tag_redraw()

def tooltip(owner,rects):
 name=getattr(owner,'hover_name',None)
 if name not in TIPS or name not in rects or time.monotonic()-getattr(owner,'hover_since',0)<.5: return None
 return TIPS[name]

def draw(owner):
 from . import adjust_ui, adjust_rotation
 context=bpy.context
 if not owner.area or context.area!=owner.area or not context.region or context.region.type!='WINDOW': return
 s=adjust_ui.state(context)
 if not s.adjust_toolbar_visible: return
 adjust_rotation.draw(owner,context)
 shader=gpu.shader.from_builtin('UNIFORM_COLOR'); gpu.state.blend_set('ALPHA')
 try:
  for name,(x,y,right,top) in bounds(context.region,s).items():
   active=s.adjust_enabled if name=='toggle' else name==s.adjust_mode
   color=(.12,.32,.58,.95) if active else (.12,.12,.12,.94)
   batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(x,y),(right,y),(right,top),(x,top)]})
   shader.bind(); shader.uniform_float('color',color); batch.draw(shader)
   blf.size(0,int(13*context.preferences.system.ui_scale))
   text=dict(LABELS)[name]
   if name=='settings':
    text='主控骨：'+(s.adjust_root or '請選擇')+' ▾'
    while len(text)>9 and blf.dimensions(0,text)[0]>right-x-16*context.preferences.system.ui_scale:
     text=text[:-4]+'… ▾'
   blf.size(0,int(13*context.preferences.system.ui_scale)); blf.color(0,1,1,1,1)
   w,h=blf.dimensions(0,text); blf.position(0,x+(right-x-w)/2,y+(top-y-h)/2,0); blf.draw(0,text)
  rects=bounds(context.region,s); lines=tooltip(owner,rects)
  if lines:
   scale=context.preferences.system.ui_scale; pad=10*scale; height=48*scale
   width=max(blf.dimensions(0,line)[0] for line in lines)+2*pad
   left=max(pad,min(rects[owner.hover_name][0],context.region.width-width-pad))
   top=min(r[1] for r in rects.values())-6*scale; bottom=top-height
   batch=batch_for_shader(shader,'TRI_FAN',{'pos':[(left,bottom),(left+width,bottom),(left+width,top),(left,top)]})
   shader.bind(); shader.uniform_float('color',(.035,.035,.035,.97)); batch.draw(shader)
   for i,line in enumerate(lines):
    blf.position(0,left+pad,top-(18+20*i)*scale,0); blf.draw(0,line)
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
 if adjust_ui.WATCH: adjust_ui.WATCH.hover_name=None
 if name=='close':
  s.adjust_enabled=False; s.adjust_toolbar_visible=False
  if s.running: s.cancel_requested=True
 elif name=='toggle':
  s.adjust_enabled=not s.adjust_enabled
  if not s.adjust_enabled and s.running: s.cancel_requested=True
 elif s.running: return
 elif name in {'PATH','KEEP_PATH'}: s.adjust_mode=name
 elif name=='settings': bpy.ops.faidlix_batch_clean_key.adjust_settings('INVOKE_DEFAULT')
 from . import ui
 ui.redraw(context)
