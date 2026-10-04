"""Selection and restriction helpers shared by the UI and tests."""

from __future__ import annotations


STATE_NONE = "NONE"
STATE_PARTIAL = "PARTIAL"
STATE_ALL = "ALL"


def unique_objects(objects):
    """Return objects once while keeping Blender's input order."""
    result = []
    seen = set()
    for obj in objects:
        pointer = obj.as_pointer() if hasattr(obj, "as_pointer") else id(obj)
        if pointer in seen:
            continue
        seen.add(pointer)
        result.append(obj)
    return result


def object_hierarchy(root):
    """Return root and every descendant, depth first."""
    result = []
    stack = [root]
    while stack:
        obj = stack.pop()
        result.append(obj)
        stack.extend(reversed(list(obj.children)))
    return unique_objects(result)


def collection_objects(collection):
    """Return every object in a collection and its child collections."""
    # Collection.all_objects is recursive in Blender. Keep the fallback small
    # so the pure helper remains easy to test outside Blender.
    if hasattr(collection, "all_objects"):
        return unique_objects(collection.all_objects)

    result = list(collection.objects)
    for child in collection.children:
        result.extend(collection_objects(child))
    return unique_objects(result)


def target_objects(target):
    """Resolve supported Outliner IDs without importing bpy."""
    if target is None:
        return []
    if hasattr(target, "collection") and hasattr(target, "objects"):
        return unique_objects(target.objects)
    if hasattr(target, "children") and hasattr(target, "select_get"):
        return object_hierarchy(target)
    if hasattr(target, "objects") and hasattr(target, "children"):
        return collection_objects(target)
    return []


def selection_state(objects, view_layer=None, logical_names=None):
    objects = list(objects)
    if not objects:
        return STATE_NONE
    logical_names = logical_names or set()
    selected = 0
    for obj in objects:
        if obj.name in logical_names:
            selected += 1
            continue
        try:
            is_selected = obj.select_get(view_layer=view_layer)
        except (RuntimeError, TypeError):
            try:
                is_selected = obj.select_get()
            except RuntimeError:
                is_selected = False
        selected += bool(is_selected)
    if selected == 0:
        return STATE_NONE
    if selected == len(objects):
        return STATE_ALL
    return STATE_PARTIAL


def reveal_for_selection(obj, view_layer=None):
    """Make an object natively selectable without changing render visibility.

    Blender cannot keep eye-hidden, viewport-disabled, or selection-locked
    objects selected. Clearing those three states is therefore required when a
    hierarchy checkbox promises a real Blender selection.
    """
    if bool(getattr(obj, "hide_viewport", False)):
        obj.hide_viewport = False
    if bool(getattr(obj, "hide_select", False)):
        obj.hide_select = False
    try:
        eye_hidden = obj.hide_get(view_layer=view_layer)
    except (RuntimeError, TypeError):
        try:
            eye_hidden = obj.hide_get()
        except RuntimeError:
            eye_hidden = False
    if eye_hidden:
        try:
            obj.hide_set(False, view_layer=view_layer)
        except (RuntimeError, TypeError):
            obj.hide_set(False)


def set_selected(objects, selected, view_layer=None, reveal_hidden=True):
    changed = 0
    for obj in unique_objects(objects):
        if view_layer is not None and obj.name not in view_layer.objects:
            continue
        if selected and reveal_hidden:
            reveal_for_selection(obj, view_layer)
        try:
            obj.select_set(bool(selected), view_layer=view_layer)
        except (RuntimeError, TypeError):
            try:
                obj.select_set(bool(selected))
            except RuntimeError:
                continue
        changed += 1
    return changed


def apply_restriction(objects, restriction, value, view_layer=None):
    changed = 0
    for obj in unique_objects(objects):
        if restriction == "HIDE":
            try:
                obj.hide_set(bool(value), view_layer=view_layer)
            except (RuntimeError, TypeError):
                try:
                    obj.hide_set(bool(value))
                except RuntimeError:
                    continue
        elif restriction == "VIEWPORT":
            obj.hide_viewport = bool(value)
        elif restriction == "SELECT":
            obj.hide_select = bool(value)
        elif restriction == "RENDER":
            obj.hide_render = bool(value)
        else:
            raise ValueError(f"Unsupported restriction: {restriction}")
        changed += 1
    return changed


def restriction_value(obj, restriction, view_layer=None):
    if restriction == "HIDE":
        try:
            return bool(obj.hide_get(view_layer=view_layer))
        except TypeError:
            return bool(obj.hide_get())
    if restriction == "VIEWPORT":
        return bool(obj.hide_viewport)
    if restriction == "SELECT":
        return bool(obj.hide_select)
    if restriction == "RENDER":
        return bool(obj.hide_render)
    raise ValueError(f"Unsupported restriction: {restriction}")

