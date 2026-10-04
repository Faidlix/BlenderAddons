import bpy
from bpy.types import Menu, Panel, UIList

from .model import flip_bone_name, reuse_mapping_items
from .operators import _mapping_axes_match


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


def _animation_row_columns(row):
    leading = row.row(align=True)
    leading.ui_units_x = 3.0
    content = row.split(factor=0.64)
    information = content.row(align=True)
    filename_and_action = information.split(factor=0.48)
    filename = filename_and_action.row(align=True)
    action_and_timing = filename_and_action.split(factor=0.52)
    action = action_and_timing.row(align=True)
    timing = action_and_timing.row(align=True)
    controls = content.row(align=True)
    return leading, filename, action, timing, controls


def _draw_multi_clip_header(layout, source, file_index):
    row = layout.row(align=True)
    leading, filename, action, _timing, _controls = _animation_row_columns(row)
    remove = leading.operator("fbr.remove_file", text="", icon="REMOVE")
    remove.file_index = file_index
    leading.prop(
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
    toggle = leading.operator("fbr.toggle_file", text="", icon=icon)
    toggle.index = file_index
    filename.label(text=f"名稱：{source.display_name}")
    action.label(text=f"{len(source.clips)} 個動畫")


def _draw_clip_row(context, layout, source, file_index, clip, clip_index, show_file_name):
    row = layout.row(align=True)
    leading, filename, action, timing, controls = _animation_row_columns(row)
    frame_text, seconds_text = _clip_timing_labels(context.scene, clip)
    if show_file_name:
        remove = leading.operator("fbr.remove_file", text="", icon="REMOVE")
        remove.file_index = file_index
        leading.label(text="")
        leading.prop(clip, "enabled", text="")
        filename.label(text=f"名稱：{source.display_name}")
        action.label(text=clip.action_name)
    else:
        filename.prop(clip, "enabled", text="")
        filename.label(text=clip.action_name)
    timing.alignment = "LEFT"
    frames = timing.row(align=True)
    frames.ui_units_x = 4.2
    frames.alignment = "LEFT"
    frames.label(text=frame_text)
    seconds = timing.row(align=True)
    seconds.ui_units_x = 5.2
    seconds.alignment = "LEFT"
    seconds.label(text=seconds_text)

    inplace = controls.operator(
        "fbr.toggle_clip_option",
        text="設為原地動畫",
        depress=clip.in_place,
    )
    inplace.file_index = file_index
    inplace.clip_index = clip_index
    inplace.option = "IN_PLACE"
    controls.separator(factor=0.15)
    copy = controls.operator(
        "fbr.toggle_clip_option",
        text="複製對稱動畫",
        depress=clip.mirror_mode == "COPY",
    )
    copy.file_index = file_index
    copy.clip_index = clip_index
    copy.option = "COPY"


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
    columns = row.split(factor=0.20)
    group_kind, is_group_parent, is_group_child = _mapping_group_info(source_file, item)
    source_cell = columns.row(align=True)
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
    target_and_tools = columns.split(factor=0.55)

    target_row = target_and_tools.row(align=True)
    target_row.alignment = "LEFT"
    if item.is_root:
        target_row.label(text="", icon="EVENT_R")
    else:
        target_row.label(text="", icon="BONE_DATA")
    select_button = target_row.row(align=True)
    select_button.ui_units_x = 10.0
    select = select_button.operator(
        "fbr.select_target_bone",
        text=("  " if is_group_child else "")
        + (_paired_mapping_label(source_file, item, "target_bone") or "未指定"),
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
    ik_slot = target_row.row(align=True)
    ik_slot.ui_units_x = 5.0
    ik = ik_slot.operator(
        "fbr.ik_settings",
        text="IK 已設定" if item.ik_enabled else "設定 IK",
        depress=item.ik_enabled,
    )
    ik.file_index = file_index
    ik.mapping_index = index
    ik.action = "START"

    tools = target_and_tools.row(align=False)
    tools.alignment = "RIGHT"
    pair = _mapping_pair(source_file, item)
    axes_match = bool(item.target_bone) and _mapping_axes_match(source, target, item) and (
        not pair or not pair.target_bone or _mapping_axes_match(source, target, pair)
    )
    axis_tools = tools.row(align=True)
    axis_tools.ui_units_x = 10.0
    axis_tools.label(text="O" if axes_match else "X")
    edit = axis_tools.operator("fbr.axis_correction", text="調整軸向")
    edit.file_index = file_index
    edit.mapping_index = index
    edit.action = "START"


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
    if active.ik_enabled:
        shape = editor.row(align=True)
        shape.prop(active, "ik_shape", text="")
        shape.prop(active, "ik_shape_scale", text="大小")
        solver = editor.row(align=True)
        solver.prop(active, "ik_chain_count")
        solver.prop(active, "ik_iterations")
        solver.prop(active, "ik_influence")
        options = editor.row(align=True)
        options.prop(active, "ik_use_tail", toggle=True)
        options.prop(active, "ik_use_rotation", toggle=True)
        options.prop(active, "ik_use_stretch", toggle=True)
    else:
        editor.label(text="IK 與控制骨已刪除", icon="INFO")
    buttons = editor.grid_flow(
        row_major=True, columns=4, even_columns=True, even_rows=True, align=True
    )
    delete = buttons.operator("fbr.delete_ik", text="刪除 IK")
    delete.file_index = file_index
    delete.mapping_index = source_file.active_mapping_index
    buttons.label(text="")
    cancel = buttons.operator("fbr.ik_settings", text="Cancel")
    cancel.file_index = file_index
    cancel.mapping_index = source_file.active_mapping_index
    cancel.action = "CANCEL"
    okay = buttons.operator("fbr.ik_settings", text="OK")
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
            if (data.axis_editing or data.ik_editing) and index < data.active_mapping_index:
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
        item_layout = layout.column(align=True)
        mapping_line = item_layout.row(align=True)
        mapping_line.enabled = not (data.axis_editing or data.ik_editing)
        _draw_mapping_row(context, mapping_line, data, item, index)
        if data.axis_editing and index == data.active_mapping_index:
            settings = context.scene.fbr_settings
            file_index = _source_file_index(settings, data)
            _draw_axis_correction(item_layout, file_index, data)
        elif data.ik_editing and index == data.active_mapping_index:
            settings = context.scene.fbr_settings
            file_index = _source_file_index(settings, data)
            _draw_ik_settings(item_layout, file_index, data)


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
    bl_label = "Faidlix_Retarget Motion · v0.6.1"
    bl_options = {"DEFAULT_CLOSED"}
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Faidlix"

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
        target_row.operator("fbr.clear_target_animation", text="刪除所有動畫", icon="TRASH")
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
            return

        if settings.files_expanded:
            file_list = source_box.column(align=True)
            for file_index, source in enumerate(settings.files):
                file_layout = file_list.column(align=True)
                has_multiple_clips = len(source.clips) > 1
                if has_multiple_clips:
                    _draw_multi_clip_header(file_layout, source, file_index)

                if not has_multiple_clips or source.expanded:
                    for clip_index, clip in enumerate(source.clips):
                        _draw_clip_row(
                            context,
                            file_layout,
                            source,
                            file_index,
                            clip,
                            clip_index,
                            show_file_name=not has_multiple_clips,
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
            preview_controls = row.row(align=True)
            preview_controls.ui_units_x = 18.0
            preview_active = (
                settings.preview_running and settings.preview_source_uid == source.uid
            )
            preview_controls.enabled = (
                bool(source.clips)
                and editing_index < 0
                and not settings.retarget_running
            )
            if len(source.clips) > 1:
                preview_controls.prop(source, "preview_clip", text="")
            preview = preview_controls.operator(
                "fbr.preview_animation",
                text="預覽",
                icon="ARMATURE_DATA",
                depress=preview_active,
            )
            preview.file_index = file_index
            preview.action = "HIDE" if preview_active else "SHOW"
            screen = getattr(context, "screen", None)
            animation_playing = bool(
                preview_active and screen and screen.is_animation_playing
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
            align = tools.operator("fbr.align_source_rig", text="骨架縮放對位")
            align.file_index = file_index
            axes = tools.operator("fbr.auto_align_axes", text="自動對軸向")
            axes.file_index = file_index
            tools.prop(settings, "auto_scale", text="Root 位移縮放", toggle=True)

            list_area = group.column(align=True)
            list_header = list_area.row(align=True)
            columns = list_header.split(factor=0.20)
            columns.label(text="來源骨骼")
            target_and_tools = columns.split(factor=0.55)
            target_header = target_and_tools.row(align=True)
            target_header.alignment = "LEFT"
            target_header.label(text="Target 骨骼")
            ik_header = target_header.row(align=True)
            ik_header.ui_units_x = 5.0
            ik_header.alignment = "CENTER"
            ik_header.label(text="IK 設定")
            tools_header = target_and_tools.row(align=False)
            tools_header.alignment = "RIGHT"
            axis_header = tools_header.row(align=True)
            axis_header.ui_units_x = 10.0
            axis_header.alignment = "RIGHT"
            axis_header.label(text="軸向相同")
            list_area.template_list(
                "FBR_UL_mappings",
                source.uid,
                source,
                "mappings",
                source,
                "active_mapping_index",
                rows=2 if (source.axis_editing or source.ik_editing) else 6,
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
        if target and enabled:
            check.label(text=f"{enabled} 個動畫片段可處理", icon="CHECKMARK")
        elif not target:
            check.label(text="請選擇主要骨架", icon="ERROR")
        else:
            check.label(text="請加入並啟用動畫片段", icon="ERROR")
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


CLASSES = (FBR_UL_mappings, FBR_MT_reuse_mapping, FBR_PT_main)
