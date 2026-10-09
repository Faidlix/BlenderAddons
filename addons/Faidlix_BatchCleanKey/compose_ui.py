"""Dedicated two-track window with draggable clips and isolated rig preview."""
import time
import math
import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from bpy.props import StringProperty, IntProperty, BoolProperty, EnumProperty, PointerProperty
from . import core, compose

SESSION = None
_draw_scale = 1.0


def ui_scale():
    return max(1.0, bpy.context.preferences.system.ui_scale)


def clip_text(left, bottom, right, top):
    blf.clipping(0, left*_draw_scale, bottom*_draw_scale, right*_draw_scale, top*_draw_scale)


class Session:
    def __init__(self, context):
        self.window, self.scene, self.obj = context.window, context.scene, context.object
        self.main = self.obj.animation_data.action
        bounds = core.actual_range(self.main)
        if bounds is None:
            raise ValueError('目前 Action 沒有 Key')
        self.tracks = [[compose.Clip.from_action(self.main,whole_frames=True)], []]
        candidates = [a for a in bpy.data.actions if a != self.main and core.actual_range(a) and core.slot_for(a, self.obj)]
        if candidates:
            self.tracks[1].append(compose.Clip.from_action(candidates[0], math.floor(bounds[0]),whole_frames=True))
        self.start, self.end, self.frame = math.floor(bounds[0]),math.ceil(bounds[1]),math.floor(bounds[0])
        self.name, self.step, self.transition = self.main.name+'_Combined', 1, 0
        self.custom = self.children = self.popup = False
        self.selected = {b.name for b in self.obj.pose.bones if b.select}
        self.collapsed, self.search, self.scroll = set(), '', 0
        self.active, self.drag = (0, 0), None
        self.play, self.last_time, self.message = None, time.monotonic(), ''
        self.worker, self.progress, self.result = None, 0, None
        self.closed = False
        self.preview_scene, self.preview_obj, self.preview_window = None, None, None
        self.objects, self.data = [], []
        self.handle = self.timer = None

    def make_preview(self):
        self.preview_scene = bpy.data.scenes.new('__BCK_ComposePreview')
        self.preview_scene.render.fps = self.scene.render.fps
        mapping = {}
        originals = [self.obj] + [o for o in self.scene.objects if o.type == 'MESH' and
                                 any(m.type == 'ARMATURE' and m.object == self.obj for m in o.modifiers)]
        for original in originals:
            copied = original.copy()
            self.objects.append(copied)
            if original.data:
                copied.data = original.data.copy()
                self.data.append(copied.data)
            copied.animation_data_clear()
            self.preview_scene.collection.objects.link(copied)
            copied.hide_viewport = False
            copied.hide_set(False, view_layer=self.preview_scene.view_layers[0])
            mapping[original] = copied
        for original, copied in mapping.items():
            world = original.matrix_world.copy()
            copied.parent = mapping.get(original.parent)
            copied.matrix_world = world
            # Output is local-channel composition; constraints are evaluated on the
            # isolated copied rig, with self-targets remapped and external targets fixed.
            for modifier in copied.modifiers:
                if modifier.type == 'ARMATURE':
                    modifier.object = mapping.get(modifier.object)
            constraints = list(copied.constraints)
            if copied.type == 'ARMATURE':
                constraints += [c for b in copied.pose.bones for c in b.constraints]
            for c in constraints:
                if hasattr(c, 'target') and c.target in mapping:
                    c.target = mapping[c.target]
            copied.select_set(False, view_layer=self.preview_scene.view_layers[0])
        self.preview_obj = mapping[self.obj]
        self.preview_scene.view_layers[0].objects.active = self.preview_obj
        self.preview_obj.select_set(True, view_layer=self.preview_scene.view_layers[0])

    def preview(self):
        if self.preview_obj:
            evaluator = compose.Evaluator(self.obj, self.tracks, self.selected, self.transition, self.custom)
            compose.set_values(self.preview_obj, evaluator.sample(self.frame, self.play or 'COMBINED'))
            self.preview_scene.view_layers[0].update()

    def bones(self):
        rows = []
        def walk(bone, depth):
            match = not self.search or self.search.casefold() in bone.name.casefold()
            if match:
                rows.append((bone, depth))
            if self.search or bone.name not in self.collapsed:
                for child in bone.children:
                    walk(child, depth+1)
        for b in self.obj.data.bones:
            if not b.parent:
                walk(b, 0)
        return rows

    def toggle_bone(self, bone):
        names = [bone.name] + ([b.name for b in bone.children_recursive] if self.children else [])
        selected = bone.name not in self.selected
        for name in names:
            self.selected.add(name) if selected else self.selected.discard(name)

    def close(self, close_window=True):
        global SESSION
        if self.closed:
            return
        self.closed = True
        if self.worker:
            self.worker.close()
            self.worker = None
        if self.handle:
            bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
            self.handle = None
        if self.timer:
            bpy.context.window_manager.event_timer_remove(self.timer)
            self.timer = None
        if close_window and self.preview_window in list(bpy.context.window_manager.windows):
            with bpy.context.temp_override(window=self.preview_window):
                self.preview_window.scene = self.scene
                bpy.ops.wm.window_close()
        for obj in self.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        if self.preview_scene:
            bpy.data.scenes.remove(self.preview_scene)
        for data in self.data:
            if data.users == 0:
                collection = bpy.data.armatures if isinstance(data, bpy.types.Armature) else bpy.data.meshes
                collection.remove(data)
        SESSION = None


class BCK_OT_CombineSettings(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.combine_settings'
    bl_label = '組合 Action 設定'
    name: StringProperty(name='新 Action 名稱')
    start: IntProperty(name='輸出開頭')
    end: IntProperty(name='輸出結尾')
    step: IntProperty(name='取樣間隔', default=1, min=1)
    transition: IntProperty(name='交接影格', default=0, min=0)
    custom: BoolProperty(name='包含骨骼自訂屬性')
    children: BoolProperty(name='勾選時包含子骨骼')
    search: StringProperty(name='搜尋骨骼')
    action: StringProperty(name='區塊 Action')
    source_start: IntProperty(name='來源開頭')
    source_end: IntProperty(name='來源結尾')
    position: IntProperty(name='區塊開頭')
    duration: IntProperty(name='區塊長度', default=1,min=1)
    mode: EnumProperty(name='長度模式', items=[('TRIM', '裁切', '保持播放速度'), ('RETIME', '變速', '縮放播放速度')], default='TRIM')

    def invoke(self, context, event):
        s = SESSION
        if not s or s.worker:
            return {'CANCELLED'}
        s.play, s.popup = None, True
        for name in ('name', 'start', 'end', 'step', 'transition', 'custom', 'children', 'search'):
            setattr(self, name, round(getattr(s,name)) if name in {'start','end','step','transition'} else getattr(s, name))
        track, index = s.active
        clip = s.tracks[track][index] if index < len(s.tracks[track]) else None
        self.action = clip.action.name if clip else ''
        if clip:
            self.source_start, self.source_end = round(clip.source_start),round(clip.source_end)
            self.position, self.duration, self.mode = round(clip.start),max(1,round(clip.duration)),clip.mode
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, context):
        col = self.layout
        col.prop(self, 'name')
        row = col.row(align=True)
        row.prop(self, 'start'); row.prop(self, 'end')
        row = col.row(align=True)
        row.prop(self, 'step'); row.prop(self, 'transition')
        col.prop_search(self, 'action', bpy.data, 'actions')
        row = col.row(align=True)
        row.prop(self, 'source_start'); row.prop(self, 'source_end')
        row = col.row(align=True)
        row.prop(self, 'position'); row.prop(self, 'duration')
        col.prop(self, 'mode', expand=True)
        col.prop(self, 'custom'); col.prop(self, 'children'); col.prop(self, 'search')
        col.label(text='裁切保持速度；變速將來源起訖縮放到區塊長度')

    def execute(self, context):
        s = SESSION
        if not s:
            return {'CANCELLED'}
        s.popup = False
        if self.end < self.start:
            self.report({'ERROR'}, '輸出結尾必須大於或等於開頭')
            return {'CANCELLED'}
        track, index = s.active
        try:
            if self.action:
                action = bpy.data.actions.get(self.action)
                if not action:
                    raise ValueError('Action 已不存在')
                bounds = core.actual_range(action)
                if not bounds:
                    raise ValueError('區塊 Action 沒有 Key')
                bounds=(math.floor(bounds[0]),math.ceil(bounds[1]))
                if index < len(s.tracks[track]) and s.tracks[track][index].action == action:
                    first, last = max(bounds[0], self.source_start), min(bounds[1], self.source_end)
                    if last < first:
                        raise ValueError('來源結尾必須大於或等於開頭')
                    clip = compose.Clip(action, first, last, self.position,
                                        max(1, last-first) if self.mode == 'TRIM' else self.duration, self.mode)
                    s.tracks[track][index] = clip
                else:
                    clip = compose.Clip.from_action(action, self.position,whole_frames=True)
                    if index < len(s.tracks[track]):
                        s.tracks[track][index] = clip
                    else:
                        s.tracks[track].append(clip)
            for name in ('name', 'start', 'end', 'step', 'transition', 'custom', 'children', 'search'):
                setattr(s, name, getattr(self, name))
            s.scroll = 0
            s.preview()
        except Exception as exc:
            s.message = str(exc)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        if SESSION:
            SESSION.popup = False


def rect(x, y, w, h, color):
    x, y, w, h = (v*_draw_scale for v in (x,y,w,h))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_FAN', {'pos': [(x,y), (x+w,y), (x+w,y+h), (x,y+h)]})
    shader.bind(); shader.uniform_float('color', color); batch.draw(shader)


def label(text, x, y, size=14, color=(.9,.9,.9,1)):
    blf.size(0, size*_draw_scale); blf.color(0, *color); blf.position(0, x*_draw_scale, y*_draw_scale, 0); blf.draw(0, str(text))


def draw_editor(session):
    global _draw_scale
    s = SESSION
    if not s or s.closed or bpy.context.window != s.preview_window:
        return
    _draw_scale = ui_scale()
    width, height = bpy.context.region.width/_draw_scale, bpy.context.region.height/_draw_scale
    session.hits = []
    def button(text, x, y, w, action, selected=False):
        rect(x, y, w, 28, (.18,.36,.65,1) if selected else (.18,.18,.18,1))
        label(text, x+7, y+8, 13)
        session.hits.append((x,y,w,28,action))
    panel_height = min(390, max(260, height*.52))
    right = max(380, width-280)
    rect(0, 0, width, panel_height, (.055,.055,.055,.98))
    label('組合 Action · '+s.name, 20, panel_height-28, 17)
    button(f'輸出 {s.start:g} — {s.end:g} / 設定', 20, panel_height-70, 290, ('SETTINGS',))
    button('產生新 Action', 320, panel_height-70, 140, ('BAKE',))
    button('取消 / Esc', 470, panel_height-70, 105, ('CANCEL',))
    x0, x1 = 155, right-20
    low = min(s.start, *(c.start for c in sum(s.tracks, [])))
    high = max(s.end, *(c.end for c in sum(s.tracks, [])))
    span = max(high-low, 1)
    session.mapping = (x0, x1, low, span)
    for track, title in enumerate(('主 Action', '組合 Action')):
        y = panel_height-150-track*95
        label(title, 20, y+28)
        button('▶' if s.play != ('MAIN' if track == 0 else 'LOWER') else '■', 20, y-3, 35, ('PLAY', 'MAIN' if track == 0 else 'LOWER'))
        button('設定', 60, y-3, 65, ('TRACK', track))
        rect(x0,y-5,x1-x0,46,(.10,.10,.10,1))
        for index, clip in enumerate(s.tracks[track]):
            left = x0+(clip.start-low)/span*(x1-x0)
            w = max(5, clip.duration/span*(x1-x0))
            selected = s.active == (track,index)
            rect(left, y, w, 33, (.22,.42,.7,1) if selected else (.23,.29,.38,1))
            rect(left,y,5,33,(.6,.65,.75,1)); rect(left+w-5,y,5,33,(.6,.65,.75,1))
            blf.enable(0, blf.CLIPPING); clip_text(left+6,y,left+w-6,y+33)
            label(f'{clip.action.name} [{clip.source_start:g}–{clip.source_end:g}]', left+8,y+10,12)
            blf.disable(0, blf.CLIPPING)
            session.hits.append((left,y,w,33,('CLIP',track,index)))
        label(f'{low:g}',x0,y-24,12); label(f'{high:g}',x1-35,y-24,12)
    play_x = x0+(s.frame-low)/span*(x1-x0)
    rect(play_x, panel_height-258, 2, 145, (.95,.4,.2,1))
    button('▶ 組合預覽' if s.play != 'COMBINED' else '■ 停止', 20, 40, 125, ('PLAY','COMBINED'))
    button('複製區塊',155,40,105,('DUPLICATE',))
    button('刪除區塊',270,40,105,('REMOVE',))
    track,index = s.active
    mode = s.tracks[track][index].mode if index < len(s.tracks[track]) else 'TRIM'
    button('裁切',385,40,65,('MODE','TRIM'),mode=='TRIM')
    button('變速',460,40,65,('MODE','RETIME'),mode=='RETIME')
    label(s.message or '拖曳區塊移動 · 拖曳兩端裁切/變速 · 時間軸空白處拖曳預覽',20,15,12)
    rect(right,80,width-right,panel_height-155,(.085,.085,.085,1))
    label(f'取代骨骼 {len(s.selected)}/{len(s.obj.pose.bones)}',right+10,panel_height-105,14)
    button('全選',right+10,panel_height-140,65,('BONES',True))
    button('不選',right+85,panel_height-140,65,('BONES',False))
    rows = s.bones()
    visible = max(1,int((panel_height-230)/24))
    s.scroll = min(s.scroll,max(0,len(rows)-visible))
    for row, (bone,depth) in enumerate(rows[s.scroll:s.scroll+visible]):
        y = panel_height-172-row*24
        x = right+10+min(depth,5)*12
        if bone.children:
            label('▸' if bone.name in s.collapsed else '▾',x,y,13)
            session.hits.append((x,y-4,16,22,('FOLD',bone.name)))
        label('☑' if bone.name in s.selected else '☐',x+17,y,15)
        blf.enable(0, blf.CLIPPING); clip_text(right,y-4,width-5,y+20)
        label(bone.name,x+38,y,12); blf.disable(0, blf.CLIPPING)
        session.hits.append((x+17,y-4,width-x-20,22,('BONE',bone.name)))
    if s.worker:
        rect(20,panel_height-105,max(0,right-40)*s.progress,8,(.25,.5,.85,1))
        label(f'批次處理 {s.progress:.0%} · Esc 取消',600,panel_height-62,13)


class BCK_OT_Combine(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.combine'
    bl_label = '組合 Action'
    bl_description = '在雙時間軸視窗裁切、移動與組合骨骼動畫；建立新 Action'

    @classmethod
    def poll(cls, context):
        obj = context.object
        return bool(not SESSION and obj and obj.type == 'ARMATURE' and obj.is_editable and
                    obj.animation_data and obj.animation_data.action)

    def invoke(self, context, event):
        global SESSION
        s = None
        try:
            s = Session(context)
            bpy.ops.ed.undo_push(message='組合 Action 前')
            s.make_preview()
            SESSION = s
            previous = set(context.window_manager.windows)
            bpy.ops.wm.window_new()
            s.preview_window = next(w for w in context.window_manager.windows if w not in previous)
            s.preview_window.scene = s.preview_scene
            area = max(s.preview_window.screen.areas, key=lambda a:a.width*a.height)
            area.type = 'VIEW_3D'
            with context.temp_override(window=s.preview_window, area=area):
                bpy.ops.screen.screen_full_area(use_hide_panels=True)
            area = next(a for a in s.preview_window.screen.areas if a.type == 'VIEW_3D')
            area.spaces.active.show_region_ui = False
            area.spaces.active.show_region_toolbar = False
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with context.temp_override(window=s.preview_window, area=area, region=region):
                bpy.ops.view3d.view_selected(use_all_regions=False)
                bpy.ops.faidlix_batch_clean_key.combine_editor('INVOKE_DEFAULT')
            s.preview()
            bpy.app.timers.register(watch_window, first_interval=.25)
        except Exception as exc:
            if s:
                s.close()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


def watch_window():
    s = SESSION
    if not s or s.closed:
        return None
    if s.preview_window not in list(bpy.context.window_manager.windows):
        s.close(False)
        return None
    if s.window not in list(bpy.context.window_manager.windows):
        s.close()
        return None
    return .25


class BCK_OT_CombineFinalize(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.combine_finalize'
    bl_label = '建立組合 Action'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        s = SESSION
        if not s or not s.result:
            return {'CANCELLED'}
        action = s.result
        ad = s.obj.animation_data_create()
        previous_action, previous_slot = ad.action, ad.action_slot
        previous_range = s.scene.frame_start, s.scene.frame_end
        try:
            core.assign_action(context, s.obj, action)
            core.sync_scene_range(s.scene, action)
            s.close()
            bpy.ops.ed.undo_push(message='建立組合 Action')
            self.report({'INFO'}, '已建立組合 Action：'+action.name)
        except Exception as exc:
            ad.action = previous_action
            if previous_action and previous_slot:
                ad.action_slot = previous_slot
            s.scene.frame_end = max(s.scene.frame_end, previous_range[1])
            s.scene.frame_start, s.scene.frame_end = previous_range
            bpy.data.actions.remove(action)
            s.close()
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class BCK_OT_CombineEditor(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.combine_editor'
    bl_label = 'Action 組合編輯器'
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        s = SESSION
        if not s:
            return {'CANCELLED'}
        s.hits, s.mapping = [], (155,500,s.start,max(1,s.end-s.start))
        s.handle = bpy.types.SpaceView3D.draw_handler_add(draw_editor,(s,),'WINDOW','POST_PIXEL')
        s.timer = context.window_manager.event_timer_add(.03,window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        s = SESSION
        if not s or s.closed:
            return {'CANCELLED'}
        if s.popup:
            return {'PASS_THROUGH'}
        if event.type == 'Z' and event.ctrl:
            s.message = '請先完成或取消組合視窗，再使用 Ctrl+Z'
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and (event.type in {'X','DEL','TAB','G','R','S'} or
                                      event.ctrl and event.type in {'O','N'}):
            s.message = '此視窗供動畫預覽；請完成或取消後再編輯場景'
            return {'RUNNING_MODAL'}
        if event.type == 'ESC' and event.value == 'PRESS':
            if s.worker:
                s.worker.close(); s.worker = None; s.message = '已取消，來源 Action 保留'; s.progress = 0
            else:
                s.close()
                return {'CANCELLED'}
        try:
            if event.type == 'TIMER':
                now = time.monotonic()
                if s.worker:
                    deadline = now+.008
                    while time.monotonic() < deadline:
                        try:
                            done,total = next(s.worker)
                            s.progress = done/max(total,1)
                        except StopIteration as finished:
                            s.result, s.worker = finished.value, None
                            s.play = None
                            def finalize():
                                if SESSION is s and s.window in list(bpy.context.window_manager.windows):
                                    with bpy.context.temp_override(window=s.window):
                                        bpy.ops.faidlix_batch_clean_key.combine_finalize()
                                return None
                            bpy.app.timers.register(finalize,first_interval=.01)
                            return {'FINISHED'}
                elif s.play:
                    fps = s.scene.render.fps/s.scene.render.fps_base
                    s.frame += (now-s.last_time)*fps
                    if s.frame > s.end:
                        s.frame = s.start
                    s.preview()
                s.last_time = now
                context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if s.worker:
                return {'RUNNING_MODAL'}
            scale = ui_scale()
            x,y = event.mouse_region_x/scale,event.mouse_region_y/scale
            x0,x1,low,span = s.mapping
            frame = round(low+(x-x0)/max(x1-x0,1)*span)
            if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'} and x >= context.region.width/scale-280:
                s.scroll = max(0,s.scroll+(-1 if event.type=='WHEELUPMOUSE' else 1)*3)
                context.area.tag_redraw(); return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                s.drag = None
            if event.type == 'MOUSEMOVE' and s.drag:
                kind,track,index,initial,origin = s.drag
                if kind == 'SCRUB':
                    s.frame = min(s.end,max(s.start,frame))
                else:
                    clip = s.tracks[track][index]
                    if kind == 'MOVE':
                        clip.start = initial + frame-origin
                    else:
                        clip.resize(kind,frame,whole_frames=True)
                s.preview(); context.area.tag_redraw(); return {'RUNNING_MODAL'}
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                hit = next((h for h in reversed(s.hits) if h[0]<=x<=h[0]+h[2] and h[1]<=y<=h[1]+h[3]),None)
                if hit:
                    action = hit[4]; kind = action[0]
                    if kind == 'CANCEL':
                        s.close(); return {'CANCELLED'}
                    if kind == 'SETTINGS':
                        bpy.ops.faidlix_batch_clean_key.combine_settings('INVOKE_DEFAULT')
                    elif kind == 'TRACK':
                        s.active = action[1],0
                        bpy.ops.faidlix_batch_clean_key.combine_settings('INVOKE_DEFAULT')
                    elif kind == 'PLAY':
                        s.play = None if s.play == action[1] else action[1]
                        s.last_time = time.monotonic(); s.preview()
                    elif kind == 'CLIP':
                        _,track,index = action
                        s.active = track,index
                        clip = s.tracks[track][index]
                        edge = 'LEFT' if x-hit[0] < 7 else 'RIGHT' if hit[0]+hit[2]-x < 7 else 'MOVE'
                        s.drag = edge,track,index,clip.start,frame
                        s.play = None
                    elif kind in {'DUPLICATE','REMOVE','MODE'}:
                        track,index = s.active
                        if index < len(s.tracks[track]):
                            if kind == 'DUPLICATE':
                                s.tracks[track].append(s.tracks[track][index].duplicate())
                                s.active = track,len(s.tracks[track])-1
                            elif kind == 'REMOVE':
                                if track == 0 and len(s.tracks[track]) == 1:
                                    s.message = '必須保留至少一個主 Action 區塊'
                                else:
                                    s.tracks[track].pop(index); s.active = track,max(0,index-1)
                            else:
                                s.tracks[track][index].mode = action[1]
                    elif kind == 'BONES':
                        s.selected = set(s.obj.pose.bones.keys()) if action[1] else set()
                    elif kind == 'BONE':
                        s.toggle_bone(s.obj.data.bones[action[1]])
                    elif kind == 'FOLD':
                        s.collapsed.symmetric_difference_update({action[1]})
                    elif kind == 'BAKE':
                        s.play = None
                        s.worker = compose.bake_steps(s.obj,s.tracks,s.selected,s.name,s.start,s.end,s.step,s.transition,s.custom)
                        s.message = ''
                    context.area.tag_redraw(); return {'RUNNING_MODAL'}
                if x0 <= x <= x1 and y < min(390,max(260,context.region.height/scale*.52))-110 and y > 100:
                    s.play = None; s.frame = min(s.end,max(s.start,frame))
                    s.drag = 'SCRUB',0,0,0,0
                    s.preview(); context.area.tag_redraw(); return {'RUNNING_MODAL'}
        except Exception as exc:
            if s.worker:
                s.worker.close(); s.worker = None
            s.message = str(exc)
            self.report({'ERROR'},str(exc))
        return {'PASS_THROUGH'}


CLASSES = (BCK_OT_CombineSettings,BCK_OT_Combine,BCK_OT_CombineFinalize,BCK_OT_CombineEditor)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    if SESSION:
        SESSION.close()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
