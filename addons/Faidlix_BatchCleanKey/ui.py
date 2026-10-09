import time
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from . import core

ADDON_VERSION = '1.1.2'
_sync_signature = None


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
    browser_index: IntProperty()
    bone_index: IntProperty()
    anchor: IntProperty(default=-1)
    show_bones: BoolProperty(name='骨骼清單', default=False)
    show_actions: BoolProperty(name='批次 Action 清單', default=True)
    show_browser: BoolProperty(name='Action 清單', default=True)
    operation: EnumProperty(items=[('DELETE', 'Delete 刪除', '刪除所選骨骼全部 Key'),
                                   ('CLEAN', 'Clean 清理', 'Blender 原生 Clean'),
                                   ('DECIMATE', 'Decimate 縮減', 'Blender 原生 Decimate')], default='CLEAN')
    threshold: FloatProperty(name='清理閾值', default=0.001, min=0.0, precision=5)
    decimate_mode: EnumProperty(items=[('RATIO', '比例', '依比例移除 Key'), ('ERROR', '誤差', '限制曲線誤差')])
    ratio: FloatProperty(name='移除比例', default=0.5, min=0, max=1, subtype='FACTOR')
    error: FloatProperty(name='最大誤差', default=0.01, min=0, precision=5)
    last_result: StringProperty()
    running: BoolProperty(default=False)
    progress: FloatProperty(min=0, max=1, subtype='FACTOR')
    progress_text: StringProperty()


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
    state.browser_index = -1
    for i, item in enumerate(state.browser):
        item.selected = item.action == current
        if item.selected:
            state.browser_index = i
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
        row.operator('faidlix_batch_clean_key.switch', text=action.name, depress=item.selected,
                     icon='RADIOBUT_ON' if item.selected else 'RADIOBUT_OFF').action_name = action.name
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
        layout.template_list('BCK_UL_Bones', '', state, 'bones', state, 'bone_index', rows=5, maxrows=5)


def draw_progress(layout, state):
    if state.running:
        layout.progress(factor=state.progress, type='BAR', text=f'批次處理 {state.progress:.0%}')
        layout.label(text=state.progress_text)
        layout.label(text='Esc 取消；完成後才寫回動畫')


class BCK_OT_Batch(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.batch'
    bl_label = 'Faidlix_BatchCleanKey'

    @classmethod
    def poll(cls, context):
        return bool(rig(context) and context.object.mode == 'POSE' and
                    not context.window_manager.faidlix_batch_clean_key.running)

    def invoke(self, context, event):
        populate(context)
        return context.window_manager.invoke_props_dialog(self, width=700, confirm_text='執行')

    def draw(self, context):
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
        layout.prop(state, 'operation', expand=True)
        if state.operation == 'CLEAN':
            layout.prop(state, 'threshold')
        elif state.operation == 'DECIMATE':
            layout.prop(state, 'decimate_mode', expand=True)
            layout.prop(state, 'ratio' if state.decimate_mode == 'RATIO' else 'error')
        else:
            layout.label(text='刪除勾選骨骼的全部 Key；保留 Action 與其他骨骼', icon='ERROR')
        layout.label(text='共用 Action 會影響其他使用者；鎖定與唯讀資料略過。Ctrl+Z 復原。')

    def execute(self, context):
        # Synchronous execution is useful to scripts; user confirmation launches modal progress.
        if bpy.app.background:
            return run_sync(self, context)
        return bpy.ops.faidlix_batch_clean_key.run('INVOKE_DEFAULT')


def batch_args(context):
    state = context.window_manager.faidlix_batch_clean_key
    obj = state.armature
    if not obj or obj != context.object or obj.mode != 'POSE':
        raise ValueError('骨架或模式已變更，請重新開啟工具')
    names = [b.name for b in state.bones if b.selected]
    actions = [i.action for i in state.actions if i.selected and i.action]
    if not names or not actions:
        raise ValueError('請至少選取一個骨骼與 Action')
    return (context, obj, names, actions, state.operation, state.threshold,
            state.decimate_mode, state.ratio, state.error)


def result_text(result):
    return f'{result["actions"]} Actions，移除 {result["removed"]} Keys，略過 {result["skipped"]} 項'


def run_sync(operator, context):
    try:
        result = core.process(*batch_args(context))
    except Exception as exc:
        operator.report({'ERROR'}, str(exc))
        return {'CANCELLED'}
    state = context.window_manager.faidlix_batch_clean_key
    state.last_result = result_text(result)
    operator.report({'INFO'}, state.last_result)
    update_counts(state)
    return {'FINISHED'}


class BCK_OT_Run(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.run'
    bl_label = '批次處理 Action Keys'
    bl_options = {'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        try:
            self._steps = core.process_steps(*batch_args(context))
            # Validation happens before locking UI.
            state = context.window_manager.faidlix_batch_clean_key
            if state.running:
                return {'CANCELLED'}
            state.running, state.progress = True, 0
            state.progress_text = '準備處理…'
            self._timer = context.window_manager.event_timer_add(0.03, window=context.window)
            context.window_manager.modal_handler_add(self)
            context.window_manager.progress_begin(0, 1)
            self._area = context.area
            self._space_type = type(context.space_data)
            self._draw_handle = self._space_type.draw_handler_add(self.draw_overlay, (), 'WINDOW', 'POST_PIXEL')
            redraw(context)
            return {'RUNNING_MODAL'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
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
        blf.position(0, x, y, 0)
        blf.draw(0, state.progress_text)
        gpu.state.blend_set('NONE')

    def finish(self, context):
        self._space_type.draw_handler_remove(self._draw_handle, 'WINDOW')
        context.window_manager.event_timer_remove(self._timer)
        context.window_manager.progress_end()
        state = context.window_manager.faidlix_batch_clean_key
        state.running = False
        refresh(context)
        redraw(context)

    def modal(self, context, event):
        state = context.window_manager.faidlix_batch_clean_key
        if event.type == 'ESC':
            self._steps.close()
            state.last_result = '已取消，原動畫保留'
            self.finish(context)
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        try:
            deadline = time.perf_counter() + 0.012
            while True:
                done, total, name = next(self._steps)
                state.progress = min(0.99, done / max(1, total))
                state.progress_text = f'{name} ｜ {done}/{total} 通道'
                context.window_manager.progress_update(state.progress)
                if time.perf_counter() >= deadline:
                    break
        except StopIteration as done:
            state.progress = 1
            state.last_result = result_text(done.value)
            self.report({'INFO'}, state.last_result)
            self.finish(context)
            return {'FINISHED'}
        except Exception as exc:
            self._steps.close()
            state.last_result = f'未完成：{exc}'
            self.report({'ERROR'}, str(exc))
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
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
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

    def execute(self, context):
        obj = rig(context)
        action = obj.animation_data.action if obj and obj.animation_data else None
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
    mode: EnumProperty(items=[('COPY', '建立翻轉副本', '保留原 Action'),
                              ('IN_PLACE', '修改原 Action', '原 Action 的所有使用者都會受到影響')], default='COPY')

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=460, confirm_text='翻轉')

    def draw(self, context):
        self.layout.label(text=self.action_name)
        self.layout.prop(self, 'mode', expand=True)
        self.layout.label(text='以骨架 X 軸翻轉，依 Blender 左右骨骼名稱配對')
        self.layout.label(text='找不到對側骨骼的通道保留；不改變 Key 時間')

    def execute(self, context):
        source, obj = bpy.data.actions.get(self.action_name), rig(context)
        if not source or not obj:
            return {'CANCELLED'}
        target = source.copy() if self.mode == 'COPY' else source
        try:
            count, skipped = core.mirror_action(target, obj)
            if self.mode == 'COPY':
                target.name = source.name + '_Flipped'
                target.use_fake_user = True
                core.assign_action(context, obj, target)
        except Exception as exc:
            if self.mode == 'COPY':
                bpy.data.actions.remove(target)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        context.view_layer.update()
        refresh(context)
        redraw(context)
        self.report({'INFO'}, f'翻轉 {count} 通道，略過 {skipped} 通道')
        return {'FINISHED'}


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
        col.enabled = not state.running
        if self.bl_space_type == 'VIEW_3D':
            col.operator('faidlix_batch_clean_key.sync_ranges', icon='PREVIEW_RANGE')
            row = col.row(align=True)
            row.enabled = bool(rig(context))
            row.operator('faidlix_batch_clean_key.new', icon='ADD')
            row.operator('faidlix_batch_clean_key.delete_action', icon='TRASH')
            if fold(col, state, 'show_browser', 'Action 清單'):
                col.template_list('BCK_UL_Browser', '', state, 'browser', state, 'browser_index', rows=8, maxrows=8)
        col.label(text=f'目前選取骨骼：{len(core.selected_bones(context))}')
        col.operator('faidlix_batch_clean_key.batch', text='批次處理 Action Keys', icon='ACTION')
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


CLASSES = (BCK_PG_Action, BCK_PG_Bone, BCK_PG_State, BCK_OT_Select, BCK_OT_SelectAll,
           BCK_UL_Bones, BCK_UL_Actions, BCK_UL_Browser, BCK_OT_Batch, BCK_OT_Run,
           BCK_OT_Switch, BCK_OT_New, BCK_OT_Delete, BCK_OT_Duplicate, BCK_OT_Flip,
           BCK_OT_Ranges, BCK_PT_View3D, BCK_PT_DopeSheet, BCK_PT_Graph)


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
