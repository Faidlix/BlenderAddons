"""Regression for native Vector loop seams; run Blender --background --python this_file.py.
BCK_TEST_MODULE optionally chooses an installed extension. Includes tiny and offset curves.
"""
import bpy,importlib,os,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
a=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'):a.register()
cases=[('down',10,1,-1),('up',-7,1,1),('tiny_down',0,1e-8,-1),('tiny_up',0,1e-8,1),('peak',4,1,0),('valley',-4,-1,0)]
for name,offset,amp,direction in cases:
 action=bpy.data.actions.new(name);slot=action.slots.new('OBJECT','Fixture')
 bag=action.layers.new('L').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
 curve=bag.fcurves.new('location',index=0)
 values=[offset,offset+direction*amp,offset-direction*3*amp,offset] if direction else [offset,offset-amp,offset-2*amp,offset]
 for f,v in zip((0,3,17,30),values):
  p=curve.keyframe_points.insert(f,v);p.interpolation='BEZIER';p.handle_left_type=p.handle_right_type='AUTO_CLAMPED'
 curve.modifiers.new('CYCLES');curve.update()
 old=[tuple(p.co) for p in curve.keyframe_points]
 a.ui.looping._close_curve(curve,0,30)
 p=curve.keyframe_points
 assert [tuple(x.co) for x in p]==old
 if direction:
  assert all(x.handle_left_type==x.handle_right_type=='VECTOR' for x in (p[0],p[-1])),name
  assert a.ui.looping._slope(p[0],'right')*direction>0,name
  assert a.ui.looping._slope(p[-1],'left')*direction>0,name
 else:
  assert abs(a.ui.looping._slope(p[0],'right'))<1e-7 and abs(a.ui.looping._slope(p[-1],'left'))<1e-7,name
print('LOOP_VECTOR_SEAMS_PASS rising falling offset tiny asymmetric extrema sparse')
