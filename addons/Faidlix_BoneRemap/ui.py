import bpy
from bpy.types import Menu, Panel, UIList

from .model import (
    animation_rows_are_current,
    flip_bone_name,
    rebuild_animation_rows,
    reuse_mapping_items,
)
from .operators import _mapping_axes_match, _object_actions, ik_editor_window_for


ADDON_VERSION = (0, 6, 9)


def _source_file_index(settings, source_file):
    pointer = source_file.as_pointer()
    return next(
        (index for index, item in enumerate(settings.files) if item.as_pointer() == pointer),
        -1,
    )


def _mapping_pair(source_file, mapping):
    pair_name = flip_bone_name(mapping.source_bone)
    if pair_name == mapping.source_bone:
        return None
    return next(
        (item for item in source_file.mappings if item.source_bone == pair_name),
        None,
    )


def _paired_mapping_label(source_file, mapping, property_name):
    value = getattr(mapping, property_name)
    pair = _mapping_pair(source_file, mapping)
    pair_value = getattr(pair, property_name) if pair else ""
    return f"{value}/{pair_value}" if value and pair_value else value


def _clip_duration(scene, clip):
    fps = scene.render.fps / max(scene.render.fps_base, 1.0e-8)
    return max(0.0, clip.frame_end - clip.frame_start) / max(fps, 1.0e-8)


def _clip_timing_labels(scene, clip):
    return (
        f"{clip.frame_start:g}-{clip.frame_end:g}",
        f"( {_clip_duration(scene, clip):.1f} 秒 )",
    )


def _reused_mapping_sources(settings, source):
    return [
        candidate
        for candidate in settings.files
        if (
            not candidate.mapping_is_independent
            and candidate.reuse_mapping == source.uid
        )
    ]


def _animation_row_columns(row, settings):
    remove = row.row(align=True)
    remove.ui_units_x = 1.25
    enabled = row.row(align=True)
    enabled.ui_units_x = 1.35
    content = row.split(factor=settings.animation_info_factor)
    information = content.row(align=True)
    name_and_timing = information.split(factor=settings.animation_action_factor)
    name = name_and_timing.row(align=True)
    timing = name_and_timing.row(align=True)
    options_fraction = 1.0 - settings.animation_mirror_fraction / max(
        1.0 - settings.animation_info_factor, 0.01
    )
    options = content.split(factor=max(0.1, min(0.9, options_fraction)))
    inplace = options.row(align=True)
    mirror = options.row(align=True)
    return remove, enabled, name, timing, inplace, mirror


def _remove_file_button(layout, file_index):
    button = layout.operator("fbr.remove_file", text="", icon="TRASH", emboss=False)
    button.file_index = file_index


def _drag_handle(layout, settings, property_name):
    handle = layout.row(align=True)
    handle.ui_units_x = 0.65
    drag = handle.operator("fbr.drag_column", text="│", emboss=True)
    drag.property_name = property_name
    return handle


def _mapping_row_columns(row, settings):
    source_end = settings.mapping_source_factor
    target_end = max(source_end + 0.1, settings.mapping_target_factor)
    axis_start = max(target_end + 0.08, settings.mapping_axis_factor)
    source_and_rest = row.split(factor=source_end)
    source = source_and_rest.row(align=True)
    target_and_rest = source_and_rest.split(
        factor=(target_end - source_end) / (1.0 - source_end)
    )
    target = target_and_rest.row(align=True)
    ik_and_axis = target_and_rest.split(
        factor=(axis_start - target_end) / (1.0 - target_end)
    )
    ik = ik_and_axis.row(align=True)
    axis = ik_and_axis.row(align=True)
    return source, target, ik, axis


def _draw_forward_axis_buttons(layout, source, file_index, role):
    property_name = "source_forward_axis" if role == "SOURCE" else "target_forward_axis"
    row = layout.row(align=True)
    row.label(text="來源前方" if role == "SOURCE" else "Target 前方")
    buttons = row.row(align=True)
    for axis, label in (("AUTO", "自動"), ("+X", "+X"), ("-X", "-X"), ("+Y", "+Y"), ("-Y", "-Y")):
        button = buttons.operator(
            "fbr.set_forward_axis",
            text=label,
            depress=getattr(source, property_name) == axis,
        )
        button.file_index = file_index
        button.role = role
        button.axis = axis


def _draw_animation_header(layout, settings):
    row = layout.row(align=True)
    remove, enabled, name, timing, inplace, mirror = _animation_row_columns(
        row, settings
    )
    remove.label(text="")
    enabled.label(text="")
    name.label(text="檔案／動畫名稱")
    _drag_handle(name, settings, "animation_action_factor")
    timing.label(text="時間")
    _drag_handle(timing, settings, "animation_info_factor")
    inplace.label(text="設為原地動畫")
    _drag_handle(inplace, settings, "animation_mirror_fraction")
    mirror.label(text="複製對稱動畫")


def _draw_multi_clip_header(layout, source, file_index, settings):
    row = layout.row(align=True)
    remove, enabled, name, _timing, _inplace, _mirror = _animation_row_columns(
        row, settings
    )
    _remove_file_button(remove, file_index)
    name.prop(
        source,
        "expanded",
        text="",
        icon="TRIA_DOWN" if source.expanded else "TRIA_RIGHT",
        emboss=False,
    )
    all_enabled = bool(source.clips) and all(clip.enabled for clip in source.clips)
    any_enabled = any(clip.enabled for clip in source.clips)
    icon = (
        "CHECKBOX_HLT"
        if all_enabled
        else ("REMOVE" if any_enabled else "CHECKBOX_DEHLT")
    )
    toggle = enabled.operator("fbr.toggle_file", text="", icon=icon, emboss=False)
    toggle.index = file_index
    name.label(text=f"{source.display_name}({len(source.clips)} 個動畫)")


def _draw_clip_row(context, layout, source, file_index, clip, clip_index, show_file_name):
    row = layout.row(align=True)
    remove, enabled, name, timing, inplace_cell, mirror_cell = _animation_row_columns(
        row,
        context.scene.fbr_settings,
    )
    frame_text, seconds_text = _clip_timing_labels(context.scene, clip)
    if show_file_name:
        _remove_file_button(remove, file_index)
        enabled.prop(clip, "enabled", text="")
        name.label(text=f"{source.display_name} / {clip.action_name}")
    else:
        remove.label(text="")
        enabled.prop(clip, "enabled", text="")
        name.label(text=clip.action_name)
    timing.alignment = "LEFT"
    time_parts = timing.split(factor=0.52)
    time_parts.label(text=frame_text)
    time_parts.label(text=seconds_text)

    inplace_cell.alignment = "CENTER"
    inplace_button = inplace_cell.row(align=True)
    inplace_button.ui_units_x = 5.0
    inplace = inplace_button.operator(
        "fbr.toggle_clip_option",
        text="啟用" if clip.in_place else "未啟用",
        depress=clip.in_place,
    )
    inplace.file_index = file_index
    inplace.clip_index = clip_index
    inplace.option = "IN_PLACE"
    mirror_cell.alignment = "CENTER"
    mirror_button = mirror_cell.row(align=True)
    mirror_button.ui_units_x = 5.0
    copy = mirror_button.operator(
        "fbr.toggle_clip_option",
        text="啟用" if clip.mirror_mode == "COPY" else "未啟用",
        depress=clip.mirror_mode == "COPY",
    )
    copy.file_index = file_index
    copy.clip_index = clip_index
    copy.option = "COPY"


class FBR_UL_animation_rows(UIList):
    bl_idname = "FBR_UL_animation_rows"

    def filter_items(self, context, data, property_name):
        rows = getattr(data, property_name)
        flags = [self.bitflag_filter_item] * len(rows)
        sources = {source.uid: source for source in data.files}
        for index, item in enumerate(rows):
            source = sources.get(item.file_uid)
            if not source or (
                item.clip_index >= 0
                and len(source.clips) > 1
                and not source.expanded
            ):
                flags[index] &= ~self.bitflag_filter_item
        return flags, []

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_property,
        index,
    ):
        file_index = next(
            (i for i, source in enumerate(data.files) if source.uid == item.file_uid),
            -1,
        )
        if file_index < 0:
            layout.label(text="")
            return
        source = data.files[file_index]
        if item.clip_index < 0:
            _draw_multi_clip_header(layout, source, file_index, data)
        elif item.clip_index < len(source.clips):
            _draw_clip_row(
                context,
                layout,
                source,
                file_index,
                source.clips[item.clip_index],
                item.clip_index,
                show_file_name=len(source.clips) <= 1,
            )


def _mapping_group_info(source_file, mapping):
    source = bpy.data.objects.get(source_file.source_object)
    if not source or source.type != "ARMATURE":
        return None, False, False
    bone = source.data.bones.get(mapping.source_bone)
    if not bone:
        return None, False, False
    own = bone.name.casefold()
    if "hand" in own and not any(token in own for token in ("thumb", "finger", "pinky", "index", "middle", "ring")):
        return "HAND", True, False
    if "foot" in own and "toe" not in own:
        return "FOOT", True, False
    parent = bone.parent
    while parent:
        name = parent.name.casefold()
        if "hand" in name:
            return "HAND", False, True
        if "foot" in name:
            return "FOOT", False, True
        parent = parent.parent
    return None, False, False


def _draw_mapping_row(context, layout, source_file, item, index):
    settings = context.scene.fbr_settings
    target = bpy.data.objects.get(settings.target_armature)
    source = bpy.data.objects.get(source_file.source_object)
    file_index = _source_file_index(settings, source_file)

    row = layout.row(align=True)
    source_cell, target_row, ik_slot, axis_tools = _mapping_row_columns(
        row, settings
    )
    group_kind, is_group_parent, is_group_child = _mapping_group_info(source_file, item)
    if is_group_parent:
        prop_name = "hands_expanded" if group_kind == "HAND" else "feet_expanded"
        expanded = getattr(source_file, prop_name)
        source_cell.prop(
            source_file,
            prop_name,
            text="",
            icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
            emboss=False,
        )
    elif is_group_child:
        source_cell.label(text="")
    source_cell.label(text=_paired_mapping_label(source_file, item, "source_bone"))
    target_row.alignment = "LEFT"
    if item.is_root:
        target_row.label(text="", icon="EVENT_R")
    else:
        target_row.label(text="", icon="BONE_DATA")
    select_button = target_row.row(align=True)
    select_button.ui_units_x = 10.0
    select = select_button.operator(
        "fbr.select_target_bone",
        text=_paired_mapping_label(source_file, item, "target_bone") or "未指定",
    )
    select.file_index = file_index
    select.mapping_index = index
    clear_slot = target_row.row(align=True)
    clear_slot.ui_units_x = 1.5
    if item.target_bone:
        clear = clear_slot.operator("fbr.clear_target_bone", text="", icon="X")
        clear.file_index = file_index
        clear.mapping_index = index
    else:
        clear_slot.label(text="")
    ik = ik_slot.operator(
        "fbr.ik_settings",
        text="IK 已設定" if item.ik_enabled else "設定 IK",
        depress=item.ik_enabled,
    )
    ik.file_index = file_index
    ik.mapping_index = index
    ik.action = "START"

    pair = _mapping_pair(source_file, item)
    axes_match = bool(item.target_bone) and _mapping_axes_match(source, target, item) and (
        not pair or not pair.target_bone or _mapping_axes_match(source, target, pair)
    )
    edit = axis_tools.operator("fbr.axis_correction", text="調整")
    edit.file_index = file_index
    edit.mapping_index = index
    edit.action = "START"
    axis_tools.label(text="相同" if axes_match else "不相同")


def _draw_axis_correction(layout, file_index, source_file):
    active = source_file.mappings[source_file.active_mapping_index]
    pair = _mapping_pair(source_file, active)
    correction = layout.box()
    rotation = correction.row(align=True)
    rotation.label(text="旋轉")
    auto = rotation.operator("fbr.axis_correction", text="自動對軸向")
    auto.file_index = file_index
    auto.mapping_index = source_file.active_mapping_index
    auto.action = "AUTO"
    rotation_property = "pair_rotation_offset" if pair else "rotation_offset"
    rotation.prop(active, rotation_property, index=0, text="X")
    rotation.prop(active, rotation_property, index=1, text="Y")
    rotation.prop(active, rotation_property, index=2, text="Z")
    values = correction.row(align=True)
    root = values.operator(
        "fbr.set_root",
        text="Root 已設定" if active.is_root else "設定為 Root",
        depress=active.is_root,
    )
    root.file_index = file_index
    root.mapping_index = source_file.active_mapping_index
    values.prop(
        active,
        "transfer_location",
        text="啟用骨頭位移倍率",
        toggle=True,
    )
    if active.transfer_location:
        values.prop(active, "location_multiplier", text="倍率")
    buttons = correction.row(align=False)
    reset = buttons.operator("fbr.axis_correction", text="Reset")
    reset.file_index = file_index
    reset.mapping_index = source_file.active_mapping_index
    reset.action = "RESET"
    buttons.separator(factor=0.5)
    cancel = buttons.operator("fbr.axis_correction", text="Cancel")
    cancel.file_index = file_index
    cancel.mapping_index = source_file.active_mapping_index
    cancel.action = "CANCEL"
    okay = buttons.operator("fbr.axis_correction", text="OK")
    okay.file_index = file_index
    okay.mapping_index = source_file.active_mapping_index
    okay.action = "OK"


def _draw_ik_settings(layout, file_index, source_file):
    active = source_file.mappings[source_file.active_mapping_index]
    editor = layout.box()
    editor.label(text=f"IK 設定：{active.source_bone} → {active.target_bone}", icon="CONSTRAINT_BONE")
    if active.ik_enabled:
        shape = editor.row(align=True)
        shape.prop(active, "ik_shape", text="", expand=True)
        dimensions = editor.row(align=True)
        dimensions.prop(active, "ik_shape_scale", text="大小")
        dimensions.prop(active, "ik_shape_wire_width", text="Width")
        appearance = editor.row(align=True)
        appearance.prop(active, "ik_shape_color", text="顏色")
        solver = editor.row(align=True)
        solver.prop(active, "ik_chain_count")
        solver.prop(active, "ik_iterations")
        solver.prop(active, "ik_influence")
        options = editor.row(align=True)
        options.prop(active, "ik_use_tail", toggle=True)
        options.prop(active, "ik_use_pole", toggle=True)
        options.prop(active, "ik_use_rotation", toggle=True)
        options.prop(active, "ik_use_stretch", toggle=True)
        if active.ik_use_pole:
            pole = editor.row(align=True)
            pole.prop(active, "ik_pole_length")
            pole.prop(active, "ik_pole_size_ratio", text="大小")
    else:
        editor.label(text="IK 與控制骨已刪除", icon="INFO")
    buttons = editor.row(align=True)
    buttons.operator_context = "EXEC_DEFAULT"
    delete = buttons.operator("fbr.delete_ik", text="刪除 IK", icon="TRASH")
    delete.file_index = file_index
    delete.mapping_index = source_file.active_mapping_index
    cancel = buttons.operator("fbr.ik_settings", text="取消")
    cancel.file_index = file_index
    cancel.mapping_index = source_file.active_mapping_index
    cancel.action = "CANCEL"
    okay = buttons.operator("fbr.ik_settings", text="確認")
    okay.file_index = file_index
    okay.mapping_index = source_file.active_mapping_index
    okay.action = "OK"


class FBR_UL_mappings(UIList):
    bl_idname = "FBR_UL_mappings"

    def filter_items(self, _context, data, property_name):
        mappings = getattr(data, property_name)
        flags = [self.bitflag_filter_item] * len(mappings)
        by_source = {item.source_bone: item for item in mappings}
        for index, item in enumerate(mappings):
            pair_name = flip_bone_name(item.source_bone)
            if (
                pair_name != item.source_bone
                and pair_name in by_source
                and item.source_bone.casefold() > pair_name.casefold()
            ):
                flags[index] &= ~self.bitflag_filter_item
            group_kind, _is_parent, is_child = _mapping_group_info(data, item)
            if is_child and group_kind == "HAND" and not data.hands_expanded:
                flags[index] &= ~self.bitflag_filter_item
            if is_child and group_kind == "FOOT" and not data.feet_expanded:
                flags[index] &= ~self.bitflag_filter_item
        return flags, []

    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_property,
        index,
    ):
        _draw_mapping_row(context, layout, data, item, index)


class FBR_MT_reuse_mapping(Menu):
    bl_idname = "FBR_MT_reuse_mapping"
    bl_label = "骨架映射"

    def draw(self, context):
        source = getattr(context, "fbr_source_file", None)
        if not source:
            return
        settings = context.scene.fbr_settings
        file_index = _source_file_index(settings, source)
        for identifier, label, description in reuse_mapping_items(source, context):
            option = self.layout.operator(
                "fbr.set_reuse_mapping",
                text=label,
                icon="CHECKMARK" if source.reuse_mapping == identifier else "NONE",
            )
            option.file_index = file_index
            option.reuse_uid = identifier


class FBR_PT_main(Panel):
    bl_idname = "FBR_PT_main"
    bl_label = "Faidlix_Retarget Motion"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Faidlix"

    def draw_header_preset(self, _context):
        row = self.layout.row(align=True)
        row.alignment = "RIGHT"
        row.label(text=f"v{'.'.join(map(str, ADDON_VERSION))}")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fbr_settings
        editing_index = next(
            (
                index
                for index, source in enumerate(settings.files)
                if source.axis_editing or source.ik_editing
            ),
            -1,
        )
        locked = editing_index >= 0 or settings.retarget_running

        top = layout.row(align=False)
        top.enabled = not locked
        top.operator("fbr.reset_all", text="全部重設", icon="FILE_REFRESH")
        top.separator(factor=0.5)
        if settings.update_status:
            status = top.row(align=True)
            status.enabled = False
            status.operator("fbr.online_update", text=settings.update_status, icon="INFO")
        else:
            top.operator("fbr.online_update", text="線上更新", icon="URL")
        layout.separator()

        target_box = layout.box()
        target_box.enabled = not locked
        target_row = target_box.row(align=True)
        target_row.label(text="主要骨架", icon="ARMATURE_DATA")
        target_choice = target_row.row(align=True)
        target_choice.ui_units_x = 11.0
        target_choice.prop(settings, "target_armature", text="")
        target = bpy.data.objects.get(settings.target_armature)

        source_box = layout.box()
        source_box.enabled = not locked
        header = source_box.row(align=False)
        if settings.files:
            header.prop(
                settings,
                "files_expanded",
                text="",
                icon="TRIA_DOWN" if settings.files_expanded else "TRIA_RIGHT",
                emboss=False,
            )
        header.operator("fbr.import_folder", text="加入動畫檔案", icon="FILE_FOLDER")
        header.separator(factor=0.5)
        header.operator("fbr.clear_files", text="全部清空動畫檔", icon="TRASH")
        if not settings.files:
            source_box.label(text="尚未加入動畫檔案", icon="INFO")

        if settings.files_expanded:
            if not animation_rows_are_current(settings):
                rebuild_animation_rows(settings)
            _draw_animation_header(source_box, settings)
            visible_rows = sum(
                1
                for item in settings.animation_rows
                for source in settings.files
                if source.uid == item.file_uid
                and not (
                    item.clip_index >= 0
                    and len(source.clips) > 1
                    and not source.expanded
                )
            )
            source_box.template_list(
                "FBR_UL_animation_rows",
                "main",
                settings,
                "animation_rows",
                settings,
                "active_animation_row_index",
                rows=max(2, min(10, visible_rows)),
            )

        mapping_box = layout.box()
        mapping_box.label(text="骨骼對應", icon="CONSTRAINT_BONE")
        for file_index, source in enumerate(settings.files):
            if not source.mapping_is_independent:
                continue
            group = mapping_box.box()
            if editing_index >= 0 and editing_index != file_index:
                group.enabled = False
            row = group.row(align=True)
            title = row.row(align=True)
            title.enabled = not locked
            title.prop(
                source,
                "mapping_expanded",
                text=f"{source.display_name} · {len(source.clips)} 個 Action",
                icon="TRIA_DOWN" if source.mapping_expanded else "TRIA_RIGHT",
                emboss=False,
            )
            mapping_choice = row.row(align=True)
            mapping_choice.ui_units_x = 9.0
            mapping_choice.enabled = not locked
            mapping_items = reuse_mapping_items(source, context)
            mapping_label = next(
                (
                    label
                    for identifier, label, _description in mapping_items
                    if identifier == source.reuse_mapping
                ),
                "獨立骨架映射",
            )
            mapping_choice.context_pointer_set("fbr_source_file", source)
            mapping_choice.menu("FBR_MT_reuse_mapping", text=mapping_label)
            row.separator(factor=0.25)
            preview_active = (
                settings.preview_running and settings.preview_source_uid == source.uid
            )
            if len(source.clips) > 1:
                clip_selector = group.row(align=True)
                clip_selector.enabled = (
                    editing_index < 0 and not settings.retarget_running
                )
                clip_selector.prop(source, "preview_clip", text="預覽動畫")
            preview_controls = group.row(align=True)
            preview_controls.enabled = (
                bool(source.clips)
                and editing_index < 0
                and not settings.retarget_running
            )
            tpose_active = (
                preview_active and settings.preview_mode == "TPOSE"
            )
            tpose = preview_controls.operator(
                "fbr.preview_tpose",
                text="T-Pose",
                icon="POSE_HLT",
                depress=tpose_active,
            )
            tpose.file_index = file_index
            tpose.action = "HIDE" if tpose_active else "SHOW"
            animation_preview_active = (
                preview_active and settings.preview_mode == "ANIMATION"
            )
            preview = preview_controls.operator(
                "fbr.preview_animation",
                text="預覽",
                icon="ARMATURE_DATA",
                depress=animation_preview_active,
            )
            preview.file_index = file_index
            preview.action = "HIDE" if animation_preview_active else "SHOW"
            screen = getattr(context, "screen", None)
            animation_playing = bool(
                animation_preview_active and screen and screen.is_animation_playing
            )
            play = preview_controls.operator(
                "fbr.preview_animation",
                text="停止播放" if animation_playing else "播放動畫",
                icon="PAUSE" if animation_playing else "PLAY",
                depress=animation_playing,
            )
            play.file_index = file_index
            play.action = "PAUSE" if animation_playing else "PLAY"

            reused_sources = _reused_mapping_sources(settings, source)
            if reused_sources and not source.mapping_expanded:
                reused_box = group.box()
                reused_count = sum(len(candidate.clips) for candidate in reused_sources)
                reused_box.prop(
                    source,
                    "reused_expanded",
                    text=f"{reused_count} 個動畫沿用映射骨架",
                    icon="TRIA_DOWN" if source.reused_expanded else "TRIA_RIGHT",
                    emboss=False,
                )
                if source.reused_expanded:
                    for candidate in reused_sources:
                        reused_row = reused_box.row(align=True)
                        reused_row.label(
                            text=f"{candidate.display_name} · {len(candidate.clips)} 個 Action"
                        )
                        reused_row.prop(candidate, "reuse_mapping", text="")

            if not source.mapping_expanded:
                continue

            tools = group.grid_flow(
                row_major=True,
                columns=4,
                even_columns=True,
                even_rows=True,
                align=True,
            )
            tools.enabled = not locked
            auto = tools.operator("fbr.auto_map", text="自動配骨架")
            auto.file_index = file_index
            axes = tools.operator("fbr.auto_align_axes", text="自動對軸向")
            axes.file_index = file_index
            tools.prop(settings, "auto_scale", text="Root 位移縮放", toggle=True)
            tools.label(text="")
            forward = group.column(align=True)
            forward.enabled = not locked
            _draw_forward_axis_buttons(forward, source, file_index, "SOURCE")
            _draw_forward_axis_buttons(forward, source, file_index, "TARGET")

            list_area = group.column(align=True)
            list_area.enabled = not locked
            list_header = list_area.row(align=True)
            source_header, target_header, ik_header, axis_header = _mapping_row_columns(
                list_header, settings
            )
            source_header.label(text="來源骨骼")
            _drag_handle(source_header, settings, "mapping_source_factor")
            target_header.alignment = "LEFT"
            target_header.label(text="Target 骨骼")
            _drag_handle(target_header, settings, "mapping_target_factor")
            ik_header.alignment = "CENTER"
            ik_header.label(text="IK 設定")
            _drag_handle(ik_header, settings, "mapping_axis_factor")
            axis_header.alignment = "CENTER"
            axis_header.label(text="來源和目標軸向")
            list_area.template_list(
                "FBR_UL_mappings",
                source.uid,
                source,
                "mappings",
                source,
                "active_mapping_index",
                rows=6,
            )
            if reused_sources:
                reused_box = group.box()
                reused_count = sum(len(candidate.clips) for candidate in reused_sources)
                reused_box.prop(
                    source,
                    "reused_expanded",
                    text=f"{reused_count} 個動畫沿用映射骨架",
                    icon="TRIA_DOWN" if source.reused_expanded else "TRIA_RIGHT",
                    emboss=False,
                )
                if source.reused_expanded:
                    for candidate in reused_sources:
                        reused_row = reused_box.row(align=True)
                        reused_row.label(
                            text=f"{candidate.display_name} · {len(candidate.clips)} 個 Action"
                        )
                        reused_row.prop(candidate, "reuse_mapping", text="")

        if target and "c_traj" in target.pose.bones:
            control_box = layout.box()
            control_box.enabled = not locked
            control_box.label(text="動畫控制")
            control_box.prop(settings, "extract_root_motion", text="Extract Root Motion")

        output_box = layout.box()
        output_box.enabled = not locked
        output_header = output_box.row(align=True)
        output_header.label(text="輸出與 Key", icon="ACTION")
        output_header.prop(settings, "fake_user", text="Fake User")
        output_modes = output_box.row(align=True)
        output_modes.prop(settings, "output_mode", expand=True)
        naming_modes = output_box.row(align=True)
        naming_modes.prop(settings, "naming_mode", expand=True)
        if settings.naming_mode == "CUSTOM":
            names_box = output_box.box()
            names_box.label(text="片段輸出名稱")
            for file_index, source in enumerate(settings.files):
                for clip_index, clip in enumerate(source.clips):
                    name_row = names_box.row(align=True)
                    name_row.label(text=clip.action_name)
                    name_row.prop(clip, "custom_name", text="")
                    clear = name_row.operator("fbr.clip_name", text="", icon="X")
                    clear.file_index = file_index
                    clear.clip_index = clip_index
                    clear.action = "CLEAR"
                    reset = name_row.operator("fbr.clip_name", text="", icon="FILE_REFRESH")
                    reset.file_index = file_index
                    reset.clip_index = clip_index
                    reset.action = "RESET"
        if settings.output_mode == "MERGED":
            output_box.prop(settings, "merged_action_name")
            row = output_box.row(align=True)
            row.prop(settings, "merged_start")
            row.prop(settings, "merged_gap")
        output_box.separator()
        key_modes = output_box.row(align=True)
        key_modes.prop(settings, "key_mode", expand=True)
        if settings.key_mode == "SIMPLIFY":
            tolerance = output_box.row(align=True)
            tolerance.prop(settings, "rotation_tolerance")
            tolerance.prop(settings, "location_tolerance")

        enabled = sum(clip.enabled for source in settings.files for clip in source.clips)
        check = layout.box()
        check.enabled = not locked
        summary = check.row(align=True)
        if target and enabled:
            summary.prop(
                settings, "target_actions_expanded", text="",
                icon="TRIA_DOWN" if settings.target_actions_expanded else "TRIA_RIGHT",
                emboss=False,
            )
            total = settings.retarget_total_count or enabled
            summary.label(
                text=f"({settings.retarget_completed_count}/{total})個動畫已處理"
            )
        elif not target:
            summary.label(text="請選擇主要骨架", icon="ERROR")
        else:
            summary.prop(
                settings, "target_actions_expanded", text="",
                icon="TRIA_DOWN" if settings.target_actions_expanded else "TRIA_RIGHT",
                emboss=False,
            )
            summary.label(text="請加入並啟用動畫片段", icon="ERROR")
        summary.operator(
            "fbr.clear_target_animation", text="刪除所有動畫", icon="TRASH"
        )
        if not target:
            summary.enabled = False
        if target and settings.target_actions_expanded:
            actions = _object_actions(target)
            action_list = check.box()
            header = action_list.row(align=True)
            remove_header = header.row(align=True)
            remove_header.ui_units_x = 1.25
            remove_header.label(text="")
            preview_header = header.row(align=True)
            preview_header.ui_units_x = 4.5
            preview_header.label(text="預覽")
            header.label(text="動畫名稱")
            header.label(text="時間")
            if not actions:
                action_list.label(text="主要骨架目前沒有掛載動畫")
            for action in actions:
                action_row = action_list.row(align=True)
                remove_cell = action_row.row(align=True)
                remove_cell.ui_units_x = 1.25
                remove = remove_cell.operator(
                    "fbr.remove_target_action", text="", icon="TRASH", emboss=False
                )
                remove.action_name = action.name
                preview_cell = action_row.row(align=True)
                preview_cell.ui_units_x = 4.5
                playing = bool(
                    settings.target_preview_action == action.name
                    and context.screen and context.screen.is_animation_playing
                )
                preview = preview_cell.operator(
                    "fbr.preview_target_action",
                    text="暫停" if playing else "播放",
                    icon="PAUSE" if playing else "PLAY",
                )
                preview.action_name = action.name
                generated = action.get("_fbr_batch_id") == settings.retarget_batch_id
                name_cell = action_row.row(align=True)
                name_cell.enabled = generated
                name_cell.label(text=action.name)
                start, end = action.frame_range
                fps = context.scene.render.fps / max(context.scene.render.fps_base, 1.0e-8)
                action_row.label(text=f"{start:g}-{end:g}  ({(end-start)/fps:.1f} 秒)")
        if settings.retarget_running:
            layout.progress(
                factor=settings.retarget_progress,
                type="BAR",
                text=f"背景處理：{settings.retarget_status} （Esc 取消）",
            )
        else:
            run = layout.row()
            run.scale_y = 1.3
            run.enabled = bool(target and enabled and editing_index < 0)
            run.operator("fbr.retarget", text="開始批次重定向", icon="PLAY")


class FBR_PT_ik_window(Panel):
    bl_idname = "FBR_PT_ik_window"
    bl_label = "設定 IK"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "scene"
    bl_order = -1000

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "fbr_settings", None)
        window = context.window
        if settings is None or window is None:
            return False
        return any(
            source.ik_editing
            and ik_editor_window_for(source.uid) == window
            and 0 <= source.active_mapping_index < len(source.mappings)
            for source in settings.files
        )

    def draw(self, context):
        settings = context.scene.fbr_settings
        window = context.window
        for index, source in enumerate(settings.files):
            if source.ik_editing and ik_editor_window_for(source.uid) == window:
                _draw_ik_settings(self.layout, index, source)
                break


CLASSES = (
    FBR_UL_animation_rows,
    FBR_UL_mappings,
    FBR_MT_reuse_mapping,
    FBR_PT_main,
    FBR_PT_ik_window,
)
