import time
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from . import core, automatic, mirror

ADDON_VERSION = '1.3.2'
_sync_signature = None
_refreshing = False


def browser_changed(state, context):
    if _refreshing or state.running or not 0 <= state.browser_index < len(state.browser):
        return
    action = state.browser[state.browser_index].action
    obj = rig(context)
    if obj and action:
        try:
            core.assign_action(context, obj, action)
            core.sync_scene_range(context.scene, action)
            for item in state.browser:
                item.selected = item.action == action
            redraw(context)
        except ValueError:
            pass


def redraw(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def rig(context):
    obj = context.object
    return obj if obj and obj.type == 'ARMATURE' else None


def bone_get(item):
    obj = item.armature
    bone = obj.pose.bones.get(item.name) if obj else None
    return bool(bone and bone.select)


def bone_set(item, value):
    obj = item.armature
    if obj and obj.mode == 'POSE' and obj.is_editable:
        bone = obj.pose.bones.get(item.name)
        if bone:
            bone.select = value
            if value:
                obj.data.bones.active = bone.bone
            update_counts(bpy.context.window_manager.faidlix_batch_clean_key)
            redraw(bpy.context)


class BCK_PG_Action(bpy.types.PropertyGroup):
    action: PointerProperty(type=bpy.types.Action)
    selected: BoolProperty(default=False)
    keys: IntProperty()
    status: StringProperty()


class BCK_PG_Bone(bpy.types.PropertyGroup):
    name: StringProperty()
    armature: PointerProperty(type=bpy.types.Object)
    selected: BoolProperty(get=bone_get, set=bone_set)


class BCK_PG_State(bpy.types.PropertyGroup):
    actions: CollectionProperty(type=BCK_PG_Action)
    browser: CollectionProperty(type=BCK_PG_Action)
    bones: CollectionProperty(type=BCK_PG_Bone)
    armature: PointerProperty(type=bpy.types.Object)
    active_index: IntProperty()
    browser_index: IntProperty(update=browser_changed)
    bone_index: IntProperty()
    anchor: IntProperty(default=-1)
    show_bones: BoolProperty(name='骨骼清單', default=False)
    show_actions: BoolProperty(name='批次 Action 清單', default=True)
    show_browser: BoolProperty(name='Action 清單', default=True)
    operation: EnumProperty(items=[('DELETE', 'Delete 刪除', '刪除所選骨骼全部 Key'),
                                   ('CLEAN', 'Clean 清理', 'Blender 原生 Clean'),
                                   ('DECIMATE', 'Decimate 縮減', 'Blender 原生 Decimate')], default='CLEAN')
    reset_bones: BoolProperty(name='完整重設所選骨骼（位置、旋轉、縮放）', default=True)
    threshold: FloatProperty(name='清理閾值', default=0.001, min=0.0, precision=5)
    decimate_mode: EnumProperty(items=[('RATIO', '比例', '依比例移除 Key'), ('ERROR', '誤差', '限制曲線誤差')])
    ratio: FloatProperty(name='移除比例', default=0.5, min=0, max=1, subtype='FACTOR')
    error: FloatProperty(name='最大誤差', default=0.01, min=0, precision=5)
    last_result: StringProperty()
    running: BoolProperty(default=False)
    pending: BoolProperty(default=False)
    cancel_requested: BoolProperty(default=False)
    progress: FloatProperty(min=0, max=1, subtype='FACTOR')
    progress_text: StringProperty()
    rotation_job: BoolProperty(default=False)
    automatic_rotation: BoolProperty(default=False)
    flip_job: BoolProperty(default=False)
    flip_action: PointerProperty(type=bpy.types.Action)
    flip_mode: StringProperty(default='COPY')
    flip_step: IntProperty(default=1,min=1)
    loop_job: BoolProperty(default=False)
    loop_action: PointerProperty(type=bpy.types.Action)
    loop_smooth: BoolProperty(default=True)
    loop_step: IntProperty(default=1, min=1)
    rotation_target: EnumProperty(name='轉換方向', items=[('XYZ', 'Quaternion → XYZ Euler', ''),
                    ('QUATERNION', 'XYZ Euler → Quaternion', '')])
    sample_step: IntProperty(name='烘焙間隔（影格）', default=1, min=1, max=100)


def update_counts(state):
    obj = state.armature
    if not obj:
        return
    names = [b.name for b in state.bones if b.selected]
    for item in state.actions:
        if item.action:
            item.keys = sum(len(c.keyframe_points) for c in core.target_curves(item.action, obj, names))
            item.status = ('唯讀' if not item.action.is_editable else
                           'Slot 不明確' if item.action.slots and not core.slot_for(item.action, obj) else '')


def refresh(context, reset=False):
    global _refreshing
    state = context.window_manager.faidlix_batch_clean_key
    if state.running:
        return state
    obj = rig(context)
    changed_rig = state.armature != obj
    if changed_rig:
        state.armature = obj
    names = [b.name for b in obj.pose.bones] if obj else []
    if changed_rig or [b.name for b in state.bones] != names:
        state.bones.clear()
        for name in names:
            item = state.bones.add()
            item.name, item.armature = name, obj
    actions = sorted(bpy.data.actions, key=lambda a: a.name.casefold())
    changed_actions = ([i.action for i in state.actions] != actions or
                       [i.action for i in state.browser] != actions)
    if changed_actions or reset:
        selected = {i.action for i in state.actions if i.selected}
        state.actions.clear()
        state.browser.clear()
        current = obj.animation_data.action if obj and obj.animation_data else None
        for action in actions:
            item = state.actions.add()
            item.action = action
            item.selected = action == current if reset else action in selected
            state.browser.add().action = action
        if reset:
            state.active_index = next((i for i, item in enumerate(state.actions) if item.selected), 0)
            state.anchor = state.active_index if any(i.selected for i in state.actions) else -1
        else:
            state.anchor = -1
    current = obj.animation_data.action if obj and obj.animation_data else None
    _refreshing = True
    state.browser_index = -1
    for i, item in enumerate(state.browser):
        item.selected = item.action == current
        if item.selected:
            state.browser_index = i
    _refreshing = False
    update_counts(state)
    return state


def populate(context):
    return refresh(context, reset=True)


def sync_timer():
    global _sync_signature
    try:
        if not hasattr(bpy.types.WindowManager, 'faidlix_batch_clean_key'):
            return None
        state = refresh(bpy.context)
        signature = (state.armature.as_pointer() if state.armature else 0,
                     tuple((b.name, b.selected) for b in state.bones),
                     tuple((i.action.as_pointer() if i.action else 0, i.keys, i.selected) for i in state.actions),
                     state.browser_index)
        if signature != _sync_signature:
            _sync_signature = signature
            redraw(bpy.context)
    except (ReferenceError, RuntimeError, AttributeError):
        pass
    return 0.3


class BCK_OT_Select(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.select'
    bl_label = '選取 Action'
    bl_description = '單擊單選；Ctrl 增減選；Shift 範圍；Ctrl+Shift 加入範圍'
    bl_options = {'INTERNAL'}
    index: IntProperty()

    def invoke(self, context, event):
        state = context.window_manager.faidlix_batch_clean_key
        state.anchor = core.choose(state.actions, self.index, state.anchor, event.ctrl, event.shift)
        state.active_index = self.index
        redraw(context)
        return {'FINISHED'}


class BCK_OT_SelectAll(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.select_all'
    bl_label = 'Action 全選'
    bl_options = {'INTERNAL'}
    value: BoolProperty(default=True)

    def execute(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        for item in state.actions:
            item.selected = self.value
        state.anchor = -1
        redraw(context)
        return {'FINISHED'}


class BCK_UL_Bones(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.prop(item, 'selected', text=item.name)


class BCK_OT_BonesAll(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.bones_all'
    bl_label = '骨骼全選／取消全選'
    bl_options = {'INTERNAL'}
    value: BoolProperty(default=True)

    def execute(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        obj = state.armature
        if not obj or obj.mode != 'POSE' or state.running or state.pending:
            return {'CANCELLED'}
        for bone in obj.pose.bones:
            bone.select = self.value
        update_counts(state)
        redraw(context)
        return {'FINISHED'}


class BCK_UL_Actions(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.operator_context = 'INVOKE_DEFAULT'
        row = layout.row(align=True)
        op = row.operator('faidlix_batch_clean_key.select', text=item.action.name if item.action else '已刪除',
                          icon='CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT', depress=item.selected)
        op.index = index
        row.label(text=f'{item.keys} Keys' + (f' ({item.status})' if item.status else ''))

    def draw_filter(self, context, layout):
        pass


class BCK_UL_Browser(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        action = item.action
        if not action:
            return
        layout.operator_context = 'INVOKE_DEFAULT'
        row = layout.row(align=True)
        row.operator('faidlix_batch_clean_key.switch', text='', depress=item.selected,
                     icon='RADIOBUT_ON' if item.selected else 'RADIOBUT_OFF').action_name = action.name
        row.prop(action, 'name', text='', emboss=False)
        row.operator('faidlix_batch_clean_key.delete_action', text='', icon='TRASH').action_name = action.name
        row.operator('faidlix_batch_clean_key.loop', text='', icon='FILE_REFRESH').action_name = action.name
        row.operator('faidlix_batch_clean_key.duplicate', text='', icon='DUPLICATE').action_name = action.name
        row.operator('faidlix_batch_clean_key.flip', text='', icon='MOD_MIRROR').action_name = action.name

    def draw_filter(self, context, layout):
        pass


def fold(layout, state, prop, title):
    row = layout.row()
    row.prop(state, prop, text=title, emboss=False,
             icon='TRIA_DOWN' if getattr(state, prop) else 'TRIA_RIGHT')
    return getattr(state, prop)


def draw_bones(layout, state):
    count = sum(b.selected for b in state.bones)
    if fold(layout, state, 'show_bones', f'骨架：{state.armature.name if state.armature else "無"} ｜ 骨骼 {count}/{len(state.bones)}'):
        row = layout.row(align=True)
        row.operator('faidlix_batch_clean_key.bones_all', text='全選骨骼').value = True
        row.operator('faidlix_batch_clean_key.bones_all', text='取消全選骨骼').value = False
        layout.template_list('BCK_UL_Bones', '', state, 'bones', state, 'bone_index', rows=5, maxrows=5)


def draw_progress(layout, state):
    if state.running:
        layout.progress(factor=state.progress, type='BAR', text=f'批次處理 {state.progress:.0%}')
        layout.label(text=state.progress_text)
        layout.label(text='Esc 取消；完成後才寫回動畫')


class BCK_OT_Cancel(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.cancel'
    bl_label = '取消批次處理'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.window_manager.faidlix_batch_clean_key.cancel_requested = True
        return {'FINISHED'}


def launch_batch(context):
    """Finish the parent dialog before installing the worker's modal handler."""
    state = context.window_manager.faidlix_batch_clean_key
    if state.pending or state.running:
        return {'CANCELLED'}
    window, area = context.window, context.area
    state.pending = True
    def start():
        current = bpy.context.window_manager.faidlix_batch_clean_key
        current.pending = False
        try:
            if window not in bpy.context.window_manager.windows[:] or area not in window.screen.areas[:]:
                raise ValueError('原編輯器已關閉，請重新啟動批次處理')
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.faidlix_batch_clean_key.run('INVOKE_DEFAULT')
        except Exception as exc:
            current.last_result = f'未完成：{exc}'
            redraw(bpy.context)
        return None
    bpy.app.timers.register(start, first_interval=0.05)
    return {'FINISHED'}


class BCK_OT_Batch(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.batch'
    bl_label = 'Faidlix_BatchCleanKey'

    @classmethod
    def poll(cls, context):
        return bool(rig(context) and context.object.mode == 'POSE' and
                    not context.window_manager.faidlix_batch_clean_key.running and
                    not context.window_manager.faidlix_batch_clean_key.pending)

    def invoke(self, context, event):
        populate(context)
        state = context.window_manager.faidlix_batch_clean_key
        state.loop_job = False
        state.flip_job = False
        state.automatic_rotation = False
        state.rotation_job = False
        return context.window_manager.invoke_props_dialog(self, width=700, confirm_text='執行')

    def draw_selection(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        layout = self.layout
        draw_bones(layout, state)
        if fold(layout, state, 'show_actions', '批次 Action 清單'):
            layout.label(text='單擊單選 ｜ Ctrl 增減選 ｜ Shift 範圍 ｜ Ctrl+Shift 加入範圍')
            row = layout.row(align=True)
            row.operator('faidlix_batch_clean_key.select_all', text='全選所有 Action').value = True
            row.operator('faidlix_batch_clean_key.select_all', text='取消全選').value = False
            layout.template_list('BCK_UL_Actions', '', state, 'actions', state, 'active_index', rows=8, maxrows=8)
        chosen = [i for i in state.actions if i.selected]
        layout.label(text=f'已選 {len(chosen)}/{len(state.actions)} Actions ｜ {sum(i.keys for i in chosen)} Keys')

    def draw(self, context):
        BCK_OT_Batch.draw_selection(self, context)
        state = context.window_manager.faidlix_batch_clean_key
        layout = self.layout
        layout.prop(state, 'operation', expand=True)
        if state.operation == 'CLEAN':
            layout.prop(state, 'threshold')
        elif state.operation == 'DECIMATE':
            layout.prop(state, 'decimate_mode', expand=True)
            layout.prop(state, 'ratio' if state.decimate_mode == 'RATIO' else 'error')
        else:
            layout.prop(state, 'reset_bones')
            layout.label(text='刪除勾選骨骼的全部 Key；保留 Action 與其他骨骼', icon='ERROR')
        layout.label(text='共用 Action 會影響其他使用者；鎖定與唯讀資料略過。Ctrl+Z 復原。')

    def execute(self, context):
        # Synchronous execution is useful to scripts; user confirmation launches modal progress.
        state = context.window_manager.faidlix_batch_clean_key
        state.rotation_job = False
        if bpy.app.background:
            state.loop_job = False
            return run_sync(self, context)
        return launch_batch(context)


def batch_args(context):
    state = context.window_manager.faidlix_batch_clean_key
    if state.rotation_job:
        obj=rig(context)
        if not obj: raise ValueError('目前沒有骨架')
        names=[b.name for b in obj.pose.bones]
        source='rotation_quaternion' if state.rotation_target=='XYZ' else 'rotation_euler'
        paths={obj.pose.bones[n].path_from_id()+'.'+source for n in names}
        actions=[a for a in bpy.data.actions if core.slot_for(a,obj) and any(c.data_path in paths and core.rotation_has_data(c) for c in core.target_curves(a,obj,names))]
        return (context,obj,names,actions,state.operation,state.threshold,state.decimate_mode,state.ratio,state.error)
    obj = state.armature
    if not obj or obj != context.object or obj.mode != 'POSE':
        raise ValueError('骨架或模式已變更，請重新開啟工具')
    names = [b.name for b in state.bones if b.selected]
    actions = [i.action for i in state.actions if i.selected and i.action]
    if not names or not actions:
        raise ValueError('請至少選取一個骨骼與 Action')
    if state.operation == 'DELETE' and state.reset_bones and not obj.is_editable:
        raise ValueError('目前骨架為唯讀，無法重設變換')
    return (context, obj, names, actions, state.operation, state.threshold,
            state.decimate_mode, state.ratio, state.error)


def result_text(result):
    if 'flip_action' in result:
        return '已翻轉 Action：'+result['flip_action']
    if 'loop_action' in result:
        return '已建立烘焙循環副本：' + result['loop_action']
    if 'samples' in result:
        return f'{result["actions"]} Actions，{result["bones"]} 骨骼，{result["samples"]} 旋轉取樣'
    return f'{result["actions"]} Actions，移除 {result["removed"]} Keys，略過 {result["skipped"]} 項'


def processing_steps(context):
    state=context.window_manager.faidlix_batch_clean_key
    if state.flip_job:
        return mirror.steps(context,rig(context),state.flip_action,state.flip_mode,state.flip_step)
    state = context.window_manager.faidlix_batch_clean_key
    if state.loop_job:
        action, obj = state.loop_action, rig(context)
        if not action or not obj or not obj.is_editable:
            raise ValueError('請選取可編輯骨架與 Action')
        def loop_steps():
            copied = yield from core.loop_copy_steps(action,obj,state.loop_smooth,state.loop_step)
            try:
                core.assign_action(context,obj,copied)
                core.sync_scene_range(context.scene,copied)
            except Exception:
                bpy.data.actions.remove(copied)
                raise
            return {'loop_action':copied.name}
        return loop_steps()
    args = batch_args(context)
    if state.rotation_job:
        if state.automatic_rotation:
            return automatic.rotation_steps(*args[:4],state.rotation_target,state.sample_step)
        return automatic.rotation_steps(*args[:4], state.rotation_target, state.sample_step)
    def steps():
        result = yield from core.process_steps(*args)
        if state.operation == 'DELETE' and state.reset_bones:
            core.reset_pose(args[1], args[2])
        return result
    return steps()


def run_sync(operator, context):
    try:
        steps = processing_steps(context)
        while True:
            try:
                next(steps)
            except StopIteration as done:
                result = done.value
                break
    except Exception as exc:
        context.window_manager.faidlix_batch_clean_key.loop_job = False
        operator.report({'ERROR'}, str(exc))
        return {'CANCELLED'}
    state = context.window_manager.faidlix_batch_clean_key
    state.last_result = result_text(result)
    state.loop_job = False
    state.flip_job = False
    operator.report({'INFO'}, state.last_result)
    update_counts(state)
    return {'FINISHED'}


class BCK_OT_Run(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.run'
    bl_label = '批次處理 Action Keys'
    bl_options = {'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        self._timer = self._draw_handle = None
        try:
            self._steps = processing_steps(context)
            # Validation happens before locking UI.
            state = context.window_manager.faidlix_batch_clean_key
            if state.running:
                return {'CANCELLED'}
            state.running, state.progress, state.cancel_requested = True, 0, False
            state.progress_text = '準備處理…'
            self._last_tick = 0
            self._timer = context.window_manager.event_timer_add(0.05, window=context.window)
            context.window_manager.modal_handler_add(self)
            context.window_manager.progress_begin(0, 1)
            self._area = context.area
            self._space_type = type(context.space_data)
            self._draw_handle = self._space_type.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
            redraw(context)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            try:
                if hasattr(self, '_steps'):
                    self._steps.close()
            finally:
                self.finish(context)
            return {'CANCELLED'}

    def draw_overlay(self):
        if bpy.context.area != self._area:
            return
        import blf
        import gpu
        from gpu_extras.batch import batch_for_shader
        state = bpy.context.window_manager.faidlix_batch_clean_key
        width = min(560, max(240, bpy.context.region.width - 60))
        x, y = (bpy.context.region.width - width) / 2, max(20, bpy.context.region.height - 115)
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        def rect(x0, y0, w, h, color):
            batch = batch_for_shader(shader, 'TRIS', {'pos': [(x0,y0), (x0+w,y0),
                    (x0+w,y0+h), (x0,y0+h)]}, indices=[(0,1,2),(0,2,3)])
            shader.bind()
            shader.uniform_float('color', color)
            batch.draw(shader)
        gpu.state.blend_set('ALPHA')
        rect(x-12, y-12, width+24, 92, (0.06,0.06,0.06,0.95))
        rect(x, y+20, width, 12, (0.2,0.2,0.2,1))
        rect(x, y+20, width*state.progress, 12, (0.15,0.45,0.85,1))
        blf.size(0, 16)
        blf.color(0, 1,1,1,1)
        blf.position(0, x, y+52, 0)
        blf.draw(0, f'批次處理 {state.progress:.0%} ｜ Esc 取消')
        rect(x+width-72, y+43, 72, 28, (0.45,0.12,0.12,1))
        blf.position(0, x+width-61, y+52, 0)
        blf.draw(0, '取消')
        blf.position(0, x, y, 0)
        blf.draw(0, state.progress_text)
        gpu.state.blend_set('NONE')

    def finish(self, context):
        try:
            if self._draw_handle is not None:
                self._space_type.draw_handler_remove(self._draw_handle, 'WINDOW')
        finally:
            try:
                if self._timer is not None:
                    context.window_manager.event_timer_remove(self._timer)
            finally:
                context.window_manager.progress_end()
                state = context.window_manager.faidlix_batch_clean_key
                state.running = state.pending = state.cancel_requested = False
                state.loop_job = False
                state.flip_job = False
                refresh(context)
                redraw(context)

    def modal(self, context, event):
        state = context.window_manager.faidlix_batch_clean_key
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            region = next(r for r in self._area.regions if r.type == 'WINDOW')
            width = min(560, max(240, region.width - 60))
            x, y = (region.width-width)/2, max(20, region.height-115)
            mx, my = event.mouse_x-region.x, event.mouse_y-region.y
            if x+width-72 <= mx <= x+width and y+43 <= my <= y+71:
                state.cancel_requested = True
        if event.type == 'ESC' or state.cancel_requested:
            try:
                self._steps.close()
                state.last_result = '已取消，原動畫保留'
            finally:
                self.finish(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        # Other editor timers and queued timer events must not monopolize the UI.
        now = time.perf_counter()
        if now - self._last_tick < 0.04:
            return {'RUNNING_MODAL'}
        self._last_tick = now
        try:
            deadline = time.perf_counter() + 0.008
            while True:
                done, total, name = next(self._steps)
                if time.perf_counter() >= deadline:
                    break
            # Publish once per tick, rather than issuing thousands of RNA/UI
            # updates per second and building a timer/keyboard event backlog.
            state.progress = min(0.99, done / max(1, total))
            unit = '取樣' if state.rotation_job or state.loop_job else '通道'
            state.progress_text = f'{name} ｜ {done}/{total} {unit}'
            context.window_manager.progress_update(state.progress)
        except StopIteration as done:
            state.progress = 1
            state.last_result = result_text(done.value)
            self.report({'INFO'}, state.last_result)
            self.finish(context)
            return {'FINISHED'}
        except Exception as exc:
            try:
                self._steps.close()
                state.last_result = f'已取消：{exc}' if state.automatic_rotation else f'未完成：{exc}'
                self.report({'INFO'} if state.automatic_rotation else {'ERROR'}, state.last_result)
            finally:
                self.finish(context)
            return {'CANCELLED'}
        redraw(context)
        return {'RUNNING_MODAL'}


class BCK_OT_Switch(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.switch'
    bl_label = '切換 Action'
    bl_options = {'UNDO'}
    action_name: StringProperty()

    def execute(self, context):
        obj, action = rig(context), bpy.data.actions.get(self.action_name)
        if not obj or not action:
            return {'CANCELLED'}
        try:
            core.assign_action(context, obj, action)
            core.sync_scene_range(context.scene, action)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        refresh(context)
        redraw(context)
        return {'FINISHED'}


class BCK_OT_Rotation(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.rotation'
    bl_label = '批次轉換旋轉 Key'
    @classmethod
    def poll(cls,context):
        state=context.window_manager.faidlix_batch_clean_key
        return bool(rig(context) and not state.running and not state.pending)

    def invoke(self, context, event):
        return self.execute(context)

    def execute(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        state.rotation_job=True
        state.loop_job=state.flip_job=False
        state.automatic_rotation=True
        try:
            args=batch_args(context)
            actions,issues,failures=automatic.inspect(args[1],args[2],args[3],state.rotation_target)
            if failures: raise ValueError('；'.join(failures))
        except Exception as exc:
            state.rotation_job=False
            state.last_result='已取消：'+str(exc)
            self.report({'INFO'},state.last_result)
            return {'CANCELLED'}
        return run_sync(self,context) if bpy.app.background else launch_batch(context)


class BCK_OT_Loop(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.loop'
    bl_label = '銜接 Action 頭尾循環'
    bl_description = '以最長曲線起訖補齊較短曲線，尾端接回開頭'
    bl_options = {'UNDO'}
    action_name: StringProperty()
    smooth: BoolProperty(name='銜接頭尾斜率', default=True)
    bake_copy: BoolProperty(name='建立烘焙／解鎖循環副本', default=False)
    sample_step: IntProperty(name='烘焙間隔',default=1,min=1)

    def invoke(self, context, event):
        try:
            action = bpy.data.actions.get(self.action_name)
            curves, start, end = core.loop_curves(action, rig(context))
            self._summary = f'{len(curves)} 曲線 ｜ 起始 {start:g} ｜ 結束 {end:g}'
        except Exception as exc:
            if not action or not core.actual_range(action):
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.bake_copy = True
            self._summary = str(exc)
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text='建立循環')

    def draw(self, context):
        self.layout.label(text=self.action_name)
        self.layout.label(text=getattr(self, '_summary', ''))
        self.layout.prop(self, 'smooth')
        self.layout.prop(self, 'bake_copy')
        if self.bake_copy:
            self.layout.prop(self,'sample_step')
            self.layout.label(text='保留來源，副本烘焙修飾器／取樣資料，解除鎖定並啟用停用曲線')
        self.layout.label(text='較短曲線補頭尾 Key；尾端值改成開頭值')
        self.layout.label(text='銜接斜率會調整接縫控制柄及鄰接段插值；Ctrl+Z 復原')

    def execute(self, context):
        if self.bake_copy:
            state = context.window_manager.faidlix_batch_clean_key
            state.loop_job, state.rotation_job = True, False
            state.flip_job=False
            state.loop_action = bpy.data.actions.get(self.action_name)
            state.loop_smooth, state.loop_step = self.smooth, self.sample_step
            return run_sync(self,context) if bpy.app.background else launch_batch(context)
        try:
            action = bpy.data.actions.get(self.action_name)
            count, added, start, end = core.make_loop(action, rig(context), self.smooth)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'{count} 曲線，新增 {added} Keys，循環 {start:g}–{end:g}')
        refresh(context)
        redraw(context)
        return {'FINISHED'}


class BCK_OT_New(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.new'
    bl_label = '新增 Action'
    bl_options = {'UNDO'}

    def execute(self, context):
        obj = rig(context)
        if not obj or not obj.is_editable:
            return {'CANCELLED'}
        action = bpy.data.actions.new('New Action')
        action.use_fake_user = True
        core.assign_action(context, obj, action)
        refresh(context)
        redraw(context)
        return {'FINISHED'}


class BCK_OT_Delete(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.delete_action'
    bl_label = '刪除 Action'
    bl_description = '刪除目前 Action 資料；共用者也會解除連結；Ctrl+Z 復原'
    bl_options = {'UNDO'}
    action_name: StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = rig(context)
        action = bpy.data.actions.get(self.action_name) if self.action_name else (obj.animation_data.action if obj and obj.animation_data else None)
        if not action or not action.is_editable:
            return {'CANCELLED'}
        bpy.data.actions.remove(action, do_unlink=True)
        refresh(context)
        redraw(context)
        return {'FINISHED'}


class BCK_OT_Duplicate(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.duplicate'
    bl_label = '複製 Action'
    bl_options = {'UNDO'}
    action_name: StringProperty()

    def execute(self, context):
        source, obj = bpy.data.actions.get(self.action_name), rig(context)
        if not source or not obj:
            return {'CANCELLED'}
        copy = source.copy()
        copy.name = source.name + '_Copy'
        copy.use_fake_user = True
        try:
            core.assign_action(context, obj, copy)
        except ValueError as exc:
            bpy.data.actions.remove(copy)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        refresh(context)
        redraw(context)
        return {'FINISHED'}


class BCK_OT_Flip(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.flip'
    bl_label = '左右翻轉 Action'
    bl_options = {'UNDO'}
    action_name: StringProperty()
    sample_step: IntProperty(name='烘焙間隔（影格）',default=1,min=1,max=100)
    mode: EnumProperty(items=[('COPY', '建立翻轉副本', '保留原 Action'),
                              ('IN_PLACE', '修改原 Action', '原 Action 的所有使用者都會受到影響')], default='COPY')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text='翻轉')

    def draw(self, context):
        self.layout.label(text=self.action_name)
        self.layout.prop(self, 'mode', expand=True)
        self.layout.prop(self, 'sample_step')
        self.layout.label(text='以骨架 X 軸翻轉，依 Blender 左右骨骼名稱配對')
        self.layout.label(text='依骨骼靜止軸向換算；保留原 Key 時間並加入間隔取樣')

    def execute(self, context):
        source, obj = bpy.data.actions.get(self.action_name), rig(context)
        if not source or not obj:
            return {'CANCELLED'}
        state=context.window_manager.faidlix_batch_clean_key
        state.flip_job=True; state.loop_job=False; state.rotation_job=False
        state.flip_action=source; state.flip_mode=self.mode; state.flip_step=self.sample_step
        return run_sync(self,context) if bpy.app.background else launch_batch(context)


class BCK_OT_Ranges(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.sync_ranges'
    bl_label = '同步所有 Action 影格範圍'
    bl_options = {'UNDO'}

    def execute(self, context):
        changed, skipped = core.sync_ranges(list(bpy.data.actions))
        self.report({'INFO'}, f'同步 {changed} Actions，略過 {skipped} 個空白／唯讀 Action')
        redraw(context)
        return {'FINISHED'}


class _Panel:
    bl_label = 'Faidlix_BatchCleanKey'
    bl_region_type = 'UI'
    bl_category = 'Faidlix'

    def draw_header_preset(self, context):
        row = self.layout.row()
        row.alignment = 'RIGHT'
        row.label(text=ADDON_VERSION)

    def draw(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        layout = self.layout
        draw_progress(layout, state)
        col = layout.column()
        col.enabled = not state.running and not state.pending
        if self.bl_space_type == 'VIEW_3D':
            row = col.row(align=True)
            row.enabled = bool(rig(context))
            row.operator('faidlix_batch_clean_key.new', icon='ADD')
            row.operator('faidlix_batch_clean_key.combine', text='組合 Action', icon='NLA')
            if fold(col, state, 'show_browser', 'Action 清單'):
                col.template_list('BCK_UL_Browser', '', state, 'browser', state, 'browser_index', rows=8, maxrows=8)
        col.label(text=f'目前選取骨骼：{len(core.selected_bones(context))}')
        col.operator('faidlix_batch_clean_key.batch', text='批次處理 Action Keys', icon='ACTION')
        box=col.box()
        box.label(text='統一轉換旋轉座標')
        box.prop(state,'rotation_target',expand=True)
        box.prop(state,'sample_step')
        box.label(text='保留原旋轉 Key 影格；間隔只用於取樣曲線')
        box.operator('faidlix_batch_clean_key.rotation',text='處理所有骨骼與 Action',icon='FILE_REFRESH')
        if state.last_result:
            layout.label(text=state.last_result)


class BCK_PT_View3D(_Panel, bpy.types.Panel):
    bl_idname = 'BCK_PT_view3d'
    bl_space_type = 'VIEW_3D'


class BCK_PT_DopeSheet(_Panel, bpy.types.Panel):
    bl_idname = 'BCK_PT_dopesheet'
    bl_space_type = 'DOPESHEET_EDITOR'

    @classmethod
    def poll(cls, context):
        return context.space_data.mode in {'DOPESHEET', 'ACTION'}


class BCK_PT_Graph(_Panel, bpy.types.Panel):
    bl_idname = 'BCK_PT_graph'
    bl_space_type = 'GRAPH_EDITOR'

    @classmethod
    def poll(cls, context):
        return context.space_data.mode == 'FCURVES'


CLASSES = (BCK_PG_Action, BCK_PG_Bone, BCK_PG_State, BCK_OT_Select, BCK_OT_SelectAll, BCK_OT_BonesAll,
           BCK_UL_Bones, BCK_UL_Actions, BCK_UL_Browser, BCK_OT_Batch, BCK_OT_Run,
           BCK_OT_Switch, BCK_OT_New, BCK_OT_Delete, BCK_OT_Duplicate, BCK_OT_Flip,
           BCK_OT_Ranges, BCK_OT_Rotation, BCK_OT_Loop, BCK_OT_Cancel, BCK_PT_View3D, BCK_PT_DopeSheet, BCK_PT_Graph)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.faidlix_batch_clean_key = PointerProperty(type=BCK_PG_State)
    bpy.app.timers.register(sync_timer, first_interval=0.1, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(sync_timer):
        bpy.app.timers.unregister(sync_timer)
    del bpy.types.WindowManager.faidlix_batch_clean_key
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
