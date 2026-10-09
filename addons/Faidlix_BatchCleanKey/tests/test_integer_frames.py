import bpy,sys,os,importlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
addon=importlib.import_module(os.environ.get('BCK_TEST_MODULE','Faidlix_BatchCleanKey'))
if not hasattr(bpy.types.WindowManager,'faidlix_batch_clean_key'): addon.register()
for cls,names in [(addon.ui.BCK_PG_State,('flip_step','loop_step','sample_step')),
 (addon.ui.BCK_OT_Flip,('sample_step',)),(addon.ui.BCK_OT_Loop,('sample_step',)),
 (addon.compose_ui.BCK_OT_CombineSettings,('start','end','step','transition','source_start','source_end','position','duration'))]:
 for name in names:
  rna=cls.bl_rna if issubclass(cls,bpy.types.PropertyGroup) else getattr(bpy.ops.faidlix_batch_clean_key,cls.bl_idname.split('.')[1]).get_rna_type()
  prop=rna.properties[name]
  assert prop.type=='INT',(cls.__name__,name,prop.type)
  if name in {'flip_step','loop_step','sample_step','step','duration'}: assert prop.hard_min==1
  if name=='transition': assert prop.hard_min==0
  if name in {'start','end','source_start','source_end','position'}: assert prop.hard_min<0
a=bpy.data.actions.new('IntegerTimelineFractionalSource')
slot=a.slots.new('OBJECT','IntegerFixture')
bag=a.layers.new('Layer').strips.new(type='KEYFRAME').channelbag(slot,ensure=True)
c=bag.fcurves.new('location',index=0)
c.keyframe_points.insert(-2.25,0); c.keyframe_points.insert(6.75,1)
clip=addon.compose.Clip.from_action(a,-8.2,whole_frames=True)
assert (clip.source_start,clip.source_end,clip.start,clip.duration)==(-3,7,-8,10)
clip.resize('RIGHT',.6,whole_frames=True)
assert all(v==round(v) for v in (clip.start,clip.duration,clip.source_start,clip.source_end))
clip.resize('LEFT',-6.3,whole_frames=True)
copy=clip.duplicate()
assert all(v==round(v) for v in (copy.start,copy.duration,copy.source_start,copy.source_end))
assert clip.duration>=1 and copy.duration>=1
# Existing fractional animation Keys are not rounded or moved by UI setup.
assert [p.co.x for p in c.keyframe_points]==[-2.25,6.75]
print('INTEGER_FRAME_SETTINGS_PASS rotation mirror loop compose settings trim drag duplicate original_keys_untouched')
