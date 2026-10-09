"""Faidlix_BatchCleanKey: selected-bone key processing across Actions."""
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from . import core

ADDON_VERSION = '1.0.0'
bl_info = {'name': 'Faidlix_BatchCleanKey', 'author': 'Faidlix',
           'version': (1, 0, 0), 'blender': (5, 2, 0), 'category': 'Animation'}


class BCK_PG_Action(bpy.types.PropertyGroup):
    action: PointerProperty(type=bpy.types.Action)
    selected: BoolProperty(default=False)
    keys: IntProperty()
    status: StringProperty()


class BCK_PG_Bone(bpy.types.PropertyGroup):
    name: StringProperty()


class BCK_PG_State(bpy.types.PropertyGroup):
    actions: CollectionProperty(type=BCK_PG_Action)
    bones: CollectionProperty(type=BCK_PG_Bone)
    armature: PointerProperty(type=bpy.types.Object)
    active_index: IntProperty()
    anchor: IntProperty(default=-1)
    page: IntProperty(default=0, min=0)
    operation: EnumProperty(items=[('DELETE', 'Delete 刪除', '刪除所選骨骼的全部 Key'),
                                   ('CLEAN', 'Clean 清理', '使用 Blender 原生 Clean'),
                                   ('DECIMATE', 'Decimate 縮減', '使用 Blender 原生 Decimate')], default='CLEAN')
    threshold: FloatProperty(name='清理閾值', default=0.001, min=0.0, precision=5)
    decimate_mode: EnumProperty(items=[('RATIO', '比例', '依比例移除 Key'),
                                       ('ERROR', '誤差', '限制曲線變化誤差')])
    ratio: FloatProperty(name='移除比例', default=0.5, min=0, max=1, subtype='FACTOR')
    error: FloatProperty(name='最大誤差', default=0.01, min=0, precision=5)
    last_result: StringProperty()


def populate(context):
    state = context.window_manager.faidlix_batch_clean_key
    names = core.selected_bones(context)
    state.armature = context.object
    state.bones.clear()
    for name in names:
        state.bones.add().name = name
    state.actions.clear()
    active = context.object.animation_data.action if context.object.animation_data else None
    for action in sorted(bpy.data.actions, key=lambda a: a.name.casefold()):
        item = state.actions.add()
        item.action = action
        curves = core.target_curves(action, context.object, names)
        item.keys = sum(len(c.keyframe_points) for c in curves)
        item.status = ('唯讀' if not action.is_editable else
                       'Slot 不明確' if action.slots and not core.slot_for(action, context.object) else '')
        item.selected = action == active and item.keys > 0 and not item.status
    state.active_index = next((i for i, a in enumerate(state.actions) if a.selected), 0)
    state.anchor = state.active_index if any(a.selected for a in state.actions) else -1
    state.page = state.active_index // 10
    return state


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
        for area in context.screen.areas:
            area.tag_redraw()
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
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class BCK_OT_Page(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.page'
    bl_label = '切換 Action 頁面'
    bl_options = {'INTERNAL'}
    delta: IntProperty()

    def execute(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        state.page = max(0, min((len(state.actions) - 1) // 10, state.page + self.delta))
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class BCK_OT_Batch(bpy.types.Operator):
    bl_idname = 'faidlix_batch_clean_key.batch'
    bl_label = 'Faidlix_BatchCleanKey'
    bl_description = '選擇 Action，批次處理目前選定骨骼的 Key'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(core.selected_bones(context))

    def invoke(self, context, event):
        populate(context)
        return context.window_manager.invoke_props_dialog(self, width=640, confirm_text='執行')

    def draw(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        layout = self.layout
        layout.label(text=f'骨架：{state.armature.name if state.armature else "無"} ｜ 骨骼：{len(state.bones)}', icon='BONE_DATA')
        layout.label(text=', '.join(b.name for b in state.bones)[:100])
        layout.label(text='單擊單選 ｜ Ctrl 增減選 ｜ Shift 範圍 ｜ Ctrl+Shift 加入範圍')
        row = layout.row(align=True)
        row.operator('faidlix_batch_clean_key.select_all', text='全選所有 Action').value = True
        row.operator('faidlix_batch_clean_key.select_all', text='取消全選').value = False
        # Native UIList consumes Ctrl-click before row operators receive the event.
        # Plain row buttons preserve modifier events; pages keep large lists bounded.
        box = layout.box()
        box.operator_context = 'INVOKE_DEFAULT'
        start = state.page * 10
        for index in range(start, min(start + 10, len(state.actions))):
            item = state.actions[index]
            label = f'{item.action.name if item.action else "已移除"}    |    {item.keys} Keys'
            if item.status:
                label += f'    ({item.status})'
            row = box.row()
            row.operator('faidlix_batch_clean_key.select', text=label,
                         icon='CHECKBOX_HLT' if item.selected else 'CHECKBOX_DEHLT',
                         depress=item.selected).index = index
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = state.page > 0
        sub.operator('faidlix_batch_clean_key.page', text='上一頁', icon='TRIA_LEFT').delta = -1
        row.label(text=f'{state.page + 1} / {max(1, (len(state.actions) + 9) // 10)}')
        sub = row.row(align=True)
        sub.enabled = (state.page + 1) * 10 < len(state.actions)
        sub.operator('faidlix_batch_clean_key.page', text='下一頁', icon='TRIA_RIGHT').delta = 1
        chosen = [a for a in state.actions if a.selected]
        layout.label(text=f'已選 {len(chosen)} / {len(state.actions)} Actions ｜ {sum(a.keys for a in chosen)} Keys')
        layout.prop(state, 'operation', expand=True)
        if state.operation == 'CLEAN':
            layout.prop(state, 'threshold')
        elif state.operation == 'DECIMATE':
            layout.prop(state, 'decimate_mode', expand=True)
            layout.prop(state, 'ratio' if state.decimate_mode == 'RATIO' else 'error')
        else:
            layout.label(text='刪除以上骨骼的全部 Key；保留 Action 和其他骨骼', icon='ERROR')
        layout.label(text='鎖定曲線與唯讀 Action 會略過；縮減略過非 Linear／Bezier 曲線')
        layout.label(text='Action 由其他物件共用時，也會影響其使用者。完成後可 Ctrl+Z 復原。')

    def execute(self, context):
        state = context.window_manager.faidlix_batch_clean_key
        obj = state.armature
        if not obj or obj != context.object or obj.mode != 'POSE':
            self.report({'ERROR'}, '骨架或模式已變更，請重新開啟工具')
            return {'CANCELLED'}
        actions = [a.action for a in state.actions if a.selected and a.action]
        if not actions:
            self.report({'WARNING'}, '請至少選一個 Action')
            return {'CANCELLED'}
        try:
            result = core.process(context, obj, [b.name for b in state.bones], actions,
                                  state.operation, state.threshold, state.decimate_mode,
                                  state.ratio, state.error)
        except Exception as exc:
            self.report({'ERROR'}, f'未完成：{exc}')
            return {'CANCELLED'}
        state.last_result = (f'{result["actions"]} Actions，移除 {result["removed"]} Keys，'
                             f'略過 {result["skipped"]} 項')
        self.report({'INFO'}, state.last_result)
        for area in context.screen.areas:
            area.tag_redraw()
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
        layout = self.layout
        names = core.selected_bones(context)
        layout.label(text=f'已選骨骼：{len(names)}', icon='BONE_DATA')
        if not names:
            layout.label(text='請在 Pose Mode 選取骨骼')
        layout.operator('faidlix_batch_clean_key.batch', text='批次處理 Action Keys', icon='ACTION')
        state = context.window_manager.faidlix_batch_clean_key
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


CLASSES = (BCK_PG_Action, BCK_PG_Bone, BCK_PG_State, BCK_OT_Select, BCK_OT_Page,
           BCK_OT_SelectAll, BCK_OT_Batch,
           BCK_PT_View3D, BCK_PT_DopeSheet, BCK_PT_Graph)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.faidlix_batch_clean_key = PointerProperty(type=BCK_PG_State)


def unregister():
    del bpy.types.WindowManager.faidlix_batch_clean_key
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
