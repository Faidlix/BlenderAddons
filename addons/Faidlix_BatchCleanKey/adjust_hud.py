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


def ik_bounds(region,owner):
 scale=bpy.context.preferences.system.ui_scale
 visible=max(1,min(12,len(owner.names.split('|')),int((region.height/scale-180)/22)))
 width=min(460*scale,region.width-24*scale); height=(140+visible*22+(22 if len(owner.names.split('|'))>visible else 0))*scale
 left=max(8*scale,(region.width-width)/2); top=(region.height+height)/2
 bottom=top-height; gap=4*scale; padding=14*scale
 middle=left+width/2; y=bottom+38*scale
 return {'box':(left,bottom,left+width,top),'visible':visible,
         'AUTO':(left+padding,y,middle-gap,y+30*scale),
         'SELECTED':(middle+gap,y,left+width-padding,y+30*scale)}


def ik_hit(owner,x,y):
 for value,rect in ik_bounds(owner.region,owner).items():
  if value not in {'AUTO','SELECTED'}: continue
  left,bottom,right,top=rect
  if left<=x<=right and bottom<=y<=top: return value
 return None


def draw_ik(owner):
 context=bpy.context
 if context.area!=owner.area or context.region!=owner.region: return
 rects=ik_bounds(context.region,owner); left,bottom,right,top=rects['box']
 scale=context.preferences.system.ui_scale; padding=14*scale
 shader=gpu.shader.from_builtin('UNIFORM_COLOR'); gpu.state.blend_set('ALPHA')
 try:
  def rect(bounds,color):
   x,y,r,t=bounds; shader.bind(); shader.uniform_float('color',color)
   batch_for_shader(shader,'TRI_FAN',{'pos':[(x,y),(r,y),(r,t),(x,t)]}).draw(shader)
  def label(text,x,y,size=13):
   blf.size(0,int(size*scale)); blf.color(0,1,1,1,1)
   while len(text)>3 and blf.dimensions(0,text)[0]>right-left-2*padding: text=text[:-2]+'…'
   blf.position(0,x,y,0); blf.draw(0,text)
  rect((left-2*scale,bottom-2*scale,right+2*scale,top+2*scale),(.28,.28,.28,1))
  rect(rects['box'],(.055,.055,.055,1))
  label('多影格同步調整：未選取的 IK 控制骨',left+padding,top-26*scale,14)
  rect((left+padding,top-38*scale,right-padding,top-37*scale),(.23,.23,.23,1))
  label('IK Target／Pole 未選取，或沒有選到 Key：',left+padding,top-61*scale)
  names=owner.names.split('|'); start=min(owner.scroll,max(0,len(names)-rects['visible']))
  for i,name in enumerate(names[start:start+rects['visible']]):
   label(name,left+padding,top-(87+i*22)*scale)
  if len(names)>rects['visible']:
   label(f'滾輪查看：{start+1}–{min(len(names),start+rects["visible"])}/{len(names)}',left+padding,bottom+77*scale,11)
  for value,text in (('AUTO','自動加入'),('SELECTED','維持原選取')):
   r=rects[value]; hover=owner.hovered==value and owner.ready
   rect(r,(.29,.29,.29,1) if hover else (.19,.19,.19,1))
   blf.size(0,int(14*scale)); w,h=blf.dimensions(0,text)
   label(text,r[0]+(r[2]-r[0]-w)/2,r[1]+(r[3]-r[1]-h)/2,14)
  label('點選後請重新開始 G／R／S；Esc 關閉',left+padding,bottom+15*scale,12)
 finally: gpu.state.blend_set('NONE')
