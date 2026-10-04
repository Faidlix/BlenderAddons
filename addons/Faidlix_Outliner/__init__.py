from __future__ import annotations


bl_info = {
    "name": "Faidlix_Outliner",
    "author": "Faidlix",
    "version": (0, 2, 14),
    "blender": (5, 2, 0),
    "location": "Outliner > left overlay gutter and context menu",
    "description": "Three-state hierarchy selection for objects and collections",
    "category": "Interface",
}

import json
import importlib
import os

import addon_utils
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator
from gpu_extras.batch import batch_for_shader

# Blender reloads the package module after an in-process extension update, but
# keeps already imported sibling modules in sys.modules. Reload them explicitly
# so __init__.py and core.py can never run with mismatched function signatures.
from . import _faidlix_update_all as _update_all_module
from . import core as _core_module

importlib.reload(_update_all_module)
importlib.reload(_core_module)

make_classes = _update_all_module.make_classes

from .core import (
    STATE_ALL,
    STATE_NONE,
    STATE_PARTIAL,
    apply_restriction,
    restriction_value,
    selection_state,
    target_objects,
    unique_objects,
)


ADDON_ID = __package__
UPDATE_ALL_CLASSES = make_classes("outliner", "Outliner")
ADDON_VERSION = (0, 2, 14)
PACKAGE_ID = "faidlix_outliner"
GITHUB_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)
_DRAW_HANDLE = None
_ORIGINAL_HEADER_DRAW = None
_SKIPPED_REGISTRATION = False
_KEYMAPS = []
_ROW_CACHE = {}
_UNSUPPORTED_ROWS = set()
_PENDING_UPDATE = None
_SHIFTED_AREAS = set()
_ROW_SCAN_PENDING = False

OVERLAY_BOX_SIZE = 14
OVERLAY_ICON_GAP = 9
CHECKBOX_DEFAULT_X = 42
TREE_CONTENT_OFFSET = 0
TREE_RESET_OFFSET = 4096
LAYOUT_VERSION = 5
LOGICAL_SELECTION_KEY = "_faidlix_outliner_logical_selection"


def _preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def _logical_selection():
    value = bpy.app.driver_namespace.get(LOGICAL_SELECTION_KEY)
    if not isinstance(value, set):
        value = set()
        bpy.app.driver_namespace[LOGICAL_SELECTION_KEY] = value
    return value


def _effective_selection_state(objects, view_layer=None):
    return selection_state(objects, view_layer, _logical_selection())


def _bone_key(armature, bone):
    return f"BONE:{armature.name}:{bone.name}"


def _bone_selection_handle(armature, bone):
    if armature.is_editmode:
        return armature.edit_bones.get(bone.name)
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE" and obj.data == armature and obj.pose:
            pose_bone = obj.pose.bones.get(bone.name)
            if pose_bone is not None:
                return pose_bone
    return None


def _target_bones(target):
    if isinstance(target, bpy.types.Armature):
        return [(target, bone) for bone in target.bones]
    pairs = []
    seen = set()
    for obj in target_objects(target):
        if obj.type != "ARMATURE" or obj.data is None:
            continue
        for bone in obj.data.bones:
            key = (obj.data.as_pointer(), bone.name)
            if key not in seen:
                seen.add(key)
                pairs.append((obj.data, bone))
    return pairs


def _bone_selected(armature, bone):
    handle = _bone_selection_handle(armature, bone)
    return _bone_key(armature, bone) in _logical_selection() or bool(
        handle and handle.select
    )


def _effective_target_state(target, view_layer=None):
    objects = target_objects(target)
    bones = _target_bones(target)
    total = len(objects) + len(bones)
    if total == 0:
        return None
    selected = sum(
        1
        for obj in objects
        if selection_state([obj], view_layer, _logical_selection()) == STATE_ALL
    )
    selected += sum(1 for armature, bone in bones if _bone_selected(armature, bone))
    if selected == 0:
        return STATE_NONE
    if selected == total:
        return STATE_ALL
    return STATE_PARTIAL


def _native_selectable(obj, view_layer):
    if view_layer is None or obj.name not in view_layer.objects:
        return False
    if obj.hide_viewport or obj.hide_select:
        return False
    try:
        return not obj.hide_get(view_layer=view_layer)
    except (RuntimeError, TypeError):
        try:
            return not obj.hide_get()
        except RuntimeError:
            return False


def _set_effective_selected(objects, selected, view_layer=None):
    logical = _logical_selection()
    changed = 0
    for obj in unique_objects(objects):
        if selected and not _native_selectable(obj, view_layer):
            logical.add(obj.name)
            changed += 1
            continue
        logical.discard(obj.name)
        if view_layer is not None and obj.name not in view_layer.objects:
            changed += 1
            continue
        try:
            obj.select_set(bool(selected), view_layer=view_layer)
        except (RuntimeError, TypeError):
            try:
                obj.select_set(bool(selected))
            except RuntimeError:
                if selected:
                    logical.add(obj.name)
        changed += 1
    return changed


def _set_bones_selected(pairs, selected):
    logical = _logical_selection()
    changed = 0
    for armature, bone in pairs:
        key = _bone_key(armature, bone)
        if selected and (bone.hide or bone.hide_select):
            logical.add(key)
            changed += 1
            continue
        logical.discard(key)
        handle = _bone_selection_handle(armature, bone)
        if handle is None:
            if selected:
                logical.add(key)
            changed += 1
            continue
        try:
            handle.select = bool(selected)
            if hasattr(handle, "select_head"):
                handle.select_head = bool(selected)
                handle.select_tail = bool(selected)
        except RuntimeError:
            if selected:
                logical.add(key)
        changed += 1
    return changed


def _set_effective_target_selected(target, selected, view_layer=None):
    return _set_effective_selected(target_objects(target), selected, view_layer) + _set_bones_selected(
        _target_bones(target), selected
    )


def _remember_effective_selection(objects, view_layer=None):
    """Keep selected items selected logically if a restriction hides/locks them."""
    logical = _logical_selection()
    for obj in unique_objects(objects):
        if obj.name in logical:
            continue
        try:
            selected = obj.select_get(view_layer=view_layer)
        except (RuntimeError, TypeError):
            try:
                selected = obj.select_get()
            except RuntimeError:
                selected = False
        if selected:
            logical.add(obj.name)


def _promote_logical_selection():
    """Convert logical selections to native selection when they become available."""
    logical = _logical_selection()
    view_layer = getattr(bpy.context, "view_layer", None)
    if not logical or view_layer is None:
        return
    for name in tuple(logical):
        if name.startswith("BONE:"):
            found = False
            for armature in bpy.data.armatures:
                for bone in armature.bones:
                    if _bone_key(armature, bone) != name:
                        continue
                    found = True
                    if not bone.hide and not bone.hide_select:
                        handle = _bone_selection_handle(armature, bone)
                        if handle is None:
                            break
                        try:
                            handle.select = True
                            if hasattr(handle, "select_head"):
                                handle.select_head = True
                                handle.select_tail = True
                            logical.discard(name)
                        except RuntimeError:
                            pass
                    break
                if found:
                    break
            if not found:
                logical.discard(name)
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            logical.discard(name)
            continue
        if not _native_selectable(obj, view_layer):
            continue
        try:
            obj.select_set(True, view_layer=view_layer)
            logical.discard(name)
        except RuntimeError:
            pass


def _disable_duplicate_addons():
    """Keep one package source from registering duplicate draw handlers.

    A ZIP installed into user_default and the canonical GitHub package can
    otherwise both be enabled because Blender treats their module names as
    different add-ons even though their operators and draw callbacks are the
    same. Remote repositories take priority over manually installed copies.
    """
    preferences = bpy.context.preferences
    def is_remote_module(module_name):
        parts = module_name.split(".")
        if len(parts) < 3 or parts[0] != "bl_ext":
            return False
        repo_module = parts[1]
        return any(
            repo.module == repo_module and bool(repo.remote_url)
            for repo in preferences.extensions.repos
        )

    current_is_remote = is_remote_module(ADDON_ID)
    duplicates = [
        module_name
        for module_name in preferences.addons.keys()
        if module_name != ADDON_ID
        and (
            module_name == PACKAGE_ID
            or module_name.endswith(f".{PACKAGE_ID}")
        )
    ]
    for module_name in duplicates:
        # user_default normally loads first. It must not disable a remote copy
        # that will load later and become the canonical owner of the UI.
        if not current_is_remote and is_remote_module(module_name):
            print(f"FAIDLIX_OUTLINER_DEFERRED_TO_REMOTE={module_name}")
            return False
        try:
            addon_utils.disable(module_name, default_set=True)
            print(f"FAIDLIX_OUTLINER_DISABLED_DUPLICATE={module_name}")
        except Exception as exc:
            print(f"FAIDLIX_OUTLINER_DUPLICATE_ERROR={module_name}:{exc}")
    return True


def _tag_outliners():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "OUTLINER":
                area.tag_redraw()


def _migrate_layout_preferences():
    preferences = _preferences()
    if preferences is None or preferences.layout_version >= LAYOUT_VERSION:
        return
    preferences.checkbox_x = CHECKBOX_DEFAULT_X
    preferences.layout_version = LAYOUT_VERSION


def _pan_outliner_area(window, area, delta):
    region = next((region for region in area.regions if region.type == "WINDOW"), None)
    if region is None:
        return False
    try:
        with bpy.context.temp_override(window=window, area=area, region=region):
            result = bpy.ops.view2d.pan(deltax=int(delta), deltay=0)
        return result == {"FINISHED"}
    except (RuntimeError, TypeError):
        return False


def _ensure_tree_content_offset():
    """Restore the native tree after upgrading from left-gutter versions."""
    _migrate_layout_preferences()
    _promote_logical_selection()
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return 1.0
    scale = bpy.context.preferences.system.ui_scale
    reset_delta = max(1, int(TREE_RESET_OFFSET * scale))
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "OUTLINER":
                continue
            pointer = area.as_pointer()
            if pointer in _SHIFTED_AREAS:
                continue
            _pan_outliner_area(window, area, reset_delta)
            _SHIFTED_AREAS.add(pointer)
            area.tag_redraw()
    return 1.0


def _restore_tree_content_offset():
    _SHIFTED_AREAS.clear()


def _github_repository(context):
    for index, repo in enumerate(context.preferences.extensions.repos):
        if repo.remote_url.rstrip("/") == GITHUB_REPOSITORY_URL.rstrip("/"):
            return index, repo
    return None, None


def _ensure_github_repository(context):
    index, repo = _github_repository(context)
    if repo is not None:
        repo.enabled = True
        repo.use_sync_on_startup = True
        return index, repo
    result = bpy.ops.preferences.extension_repo_add(
        name="Faidlix Outliner GitHub",
        remote_url=GITHUB_REPOSITORY_URL,
        use_sync_on_startup=True,
        type="REMOTE",
    )
    if result != {"FINISHED"}:
        return None, None
    return _github_repository(context)


def _version_tuple(version):
    try:
        return tuple(int(part) for part in version.split("."))
    except (AttributeError, TypeError, ValueError):
        return ()


def _latest_version_from_index(index_data):
    versions = [
        _version_tuple(item.get("version"))
        for item in index_data.get("data", [])
        if item.get("id") == PACKAGE_ID
    ]
    return max((version for version in versions if version), default=())


def _cached_repository_index(repo):
    path = os.path.join(repo.directory, ".blender_ext", "index.json")
    try:
        with open(path, "r", encoding="utf8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _preference_snapshot(context):
    preferences = _preferences(context)
    if preferences is None:
        return {}
    return {
        "show_overlay": preferences.show_overlay,
        "show_batch_eye": preferences.show_batch_eye,
        "batch_selected_restrictions": preferences.batch_selected_restrictions,
        "checkbox_x": preferences.checkbox_x,
        "layout_version": preferences.layout_version,
    }


def _restore_preference_snapshot(context, snapshot):
    preferences = _preferences(context)
    if preferences is None:
        return
    for name, value in snapshot.items():
        if hasattr(preferences, name):
            setattr(preferences, name, value)


def _apply_pending_update():
    """Install after the initiating operator has returned.

    Blender cannot safely replace an enabled extension while an operator class
    from that extension is still executing. A timer calls this function on the
    next event-loop turn, disables the old module cleanly, installs the newer
    package, and then restores preferences on the newly registered module.
    """
    global _PENDING_UPDATE
    pending = _PENDING_UPDATE
    _PENDING_UPDATE = None
    if not pending:
        return None

    module_name = pending["module_name"]
    repo_index = pending["repo_index"]
    target_module_name = pending["target_module_name"]
    snapshot = pending["preferences"]
    version = pending["version"]
    package_id = PACKAGE_ID
    bpy_module = bpy

    try:
        result = bpy_module.ops.preferences.addon_disable(module=module_name)
        if result != {"FINISHED"}:
            raise RuntimeError("could not disable the current add-on")
        source_repo_index = None
        module_parts = module_name.split(".")
        source_repo_module = module_parts[1] if len(module_parts) >= 3 else ""
        for index, repo in enumerate(bpy_module.context.preferences.extensions.repos):
            if repo.module == source_repo_module:
                source_repo_index = index
                break
        if source_repo_index is not None and source_repo_index != repo_index:
            result = bpy_module.ops.extensions.package_uninstall(
                repo_index=source_repo_index,
                pkg_id=package_id,
            )
            if result != {"FINISHED"}:
                raise RuntimeError("could not remove the package from its old repository")
        result = bpy_module.ops.extensions.package_install(
            repo_index=repo_index,
            pkg_id=package_id,
            enable_on_install=True,
        )
        if result != {"FINISHED"}:
            raise RuntimeError("package installation did not finish")
        addon = bpy_module.context.preferences.addons.get(target_module_name)
        preferences = addon.preferences if addon else None
        if preferences is not None:
            for name, value in snapshot.items():
                if hasattr(preferences, name):
                    setattr(preferences, name, value)
        bpy_module.ops.wm.save_userpref()
        print(f"FAIDLIX_OUTLINER_UPDATED={version}")
    except Exception as exc:
        print(f"FAIDLIX_OUTLINER_UPDATE_ERROR={exc}")
        try:
            bpy_module.ops.preferences.addon_enable(module=module_name)
        except Exception:
            pass
    return None


def _target_from_name(kind, name):
    if kind == "SCENE":
        return bpy.data.scenes.get(name)
    if kind == "OBJECT":
        return bpy.data.objects.get(name)
    if kind == "COLLECTION":
        return bpy.data.collections.get(name)
    if kind == "ARMATURE":
        return bpy.data.armatures.get(name)
    return None


def _target_identity(target):
    if isinstance(target, bpy.types.Scene):
        return "SCENE", target.name
    if isinstance(target, bpy.types.Object):
        return "OBJECT", target.name
    if isinstance(target, bpy.types.Collection):
        return "COLLECTION", target.name
    if isinstance(target, bpy.types.Armature):
        return "ARMATURE", target.name
    return None


def _target_batches_current_selection(target, view_layer):
    if isinstance(target, bpy.types.Object):
        return _effective_selection_state([target], view_layer) == STATE_ALL
    return _effective_target_state(target, view_layer) == STATE_ALL


def _objects_for_batch(context, target):
    objects = target_objects(target)
    preferences = _preferences(context)
    if preferences is not None and not preferences.batch_selected_restrictions:
        return objects
    if not _target_batches_current_selection(target, context.view_layer):
        return objects
    logical = _logical_selection()
    selected = [
        obj
        for obj in bpy.data.objects
        if obj.name in logical
        or (obj.name in context.view_layer.objects and obj.select_get())
    ]
    return unique_objects(selected or objects)


def _snapshot_selection(context):
    selected = [obj for obj in context.view_layer.objects if obj.select_get()]
    return selected, context.view_layer.objects.active


def _restore_selection(context, snapshot):
    selected, active = snapshot
    for obj in context.view_layer.objects:
        obj.select_set(False)
    for obj in selected:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    if active and active.name in context.view_layer.objects:
        context.view_layer.objects.active = active


def _probe_row(context, y):
    """Ask Blender's Outliner to identify a row, then restore object selection."""
    snapshot = _snapshot_selection(context)
    result = bpy.ops.outliner.select_box(
        xmin=0,
        xmax=max(1, context.region.width - 1),
        ymin=max(0, y - 2),
        ymax=min(context.region.height - 1, y + 2),
        wait_for_input=False,
        mode="SET",
    )
    selected_ids = list(getattr(context, "selected_ids", ()))
    _restore_selection(context, snapshot)
    if result != {"FINISHED"}:
        return None
    for item in selected_ids:
        if isinstance(item, (bpy.types.Scene, bpy.types.Object, bpy.types.Collection, bpy.types.Armature)):
            return item
        if isinstance(item, bpy.types.ViewLayer):
            return context.scene
    return None


def _scan_visible_rows():
    """Classify visible rows outside draw callbacks so detail rows stay blank."""
    global _ROW_SCAN_PENDING
    _ROW_SCAN_PENDING = False
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return None
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type != "OUTLINER":
                continue
            region = next((item for item in area.regions if item.type == "WINDOW"), None)
            if region is None:
                continue
            area_pointer = area.as_pointer()
            for key in [key for key in _ROW_CACHE if key[0] == area_pointer]:
                _ROW_CACHE.pop(key, None)
            _UNSUPPORTED_ROWS.difference_update(
                key for key in tuple(_UNSUPPORTED_ROWS) if key[0] == area_pointer
            )
            with bpy.context.temp_override(window=window, area=area, region=region):
                context = bpy.context
                row_height = max(16, int(20 * context.preferences.system.ui_scale))
                slot = 0
                unresolved_run = 0
                center_y = region.height - row_height * 0.5
                while center_y > -row_height:
                    key = (area_pointer, slot)
                    target = _probe_row(context, int(center_y))
                    identity = _target_identity(target)
                    if identity and (target_objects(target) or _target_bones(target)):
                        _ROW_CACHE[key] = identity
                        unresolved_run = 0
                    else:
                        _UNSUPPORTED_ROWS.add(key)
                        unresolved_run += 1
                    slot += 1
                    center_y -= row_height
                    # Empty space below a collapsed tree otherwise causes many
                    # expensive Outliner selection probes. Eight unresolved
                    # rows still leaves room for common data-detail sections.
                    if slot > 2 and unresolved_run >= 8:
                        break
                # Blender's row selection operator does not consistently
                # return an ID for the View Layer root. It is nevertheless a
                # stable first row and semantically represents the Scene.
                if context.space_data.display_mode == "VIEW_LAYER":
                    root_key = (area_pointer, 0)
                    _ROW_CACHE[root_key] = ("SCENE", context.scene.name)
                    _UNSUPPORTED_ROWS.discard(root_key)
            area.tag_redraw()
    return None


def _schedule_row_scan(delay=0.01):
    global _ROW_SCAN_PENDING
    if _ROW_SCAN_PENDING:
        return
    _ROW_SCAN_PENDING = True
    bpy.app.timers.register(_scan_visible_rows, first_interval=delay)


def _invalidate_area_rows(context):
    """Hide stale boxes immediately while a new visible-row scan is pending."""
    area_pointer = context.area.as_pointer()
    for key in [key for key in _ROW_CACHE if key[0] == area_pointer]:
        _ROW_CACHE.pop(key, None)
    row_height = max(16, int(20 * context.preferences.system.ui_scale))
    row_count = max(1, context.region.height // row_height + 2)
    _UNSUPPORTED_ROWS.update((area_pointer, slot) for slot in range(row_count))
    if context.space_data.display_mode == "VIEW_LAYER":
        root_key = (area_pointer, 0)
        _ROW_CACHE[root_key] = ("SCENE", context.scene.name)
        _UNSUPPORTED_ROWS.discard(root_key)
    context.area.tag_redraw()


def _cache_key(context, event):
    area = context.area.as_pointer()
    row_height = max(16, int(20 * context.preferences.system.ui_scale))
    slot = max(0, (context.region.height - event.mouse_region_y) // row_height)
    return area, slot


def _cache_target(context, event, target):
    identity = _target_identity(target)
    if identity:
        _ROW_CACHE[_cache_key(context, event)] = identity


def _restriction_columns(context):
    space = context.space_data
    if space.display_mode == "VIEW_LAYER":
        return (
            ("show_restrict_column_enable", None),
            ("show_restrict_column_select", "SELECT"),
            ("show_restrict_column_hide", "HIDE"),
            ("show_restrict_column_viewport", "VIEWPORT"),
            ("show_restrict_column_render", "RENDER"),
            ("show_restrict_column_holdout", None),
            ("show_restrict_column_indirect_only", None),
        )
    elif space.display_mode == "SCENES":
        return (
            ("show_restrict_column_select", "SELECT"),
            ("show_restrict_column_hide", "HIDE"),
            ("show_restrict_column_viewport", "VIEWPORT"),
            ("show_restrict_column_render", "RENDER"),
        )
    return ()


def _visible_column_centers(context):
    columns = [
        item
        for item in _restriction_columns(context)
        if getattr(context.space_data, item[0], False)
    ]
    scale = context.preferences.system.ui_scale
    step = max(16, int(20 * scale))
    center = context.region.width - max(8, int(10 * scale))
    result = {}
    for prop, restriction in reversed(columns):
        result[prop] = (center, restriction)
        center -= step
    return result


def _custom_column_geometries(context):
    preferences = _preferences(context)
    if preferences is None:
        return {}
    scale = context.preferences.system.ui_scale
    step = max(16, int(20 * scale))
    size = max(8, int(OVERLAY_BOX_SIZE * scale))
    centers = [center for center, _restriction in _visible_column_centers(context).values()]
    if centers:
        center = min(centers) - step
    else:
        center = context.region.width - max(8, int(10 * scale))
    result = {}
    if preferences.show_batch_eye:
        left = int(center - size * 0.5)
        result["EYE"] = (left, left + size, size)
        center -= step
    if preferences.show_overlay:
        left = int(center - size * 0.5)
        result["CHECKBOX"] = (left, left + size, size)
    return result


def _restriction_at_x(context, x):
    """Resolve Blender's right-aligned restriction column under the pointer."""
    scale = context.preferences.system.ui_scale
    radius = max(7, int(9 * scale))
    for center, restriction in _visible_column_centers(context).values():
        if abs(x - center) <= radius:
            return restriction
    return None


def _apply_custom_drag_target(
    context,
    target,
    kind,
    value,
    use_selected_batch=False,
):
    if kind == "EYE":
        objects = target_objects(target)
        if not objects:
            return 0
        batch = _objects_for_batch(context, target) if use_selected_batch else objects
        if value:
            _remember_effective_selection(batch, context.view_layer)
        return apply_restriction(batch, "HIDE", value, context.view_layer)

    count = _set_effective_target_selected(target, value, context.view_layer)
    if value and isinstance(target, bpy.types.Object):
        context.view_layer.objects.active = target
    return count


def _line(shader, coords, color, width=1.0):
    gpu.state.line_width_set(width)
    shader.uniform_float("color", color)
    batch_for_shader(shader, "LINES", {"pos": coords}).draw(shader)


def _draw_box(shader, x, y, size, state, color):
    x2, y2 = x + size, y + size
    _line(shader, [(x, y), (x2, y), (x2, y), (x2, y2), (x2, y2), (x, y2), (x, y2), (x, y)], color)
    if state == STATE_ALL:
        _line(shader, [(x + 3, y + size * 0.52), (x + size * 0.43, y + 3), (x + size * 0.43, y + 3), (x2 - 2, y2 - 3)], color, 2.0)
    elif state == STATE_PARTIAL:
        _line(shader, [(x + 3, y + size * 0.5), (x2 - 3, y + size * 0.5)], color, 2.0)


def _draw_eye(shader, x, y, size, hidden, color):
    left = (x + 1, y + size * 0.5)
    right = (x + size - 1, y + size * 0.5)
    top = (x + size * 0.5, y + size - 2)
    bottom = (x + size * 0.5, y + 2)
    _line(shader, [left, top, top, right, right, bottom, bottom, left], color, 1.5)
    pupil = max(2, size * 0.14)
    cx, cy = x + size * 0.5, y + size * 0.5
    _line(shader, [(cx - pupil, cy), (cx + pupil, cy), (cx, cy - pupil), (cx, cy + pupil)], color, 2.0)
    if hidden:
        _line(shader, [(x + 1, y + 1), (x + size - 1, y + size - 1)], color, 2.0)


def _draw_overlay():
    context = bpy.context
    if not context.area or context.area.type != "OUTLINER" or not context.region:
        return
    preferences = _preferences(context)
    if not preferences or not (preferences.show_overlay or preferences.show_batch_eye):
        return

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    scale = context.preferences.system.ui_scale
    row_height = max(16, int(20 * scale))
    geometries = _custom_column_geometries(context)
    if not geometries:
        return
    size = next(iter(geometries.values()))[2]
    area_pointer = context.area.as_pointer()
    color = (0.82, 0.84, 0.88, 0.92)
    unknown = (0.45, 0.48, 0.52, 0.45)

    gpu.state.blend_set("ALPHA")
    slot = 0
    center_y = context.region.height - row_height * 0.5
    while center_y > -row_height:
        if (area_pointer, slot) in _UNSUPPORTED_ROWS:
            slot += 1
            center_y -= row_height
            continue
        identity = _ROW_CACHE.get((area_pointer, slot))
        state = None
        if identity:
            target = _target_from_name(*identity)
            state = _effective_target_state(target, context.view_layer)
            objects = target_objects(target)
        # Unresolved rows use a compact, faint placeholder in the far-left
        # gutter. The following fixed gap is untouched so Animation, Pose,
        # armature-data, and mode-specific icons remain readable and clickable.
        placeholder_size = size
        checkbox_geometry = geometries.get("CHECKBOX")
        if checkbox_geometry:
            _draw_box(
                shader,
                checkbox_geometry[0],
                center_y - placeholder_size * 0.5,
                placeholder_size,
                state,
                color if state else unknown,
            )
        eye_geometry = geometries.get("EYE")
        if eye_geometry and identity and objects:
            hidden = all(restriction_value(obj, "HIDE", context.view_layer) for obj in objects)
            _draw_eye(
                shader,
                eye_geometry[0],
                center_y - placeholder_size * 0.5,
                placeholder_size,
                hidden,
                color,
            )
        slot += 1
        center_y -= row_height
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


class FAIDLIXOUTLINER_OT_online_update(Operator):
    bl_idname = "faidlix_outliner.online_update"
    bl_label = "Online Update"
    bl_description = "檢查 GitHub 並安裝較新的 Faidlix_Outliner"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        global _PENDING_UPDATE
        context.preferences.system.use_online_access = True
        snapshot = _preference_snapshot(context)
        repo_index, repo = _ensure_github_repository(context)
        if repo is None:
            self.report({"ERROR"}, "無法建立 Faidlix Outliner GitHub 更新來源")
            return {"CANCELLED"}

        try:
            sync_result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
        except RuntimeError as exc:
            self.report({"ERROR"}, f"GitHub 同步失敗：{exc}")
            return {"CANCELLED"}
        if sync_result != {"FINISHED"}:
            self.report({"ERROR"}, "GitHub 同步未完成")
            return {"CANCELLED"}

        latest = _latest_version_from_index(_cached_repository_index(repo) or {})
        if not latest:
            self.report({"ERROR"}, "GitHub 更新索引找不到 Faidlix_Outliner")
            return {"CANCELLED"}
        if latest <= ADDON_VERSION:
            bpy.ops.wm.save_userpref()
            current = ".".join(str(part) for part in ADDON_VERSION)
            self.report({"INFO"}, f"Faidlix_Outliner {current} 已是最新版")
            return {"FINISHED"}

        version = ".".join(str(part) for part in latest)
        _PENDING_UPDATE = {
            "module_name": ADDON_ID,
            "repo_index": repo_index,
            "target_module_name": f"bl_ext.{repo.module}.{PACKAGE_ID}",
            "preferences": snapshot,
            "version": version,
        }
        if not bpy.app.timers.is_registered(_apply_pending_update):
            bpy.app.timers.register(_apply_pending_update, first_interval=0.1)
        self.report({"INFO"}, f"即將安全安裝 Faidlix_Outliner {version}")
        return {"FINISHED"}


class FAIDLIXOUTLINER_Preferences(AddonPreferences):
    bl_idname = ADDON_ID

    show_overlay: BoolProperty(name="顯示 Outliner 勾選覆蓋欄", default=True)
    show_batch_eye: BoolProperty(
        name="顯示 Faidlix 批次眼睛欄",
        description="在原生 Toggles 左側增加不影響 Blender 原生眼睛的批次顯示欄",
        default=True,
    )
    batch_selected_restrictions: BoolProperty(
        name="限制開關套用到所有已選物件",
        description="操作全選階層的限制開關時，同時處理其他已選物件",
        default=True,
    )
    checkbox_x: IntProperty(
        name="勾選框最前方位置",
        description="勾選框位於最左側，後方固定保留給 Outliner 特殊模式圖示",
        default=CHECKBOX_DEFAULT_X,
        min=0,
        max=60,
    )
    layout_version: IntProperty(default=0, options={"HIDDEN"})

    def draw(self, _context):
        layout = self.layout
        version = ".".join(str(part) for part in ADDON_VERSION)
        layout.label(text=f"Installed version: {version}")
        layout.label(text="Source: Faidlix GitHub")
        layout.separator()
        layout.prop(self, "show_overlay")
        layout.prop(self, "show_batch_eye")
        layout.prop(self, "batch_selected_restrictions")
        layout.label(text="核取框位於原生 Restriction Toggles 左側的獨立欄位。", icon="INFO")


class FAIDLIXOUTLINER_OT_row_toggle(Operator):
    bl_idname = "faidlix_outliner.row_toggle"
    bl_label = "階層勾選"
    bl_description = "選取或取消目前列以及所有下層物件"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def _target_at_event(self, context, event):
        key = _cache_key(context, event)
        target = _probe_row(context, event.mouse_region_y)
        if target is None and key[1] == 0 and context.space_data.display_mode == "VIEW_LAYER":
            target = context.scene
        if not target_objects(target) and not _target_bones(target):
            _UNSUPPORTED_ROWS.add(key)
            return None, key
        _UNSUPPORTED_ROWS.discard(key)
        _cache_target(context, event, target)
        return target, key

    def _apply_drag_target(self, context, target, use_selected_batch=False):
        return _apply_custom_drag_target(
            context,
            target,
            self._drag_kind,
            self._drag_value,
            use_selected_batch=use_selected_batch,
        )

    def invoke(self, context, event):
        preferences = _preferences(context)
        if not preferences or context.area.type != "OUTLINER":
            return {"PASS_THROUGH"}
        geometries = _custom_column_geometries(context)
        if not geometries:
            return {"PASS_THROUGH"}
        _invalidate_area_rows(context)
        _schedule_row_scan()
        checkbox_geometry = geometries.get("CHECKBOX")
        eye_geometry = geometries.get("EYE")
        checkbox_click = bool(
            checkbox_geometry
            and checkbox_geometry[0] <= event.mouse_region_x <= checkbox_geometry[1]
        )
        eye_click = bool(
            eye_geometry and eye_geometry[0] <= event.mouse_region_x <= eye_geometry[1]
        )
        if not checkbox_click and not eye_click:
            return {"PASS_THROUGH"}

        target, key = self._target_at_event(context, event)
        if target is None:
            _tag_outliners()
            return {"PASS_THROUGH"}
        objects = target_objects(target)
        state = _effective_target_state(target, context.view_layer)
        if eye_click:
            if not objects:
                return {"PASS_THROUGH"}
            self._drag_kind = "EYE"
            self._drag_value = not restriction_value(objects[0], "HIDE", context.view_layer)
            use_selected_batch = True
        else:
            self._drag_kind = "CHECKBOX"
            self._drag_value = False if event.ctrl else True if event.shift else state != STATE_ALL
            use_selected_batch = False

        self._drag_count = self._apply_drag_target(
            context,
            target,
            use_selected_batch=use_selected_batch,
        )
        self._visited_slots = {key}
        _tag_outliners()
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            if self._drag_kind == "EYE":
                verb = "隱藏" if self._drag_value else "顯示"
            else:
                verb = "選取" if self._drag_value else "取消"
            self.report({"INFO"}, f"已{verb} {self._drag_count} 個項目")
            _tag_outliners()
            return {"FINISHED"}
        if event.type == "ESC":
            _tag_outliners()
            return {"FINISHED"}
        if event.type not in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            return {"RUNNING_MODAL"}

        geometry = _custom_column_geometries(context).get(self._drag_kind)
        if geometry is None or not (geometry[0] <= event.mouse_region_x <= geometry[1]):
            return {"RUNNING_MODAL"}
        key = _cache_key(context, event)
        if key in self._visited_slots:
            return {"RUNNING_MODAL"}
        self._visited_slots.add(key)
        target, _key = self._target_at_event(context, event)
        if target is None:
            _tag_outliners()
            return {"RUNNING_MODAL"}
        self._drag_count += self._apply_drag_target(context, target)
        _tag_outliners()
        return {"RUNNING_MODAL"}


class FAIDLIXOUTLINER_OT_toggle_target(Operator):
    bl_idname = "faidlix_outliner.toggle_target"
    bl_label = "切換階層選取"
    bl_options = {"REGISTER", "UNDO"}

    target_kind: EnumProperty(
        items=(
            ("SCENE", "Scene Collection", ""),
            ("OBJECT", "物件", ""),
            ("COLLECTION", "Collection", ""),
            ("ARMATURE", "骨架", ""),
        )
    )
    target_name: StringProperty()
    action: EnumProperty(items=(("AUTO", "自動", ""), ("ADD", "加選", ""), ("SUBTRACT", "減選", "")), default="AUTO")

    def invoke(self, context, event):
        if event.ctrl:
            self.action = "SUBTRACT"
        elif event.shift:
            self.action = "ADD"
        return self.execute(context)

    def execute(self, context):
        target = _target_from_name(self.target_kind, self.target_name)
        objects = target_objects(target)
        if not objects and not _target_bones(target):
            self.report({"WARNING"}, "階層內沒有可操作的物件")
            return {"CANCELLED"}
        state = _effective_target_state(target, context.view_layer)
        select = self.action == "ADD" or (self.action == "AUTO" and state != STATE_ALL)
        if self.action == "SUBTRACT":
            select = False
        count = _set_effective_target_selected(target, select, context.view_layer)
        if select and isinstance(target, bpy.types.Object):
            context.view_layer.objects.active = target
        _tag_outliners()
        self.report({"INFO"}, f"{'選取' if select else '取消'} {count} 個物件")
        return {"FINISHED"}


class FAIDLIXOUTLINER_OT_toggle_restriction(Operator):
    bl_idname = "faidlix_outliner.toggle_restriction"
    bl_label = "切換階層限制"
    bl_options = {"REGISTER", "UNDO"}

    target_kind: EnumProperty(
        items=(
            ("SCENE", "Scene Collection", ""),
            ("OBJECT", "物件", ""),
            ("COLLECTION", "Collection", ""),
            ("ARMATURE", "骨架", ""),
        )
    )
    target_name: StringProperty()
    restriction: EnumProperty(items=(("HIDE", "眼睛", ""), ("VIEWPORT", "螢幕", ""), ("SELECT", "禁止選取", ""), ("RENDER", "渲染", "")))

    def execute(self, context):
        target = _target_from_name(self.target_kind, self.target_name)
        target_members = target_objects(target)
        objects = _objects_for_batch(context, target)
        if not target_members or not objects:
            self.report({"WARNING"}, "階層內沒有可操作的物件")
            return {"CANCELLED"}
        value = not restriction_value(target_members[0], self.restriction, context.view_layer)
        if value and self.restriction in {"HIDE", "VIEWPORT", "SELECT"}:
            _remember_effective_selection(objects, context.view_layer)
        count = apply_restriction(objects, self.restriction, value, context.view_layer)
        _tag_outliners()
        self.report({"INFO"}, f"已更新 {count} 個物件")
        return {"FINISHED"}


def _draw_target_menu(layout, target):
    identity = _target_identity(target)
    if not identity:
        return
    kind, name = identity
    state = _effective_target_state(target, bpy.context.view_layer)
    icon = "CHECKBOX_HLT" if state == STATE_ALL else "REMOVE" if state == STATE_PARTIAL else "CHECKBOX_DEHLT"
    operator = layout.operator(FAIDLIXOUTLINER_OT_toggle_target.bl_idname, text="階層勾選", icon=icon)
    operator.target_kind, operator.target_name = kind, name

    if isinstance(target, bpy.types.Armature):
        return
    row = layout.row(align=True)
    for restriction, icon_name in (("HIDE", "HIDE_OFF"), ("VIEWPORT", "RESTRICT_VIEW_OFF"), ("SELECT", "RESTRICT_SELECT_OFF"), ("RENDER", "RESTRICT_RENDER_OFF")):
        operator = row.operator(FAIDLIXOUTLINER_OT_toggle_restriction.bl_idname, text="", icon=icon_name)
        operator.target_kind, operator.target_name, operator.restriction = kind, name, restriction


def _draw_context_menu(self, context):
    targets = [item for item in getattr(context, "selected_ids", ()) if _target_identity(item)]
    if not targets and context.active_object:
        targets = [context.active_object]
    if not targets:
        return
    self.layout.separator()
    self.layout.label(text="Faidlix Outliner")
    _draw_target_menu(self.layout, targets[0])


def _draw_filter_faidlix_toggle(self, context):
    preferences = _preferences(context)
    if preferences is None or context.space_data.display_mode not in {"VIEW_LAYER", "SCENES"}:
        return
    self.layout.separator()
    row = self.layout.row(align=True)
    row.label(text="Faidlix Toggles")
    row.prop(
        preferences,
        "show_overlay",
        text="",
        icon="CHECKBOX_HLT" if preferences.show_overlay else "CHECKBOX_DEHLT",
        toggle=True,
    )
    row.prop(
        preferences,
        "show_batch_eye",
        text="",
        icon="HIDE_OFF",
        toggle=True,
    )


def _draw_outliner_header(self, context):
    """Blender 5.2 Outliner header with one update button after Search."""
    from bl_ui.space_outliner import OUTLINER_MT_editor_menus

    layout = self.layout
    space = context.space_data
    display_mode = space.display_mode
    scene = context.scene
    keying_set = scene.keying_sets.active

    layout.template_header()
    layout.prop(space, "display_mode", icon_only=True)

    if display_mode == "DATA_API":
        OUTLINER_MT_editor_menus.draw_collapsible(context, layout)
    if display_mode == "LIBRARY_OVERRIDES":
        layout.prop(space, "lib_override_view_mode", text="")

    layout.separator_spacer()
    filter_text_supported = not (
        display_mode == "LIBRARY_OVERRIDES"
        and space.lib_override_view_mode == "HIERARCHIES"
    )
    if filter_text_supported:
        row = layout.row(align=True)
        row.prop(space, "filter_text", icon="VIEWZOOM", text="")

    layout.separator_spacer()
    layout.operator(
        FAIDLIXOUTLINER_OT_online_update.bl_idname,
        text="Online Update",
        icon="FILE_REFRESH",
    )

    if display_mode == "SEQUENCE":
        row = layout.row(align=True)
        row.prop(space, "use_sync_select", icon="UV_SYNC_SELECT", text="")

    row = layout.row(align=True)
    if display_mode in {"SCENES", "VIEW_LAYER", "LIBRARY_OVERRIDES"}:
        row.popover(panel="OUTLINER_PT_filter", text="")

    if display_mode in {"LIBRARIES", "ORPHAN_DATA"}:
        row.prop(
            space,
            "use_filter_id_type",
            text="",
            icon="FILTER_FILLED" if space.use_filter_id_type else "FILTER",
        )
        sub = row.row(align=True)
        sub.active = space.use_filter_id_type
        sub.prop(space, "filter_id_type", text="", icon_only=True)

    if display_mode == "VIEW_LAYER":
        layout.operator("outliner.collection_new", text="", icon="COLLECTION_NEW").nested = True
    elif display_mode == "ORPHAN_DATA":
        layout.operator("outliner.orphans_purge", text="Purge")
    elif display_mode == "DATA_API":
        layout.separator()
        row = layout.row(align=True)
        row.operator("outliner.keyingset_add_selected", icon="ADD", text="")
        row.operator("outliner.keyingset_remove_selected", icon="REMOVE", text="")
        if keying_set:
            row = layout.row()
            row.prop_search(scene.keying_sets, "active", scene, "keying_sets", text="")
            row = layout.row(align=True)
            row.operator("anim.keyframe_insert", text="", icon="KEY_HLT")
            row.operator("anim.keyframe_delete", text="", icon="KEY_DEHLT")
        else:
            row = layout.row()
            row.label(text="No Keying Set Active")


def _install_header_button():
    global _ORIGINAL_HEADER_DRAW
    header = bpy.types.OUTLINER_HT_header
    if _ORIGINAL_HEADER_DRAW is None:
        _ORIGINAL_HEADER_DRAW = header.draw
    header.draw = _draw_outliner_header


def _remove_header_button():
    global _ORIGINAL_HEADER_DRAW
    if _ORIGINAL_HEADER_DRAW is not None:
        bpy.types.OUTLINER_HT_header.draw = _ORIGINAL_HEADER_DRAW
        _ORIGINAL_HEADER_DRAW = None


CLASSES = (
    FAIDLIXOUTLINER_OT_online_update,
    FAIDLIXOUTLINER_Preferences,
    FAIDLIXOUTLINER_OT_row_toggle,
    FAIDLIXOUTLINER_OT_toggle_target,
    FAIDLIXOUTLINER_OT_toggle_restriction,
) + UPDATE_ALL_CLASSES


def register():
    global _DRAW_HANDLE, _SKIPPED_REGISTRATION
    if not _disable_duplicate_addons():
        _SKIPPED_REGISTRATION = True
        return
    _SKIPPED_REGISTRATION = False
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _install_header_button()
    bpy.types.OUTLINER_MT_context_menu.append(_draw_context_menu)
    bpy.types.OUTLINER_PT_filter.append(_draw_filter_faidlix_toggle)
    _DRAW_HANDLE = bpy.types.SpaceOutliner.draw_handler_add(_draw_overlay, (), "WINDOW", "POST_PIXEL")

    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon
    if keyconfig:
        keymap = keyconfig.keymaps.new(name="Outliner", space_type="OUTLINER")
        item = keymap.keymap_items.new(FAIDLIXOUTLINER_OT_row_toggle.bl_idname, "LEFTMOUSE", "PRESS")
        _KEYMAPS.append((keymap, item))
    if not bpy.app.timers.is_registered(_ensure_tree_content_offset):
        bpy.app.timers.register(_ensure_tree_content_offset, first_interval=0.2)
    _schedule_row_scan(0.35)
    _tag_outliners()


def unregister():
    global _DRAW_HANDLE, _SKIPPED_REGISTRATION, _ROW_SCAN_PENDING
    if _SKIPPED_REGISTRATION:
        _SKIPPED_REGISTRATION = False
        return
    if bpy.app.timers.is_registered(_ensure_tree_content_offset):
        bpy.app.timers.unregister(_ensure_tree_content_offset)
    if bpy.app.timers.is_registered(_scan_visible_rows):
        bpy.app.timers.unregister(_scan_visible_rows)
    _ROW_SCAN_PENDING = False
    _restore_tree_content_offset()
    for keymap, item in _KEYMAPS:
        keymap.keymap_items.remove(item)
    _KEYMAPS.clear()
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceOutliner.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    _remove_header_button()
    bpy.types.OUTLINER_MT_context_menu.remove(_draw_context_menu)
    bpy.types.OUTLINER_PT_filter.remove(_draw_filter_faidlix_toggle)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _ROW_CACHE.clear()
    _UNSUPPORTED_ROWS.clear()


if __name__ == "__main__":
    register()

