import hashlib
import math
import re

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


def normalize_bone_name(name):
    value = name.rsplit(":", 1)[-1].lower()
    value = re.sub(r"[^a-z0-9]+", "", value)
    replacements = {
        "left": "l",
        "right": "r",
        "mixamorig": "",
        "def": "",
        "org": "",
        "mch": "",
        "jnt": "",
        "joint": "",
        "bone": "",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def flip_bone_name(name):
    flipped = bpy.utils.flip_name(name)
    if flipped != name:
        return flipped
    swaps = (
        ("Left", "Right"),
        ("left", "right"),
        ("LEFT", "RIGHT"),
        ("_L", "_R"),
        ("_l", "_r"),
        (" L ", " R "),
    )
    for left, right in swaps:
        if left in name:
            return name.replace(left, right)
        if right in name:
            return name.replace(right, left)
    return name


def armature_signature(obj):
    if not obj or obj.type != "ARMATURE":
        return ""
    records = []
    for bone in sorted(obj.data.bones, key=lambda item: item.name):
        records.append((bone.name, bone.parent.name if bone.parent else ""))
    return hashlib.sha256(repr(records).encode("utf8")).hexdigest()


def iter_action_fcurves(action):
    seen = set()
    legacy = getattr(action, "fcurves", None)
    if legacy:
        for curve in legacy:
            pointer = curve.as_pointer()
            if pointer not in seen:
                seen.add(pointer)
                yield curve
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            for channelbag in getattr(strip, "channelbags", ()):
                for curve in getattr(channelbag, "fcurves", ()):
                    pointer = curve.as_pointer()
                    if pointer not in seen:
                        seen.add(pointer)
                        yield curve


def action_bone_names(action):
    result = set()
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    for curve in iter_action_fcurves(action):
        match = pattern.search(curve.data_path)
        if match:
            result.add(match.group(1))
    return result


def action_keyframes(action):
    frames = set()
    for curve in iter_action_fcurves(action):
        frames.update(round(point.co.x, 6) for point in curve.keyframe_points)
    if frames:
        return sorted(frames)
    start, end = action.frame_range
    return list(range(math.floor(start), math.ceil(end) + 1))


_TARGET_ARMATURE_ITEMS_CACHE = {}
_PREVIEW_CLIP_ITEMS_CACHE = {}


def target_armature_items(self, context):
    items = [("0", "未選擇", "")]
    if context and context.scene:
        armatures = sorted(
            (
                obj
                for obj in context.scene.objects
                if obj.type == "ARMATURE" and not obj.get("_fbr_temp_source", False)
            ),
            key=lambda obj: obj.name.lower(),
        )
        items.extend((obj.name, obj.name, "") for obj in armatures)
    cache_key = tuple(item[0] for item in items)
    if cache_key not in _TARGET_ARMATURE_ITEMS_CACHE:
        _TARGET_ARMATURE_ITEMS_CACHE[cache_key] = items
    return _TARGET_ARMATURE_ITEMS_CACHE[cache_key]


def update_target_armature(self, context):
    if not self.target_armature:
        return
    obj = bpy.data.objects.get(self.target_armature)
    if not obj or obj.type != "ARMATURE":
        return
    view_layer = context.view_layer
    for selected in list(context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    view_layer.objects.active = obj


_REUSE_MAPPING_ITEMS_CACHE = {}


def reuse_mapping_items(self, context):
    items = [("SELF", "獨立骨架映射", "顯示並編輯此來源的骨骼映射")]
    if not context or not context.scene:
        return items
    settings = getattr(context.scene, "fbr_settings", None)
    if not settings:
        return items
    for source in settings.files:
        if source.uid != self.uid and source.mapping_is_independent:
            items.append((source.uid, f"沿用 {source.display_name}", "使用另一組的骨骼與軸向映射"))
    cache_key = (
        self.uid,
        tuple(
            (source.uid, source.display_name, source.mapping_is_independent)
            for source in settings.files
        ),
    )
    if cache_key not in _REUSE_MAPPING_ITEMS_CACHE:
        _REUSE_MAPPING_ITEMS_CACHE[cache_key] = items
    return _REUSE_MAPPING_ITEMS_CACHE[cache_key]


def update_reuse_mapping(self, context):
    self.mapping_expanded = False
    was_independent = self.mapping_is_independent
    self.mapping_is_independent = self.reuse_mapping == "SELF"
    became_independent = self.mapping_is_independent and not was_independent
    if not became_independent:
        return
    if self.mappings:
        self.mapping_expanded = True
        return
    if not context or not context.scene:
        return
    settings = getattr(context.scene, "fbr_settings", None)
    source = bpy.data.objects.get(self.source_object)
    target = bpy.data.objects.get(settings.target_armature) if settings else None
    if source and source.type == "ARMATURE" and target and target.type == "ARMATURE":
        from .retarget import build_automatic_mapping

        build_automatic_mapping(source, target, self.mappings)
        self.mapping_expanded = True


def update_axis_preview(self, context):
    if not context or not context.scene:
        return
    from .operators import _update_axis_preview

    _update_axis_preview(context, self)


def update_root_mapping(self, context):
    if self.is_root and context and context.scene:
        settings = getattr(context.scene, "fbr_settings", None)
        if settings:
            pointer = self.as_pointer()
            for source in settings.files:
                if not any(item.as_pointer() == pointer for item in source.mappings):
                    continue
                for item in source.mappings:
                    if item.as_pointer() != pointer and item.is_root:
                        item.is_root = False
                break
    update_axis_preview(self, context)


def update_ik_settings(self, context):
    if not context or not context.scene:
        return
    from .operators import _update_ik_preview

    _update_ik_preview(context, self)


def update_ik_pole_length(self, context):
    if not context or not context.scene:
        return
    from .operators import _update_ik_preview

    _update_ik_preview(context, self, move_pole=True)


def update_active_mapping_index(self, _context):
    if (
        (self.axis_editing or self.ik_editing)
        and self.active_mapping_index != self.axis_locked_mapping_index
    ):
        self.active_mapping_index = self.axis_locked_mapping_index


def preview_clip_items(self, _context):
    items = [
        (str(index), clip.action_name or f"Action {index + 1}", "")
        for index, clip in enumerate(self.clips)
    ]
    if not items:
        items = [("0", "沒有可預覽的動畫", "")]
    cache_key = tuple((identifier, name) for identifier, name, _description in items)
    if cache_key not in _PREVIEW_CLIP_ITEMS_CACHE:
        _PREVIEW_CLIP_ITEMS_CACHE[cache_key] = items
    return _PREVIEW_CLIP_ITEMS_CACHE[cache_key]


def update_preview_clip(self, context):
    if not context or not context.scene:
        return
    settings = getattr(context.scene, "fbr_settings", None)
    if not settings or not settings.preview_running or settings.preview_source_uid != self.uid:
        return
    from .operators import restart_animation_preview

    restart_animation_preview(context, self)


def update_forward_axis(self, context):
    if not context or not context.scene:
        return
    from .operators import _update_forward_axis_preview

    _update_forward_axis_preview(context, self)


class FBR_BoneMap(PropertyGroup):
    source_bone: StringProperty(name="來源骨骼")
    target_bone: StringProperty(name="目標骨骼")
    is_root: BoolProperty(name="Root", default=False, update=update_root_mapping)
    transfer_location: BoolProperty(name="位置", default=False, update=update_axis_preview)
    location_multiplier: FloatProperty(
        name="位置倍率",
        default=1.0,
        min=0.0,
        update=update_axis_preview,
    )
    rotation_offset: FloatVectorProperty(
        name="旋轉校正",
        subtype="EULER",
        unit="ROTATION",
        size=3,
        default=(0.0, 0.0, 0.0),
        update=update_axis_preview,
    )
    pair_rotation_offset: FloatVectorProperty(
        name="左右相對旋轉",
        subtype="EULER",
        unit="ROTATION",
        size=3,
        default=(0.0, 0.0, 0.0),
        update=update_axis_preview,
    )
    reset_is_root: BoolProperty(default=False, options={"HIDDEN"})
    reset_transfer_location: BoolProperty(default=False, options={"HIDDEN"})
    reset_location_multiplier: FloatProperty(default=1.0, options={"HIDDEN"})
    reset_rotation_offset: FloatVectorProperty(
        size=3,
        default=(0.0, 0.0, 0.0),
        options={"HIDDEN"},
    )
    ik_enabled: BoolProperty(default=False, options={"HIDDEN"})
    ik_control_bone: StringProperty(default="", options={"HIDDEN"})
    ik_pole_bone: StringProperty(default="", options={"HIDDEN"})
    ik_chain_count: IntProperty(
        name="關聯骨頭數",
        default=2,
        min=1,
        max=255,
        update=update_ik_settings,
    )
    ik_iterations: IntProperty(
        name="迭代次數",
        default=500,
        min=0,
        max=10000,
        update=update_ik_settings,
    )
    ik_influence: FloatProperty(
        name="影響",
        default=1.0,
        min=0.0,
        max=1.0,
        update=update_ik_settings,
    )
    ik_use_tail: BoolProperty(name="使用骨尾", default=True, update=update_ik_settings)
    ik_use_pole: BoolProperty(name="使用 Pole", default=True, update=update_ik_settings)
    ik_pole_length: FloatProperty(
        name="調整長度", default=1.0, min=-10.0, max=10.0,
        update=update_ik_pole_length,
    )
    ik_pole_size_ratio: FloatProperty(
        name="大小", default=0.7, min=0.01, max=10.0,
        description="Pole 顯示大小相對於 IK 控制器的比例",
        update=update_ik_settings,
    )
    ik_use_rotation: BoolProperty(
        name="使用旋轉",
        default=False,
        update=update_ik_settings,
    )
    ik_use_stretch: BoolProperty(
        name="允許拉伸",
        default=False,
        update=update_ik_settings,
    )
    ik_shape: EnumProperty(
        name="控制器樣式",
        items=(
            ("BOX", "Box Wireframe", "方盒線框"),
            ("SPHERE", "球形", "球形線框"),
            ("CIRCLE", "圓圈", "圓形線框"),
            ("SQUARE", "方形", "方形線框"),
        ),
        default="BOX",
        update=update_ik_settings,
    )
    ik_shape_scale: FloatProperty(
        name="控制器大小",
        default=0.05,
        min=0.01,
        soft_max=5.0,
        update=update_ik_settings,
    )
    ik_shape_wire_width: FloatProperty(
        name="線框粗細",
        default=2.0,
        min=1.0,
        max=16.0,
        update=update_ik_settings,
    )
    ik_shape_color: FloatVectorProperty(
        name="顏色",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(1.0, 0.45, 0.05),
        update=update_ik_settings,
    )


class FBR_Clip(PropertyGroup):
    enabled: BoolProperty(name="啟用", default=True)
    action_name: StringProperty(name="Action")
    source_action_name: StringProperty(options={"HIDDEN"})
    custom_name: StringProperty(name="自訂名稱")
    frame_start: FloatProperty(name="開始", default=0.0)
    frame_end: FloatProperty(name="結束", default=0.0)
    in_place: BoolProperty(name="原地動畫", default=False)
    mirror_mode: EnumProperty(
        name="翻轉",
        items=(
            ("NONE", "無", "不翻轉"),
            ("MIRROR", "左右翻轉", "只輸出左右翻轉版本"),
            ("COPY", "複製對稱動畫", "同時輸出原版與左右對稱版本"),
        ),
        default="NONE",
    )
    custom_start: IntProperty(name="起始影格", default=-1, min=-1)


class FBR_AnimationRow(PropertyGroup):
    file_uid: StringProperty(options={"HIDDEN"})
    clip_index: IntProperty(default=-1, options={"HIDDEN"})


class FBR_SourceFile(PropertyGroup):
    uid: StringProperty()
    display_name: StringProperty(name="檔案")
    filepath: StringProperty(subtype="FILE_PATH")
    file_type: StringProperty()
    source_object: StringProperty(name="來源骨架")
    signature: StringProperty()
    expanded: BoolProperty(default=True)
    mapping_expanded: BoolProperty(default=False)
    reused_expanded: BoolProperty(default=False)
    hands_expanded: BoolProperty(default=True)
    feet_expanded: BoolProperty(default=True)
    mapping_is_independent: BoolProperty(default=True, options={"HIDDEN"})
    reuse_mapping: EnumProperty(items=reuse_mapping_items, update=update_reuse_mapping)
    clips: CollectionProperty(type=FBR_Clip)
    mappings: CollectionProperty(type=FBR_BoneMap)
    active_mapping_index: IntProperty(default=0, update=update_active_mapping_index)
    axis_editing: BoolProperty(default=False, options={"SKIP_SAVE"})
    axis_locked_mapping_index: IntProperty(default=0, options={"SKIP_SAVE"})
    axis_backup_rotation: FloatVectorProperty(size=3, options={"SKIP_SAVE"})
    axis_backup_transfer_location: BoolProperty(options={"SKIP_SAVE"})
    axis_backup_location_multiplier: FloatProperty(default=1.0, options={"SKIP_SAVE"})
    axis_backup_is_root: BoolProperty(options={"SKIP_SAVE"})
    axis_backup_pair_rotation: FloatVectorProperty(size=3, options={"SKIP_SAVE"})
    preview_scale: FloatProperty(default=1.0, min=0.0001, options={"HIDDEN"})
    alignment_original_valid: BoolProperty(default=False, options={"HIDDEN"})
    alignment_original_matrix: FloatVectorProperty(
        size=16,
        default=(
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ),
        options={"HIDDEN"},
    )
    alignment_valid: BoolProperty(default=False, options={"HIDDEN"})
    alignment_matrix: FloatVectorProperty(
        size=16,
        default=(
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ),
        options={"HIDDEN"},
    )
    alignment_scale: FloatProperty(default=1.0, min=1.0e-8, options={"HIDDEN"})
    preview_clip: EnumProperty(items=preview_clip_items, update=update_preview_clip)
    ik_editing: BoolProperty(default=False, options={"SKIP_SAVE"})
    ik_existing_view: BoolProperty(default=False, options={"SKIP_SAVE"})
    ik_backup_enabled: BoolProperty(options={"SKIP_SAVE"})
    ik_backup_control_bone: StringProperty(options={"SKIP_SAVE"})
    ik_backup_pole_bone: StringProperty(options={"SKIP_SAVE"})
    ik_backup_chain_count: IntProperty(default=2, options={"SKIP_SAVE"})
    ik_backup_iterations: IntProperty(default=500, options={"SKIP_SAVE"})
    ik_backup_influence: FloatProperty(default=1.0, options={"SKIP_SAVE"})
    ik_backup_use_tail: BoolProperty(default=True, options={"SKIP_SAVE"})
    ik_backup_use_pole: BoolProperty(default=True, options={"SKIP_SAVE"})
    ik_backup_pole_length: FloatProperty(default=0.5, options={"SKIP_SAVE"})
    ik_backup_pole_size_ratio: FloatProperty(default=0.7, options={"SKIP_SAVE"})
    ik_backup_use_rotation: BoolProperty(options={"SKIP_SAVE"})
    ik_backup_use_stretch: BoolProperty(options={"SKIP_SAVE"})
    ik_backup_shape: StringProperty(default="BOX", options={"SKIP_SAVE"})
    ik_backup_shape_scale: FloatProperty(default=0.05, options={"SKIP_SAVE"})
    ik_backup_shape_wire_width: FloatProperty(default=2.0, options={"SKIP_SAVE"})
    ik_backup_shape_color: FloatVectorProperty(
        size=3,
        default=(1.0, 0.45, 0.05),
        options={"SKIP_SAVE"},
    )
    source_forward_axis: EnumProperty(
        name="來源前方",
        items=(
            ("AUTO", "自動", "依腳、左右與上下骨骼自動判斷"),
            ("+X", "+X", "來源角色面向 +X"),
            ("-X", "-X", "來源角色面向 -X"),
            ("+Y", "+Y", "來源角色面向 +Y"),
            ("-Y", "-Y", "來源角色面向 -Y"),
        ),
        default="AUTO",
        update=update_forward_axis,
    )
    target_forward_axis: EnumProperty(
        name="Target 前方",
        items=(
            ("AUTO", "自動", "依腳、左右與上下骨骼自動判斷"),
            ("+X", "+X", "Target 角色面向 +X"),
            ("-X", "-X", "Target 角色面向 -X"),
            ("+Y", "+Y", "Target 角色面向 +Y"),
            ("-Y", "-Y", "Target 角色面向 -Y"),
        ),
        default="AUTO",
        update=update_forward_axis,
    )
    global_axis_correction: FloatVectorProperty(
        size=4,
        subtype="QUATERNION",
        default=(1.0, 0.0, 0.0, 0.0),
        options={"HIDDEN"},
    )


class FBR_Settings(PropertyGroup):
    target_armature: EnumProperty(
        name="Target Armature",
        items=target_armature_items,
        update=update_target_armature,
    )
    files: CollectionProperty(type=FBR_SourceFile)
    active_file_index: IntProperty(default=0)
    animation_rows: CollectionProperty(type=FBR_AnimationRow)
    active_animation_row_index: IntProperty(default=0)
    files_expanded: BoolProperty(default=True)
    reused_expanded: BoolProperty(default=False)
    animation_info_factor: FloatProperty(
        name="名稱／時間寬度",
        default=0.68,
        min=0.45,
        max=0.82,
    )
    animation_file_factor: FloatProperty(
        name="檔案名稱寬度",
        default=0.38,
        min=0.15,
        max=0.65,
    )
    animation_action_factor: FloatProperty(
        name="檔案／動畫名稱寬度",
        default=0.68,
        min=0.40,
        max=0.82,
    )
    animation_options_factor: FloatProperty(
        name="原地動畫寬度", default=0.5, min=0.2, max=0.8,
    )
    animation_mirror_fraction: FloatProperty(
        name="對稱動畫欄寬", default=0.16, min=0.10, max=0.30,
    )
    animation_child_name_factor: FloatProperty(
        name="子動畫名稱寬度",
        default=0.62,
        min=0.35,
        max=0.82,
    )
    mapping_source_factor: FloatProperty(
        name="來源骨骼寬度",
        default=0.22,
        min=0.12,
        max=0.42,
    )
    mapping_target_factor: FloatProperty(
        name="Target 骨骼右界",
        default=0.58,
        min=0.38,
        max=0.76,
    )
    mapping_axis_factor: FloatProperty(
        name="IK 設定右界", default=0.70, min=0.55, max=0.88,
    )
    target_actions_expanded: BoolProperty(default=False)
    retarget_completed_count: IntProperty(default=0, min=0)
    retarget_total_count: IntProperty(default=0, min=0)
    retarget_batch_id: StringProperty(default="")
    retarget_plan_signature: StringProperty(default="", options={"HIDDEN"})
    target_preview_action: StringProperty(default="", options={"SKIP_SAVE"})
    output_mode: EnumProperty(
        name="輸出",
        items=(
            ("SEPARATE", "每段獨立 Action", "每個來源片段建立一個 Action"),
            ("MERGED", "合併長 Action", "依序放進同一個 Action"),
        ),
        default="SEPARATE",
    )
    naming_mode: EnumProperty(
        name="命名",
        items=(
            ("FILE_ACTION", "檔名_Action 名稱", "檔名加 Action 名稱"),
            ("ACTION", "只用 Action 名稱", "只使用來源 Action 名稱"),
            ("CUSTOM", "使用片段自訂名稱", "展開每個片段的自訂名稱"),
        ),
        default="FILE_ACTION",
    )
    merged_action_name: StringProperty(name="Action 名稱", default="Combined_Animation")
    merged_start: IntProperty(name="起始影格", default=1)
    merged_gap: IntProperty(name="片段間隔", default=5, min=0)
    key_mode: EnumProperty(
        name="Key 處理",
        items=(
            ("BAKE", "每格 Bake", "每個整數影格建立 Key"),
            ("SOURCE", "只取來源 Key", "只在來源動畫已有 Key 的影格建立 Key"),
            ("SIMPLIFY", "每格 Bake 後精簡", "Bake 後移除誤差範圍內的中間 Key"),
        ),
        default="SIMPLIFY",
    )
    ik_bake_mode: EnumProperty(
        name="IK 處理",
        items=(
            ("POSE", "姿勢 Bake", "沿用目前的姿勢烘焙流程"),
            ("EXISTING", "沿用目標 IK", "使用目標骨架已有的 IK 控制骨與 Pole，不新增 IK"),
        ),
        default="POSE",
    )
    rotation_tolerance: FloatProperty(
        name="旋轉誤差",
        default=math.radians(0.5),
        min=0.0,
        unit="ROTATION",
    )
    location_tolerance: FloatProperty(name="位置誤差", default=0.05, min=0.0)
    fake_user: BoolProperty(name="Fake User", default=True)
    extract_root_motion: BoolProperty(
        name="Extract Root Motion",
        description="將 Root 的水平位移抽出到 Target 的 c_traj 軌跡骨",
        default=False,
    )
    auto_scale: BoolProperty(
        name="Root 位移縮放",
        description="依來源與 Target 骨架尺寸比例自動縮放 Root 位移",
        default=True,
    )
    update_status: StringProperty(default="")
    retarget_running: BoolProperty(default=False, options={"SKIP_SAVE"})
    retarget_progress: FloatProperty(default=0.0, min=0.0, max=1.0, options={"SKIP_SAVE"})
    retarget_status: StringProperty(default="", options={"SKIP_SAVE"})
    preview_running: BoolProperty(default=False, options={"SKIP_SAVE"})
    preview_source_uid: StringProperty(default="", options={"SKIP_SAVE"})
    preview_mode: StringProperty(default="", options={"SKIP_SAVE"})


def rebuild_animation_rows(settings):
    """Rebuild the flat UI list without changing per-file expansion state."""
    settings.animation_rows.clear()
    for source in settings.files:
        if len(source.clips) > 1:
            row = settings.animation_rows.add()
            row.file_uid = source.uid
            row.clip_index = -1
        for clip_index, _clip in enumerate(source.clips):
            row = settings.animation_rows.add()
            row.file_uid = source.uid
            row.clip_index = clip_index
    settings.active_animation_row_index = min(
        settings.active_animation_row_index,
        max(0, len(settings.animation_rows) - 1),
    )


def animation_rows_are_current(settings):
    expected = []
    for source in settings.files:
        if len(source.clips) > 1:
            expected.append((source.uid, -1))
        expected.extend((source.uid, index) for index in range(len(source.clips)))
    actual = [(row.file_uid, row.clip_index) for row in settings.animation_rows]
    return actual == expected


CLASSES = (
    FBR_BoneMap,
    FBR_Clip,
    FBR_AnimationRow,
    FBR_SourceFile,
    FBR_Settings,
)
