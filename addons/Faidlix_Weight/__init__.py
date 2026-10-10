bl_info = {
    "name": "Faidlix_Weight",
    "author": "Faidlix",
    "version": (1, 3, 1),
    "blender": (5, 2, 0),
    "location": "3D Viewport > Weight Paint > Right-click",
    "description": "Mirror or flip selected vertex weights across the local X axis",
    "category": "Rigging",
}

import json
import os
import re

import bpy
from bpy.props import BoolProperty
from bpy.types import AddonPreferences, Operator
from mathutils import Vector
from mathutils.kdtree import KDTree


_LONG_SIDE_RE = re.compile(r"left|right", re.IGNORECASE)
_SHORT_SIDE_RE = re.compile(r"(?P<separator>[._\-\s])(?P<side>[lr])(?=$|[._\-\s]|\d)", re.IGNORECASE)
_CONTEXT_MENU = None
ADDON_VERSION = (1, 3, 1)
PACKAGE_ID = "faidlix_weight"
GITHUB_REPOSITORY_URL = (
    "https://raw.githubusercontent.com/"
    "Faidlix/BlenderAddons/main/repository/index.json"
)


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
        name="Faidlix Blender Add-ons",
        remote_url=GITHUB_REPOSITORY_URL,
        use_sync_on_startup=True,
        type='REMOTE',
    )
    if result != {'FINISHED'}:
        return None, None
    return _github_repository(context)


def _version_tuple(version):
    try:
        return tuple(int(part) for part in version.split('.'))
    except (AttributeError, TypeError, ValueError):
        return ()


def _latest_version_from_index(index_data):
    versions = [
        _version_tuple(item.get('version'))
        for item in index_data.get('data', [])
        if item.get('id') == PACKAGE_ID
    ]
    return max((version for version in versions if version), default=())


def _cached_repository_index(repo):
    path = os.path.join(repo.directory, '.blender_ext', 'index.json')
    try:
        with open(path, 'r', encoding='utf8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _matching_case(text, template):
    if template.isupper():
        return text.upper()
    if template.islower():
        return text.lower()
    if template[:1].isupper() and template[1:].islower():
        return text.capitalize()
    # Unusual mixed case is still recognized. Preserve the leading case so the
    # result remains predictable even though Left and Right differ in length.
    return text.capitalize() if template[:1].isupper() else text.lower()


def mirror_group_name(name):
    """Return the left/right counterpart while preserving common case styles."""

    def replace_long(match):
        source = match.group(0)
        counterpart = "right" if source.lower() == "left" else "left"
        return _matching_case(counterpart, source)

    mirrored, count = _LONG_SIDE_RE.subn(replace_long, name)
    if count:
        return mirrored

    def replace_short(match):
        source = match.group("side")
        counterpart = "r" if source.lower() == "l" else "l"
        counterpart = counterpart.upper() if source.isupper() else counterpart
        return match.group("separator") + counterpart

    mirrored, _count = _SHORT_SIDE_RE.subn(replace_short, name)
    return mirrored


def _selected_vertex_indices(obj):
    if obj is None or obj.type != 'MESH':
        return []
    return [vertex.index for vertex in obj.data.vertices if vertex.select]


def _mirror_tolerance(mesh):
    return max(1.0e-6, _mesh_diagonal(mesh) * 1.0e-5)


def _mesh_diagonal(mesh):
    if not mesh.vertices:
        return 0.0
    minimum = Vector((float("inf"),) * 3)
    maximum = Vector((float("-inf"),) * 3)
    for vertex in mesh.vertices:
        co = vertex.co
        minimum.x = min(minimum.x, co.x)
        minimum.y = min(minimum.y, co.y)
        minimum.z = min(minimum.z, co.z)
        maximum.x = max(maximum.x, co.x)
        maximum.y = max(maximum.y, co.y)
        maximum.z = max(maximum.z, co.z)
    return (maximum - minimum).length


def _topology_features(mesh):
    neighbors = [set() for _vertex in mesh.vertices]
    edge_lengths = [[] for _vertex in mesh.vertices]
    edge_face_counts = {}
    face_counts = [0] * len(mesh.vertices)

    for edge in mesh.edges:
        first, second = edge.vertices
        neighbors[first].add(second)
        neighbors[second].add(first)
        length = (mesh.vertices[first].co - mesh.vertices[second].co).length
        edge_lengths[first].append(length)
        edge_lengths[second].append(length)
        edge_face_counts[tuple(sorted((first, second)))] = 0

    for polygon in mesh.polygons:
        for vertex_index in polygon.vertices:
            face_counts[vertex_index] += 1
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            edge_face_counts[key] = edge_face_counts.get(key, 0) + 1

    boundary = [False] * len(mesh.vertices)
    for edge in mesh.edges:
        key = tuple(sorted(edge.vertices))
        if edge_face_counts.get(key, 0) < 2:
            for vertex_index in edge.vertices:
                boundary[vertex_index] = True

    return {
        'neighbors': neighbors,
        'edge_lengths': edge_lengths,
        'face_counts': face_counts,
        'boundary': boundary,
    }


def _normalized_lengths(lengths):
    if not lengths:
        return []
    average = sum(lengths) / len(lengths)
    if average <= 1.0e-12:
        return [0.0] * len(lengths)
    return sorted(length / average for length in lengths)


def _neighborhood_shape_difference(source_lengths, target_lengths):
    source = _normalized_lengths(source_lengths)
    target = _normalized_lengths(target_lengths)
    shared = min(len(source), len(target))
    difference = sum(abs(source[index] - target[index]) for index in range(shared))
    difference += abs(len(source) - len(target))
    return difference / max(len(source), len(target), 1)


def _smart_mirror_candidates(mesh, tree, source_index, mirrored_co, tolerance, features, diagonal):
    source = mesh.vertices[source_index]
    source_lengths = features['edge_lengths'][source_index]
    local_scale = sum(source_lengths) / len(source_lengths) if source_lengths else diagonal * 0.01
    radius = max(tolerance * 4.0, local_scale * 2.0, diagonal * 0.002)
    candidates = []

    for _co, target_index, distance in tree.find_range(mirrored_co, radius):
        if target_index == source_index:
            continue
        target = mesh.vertices[target_index]
        if source.co.x * target.co.x >= 0.0:
            continue

        valence_difference = abs(
            len(features['neighbors'][source_index])
            - len(features['neighbors'][target_index])
        )
        face_difference = abs(
            features['face_counts'][source_index]
            - features['face_counts'][target_index]
        )
        boundary_difference = (
            features['boundary'][source_index]
            != features['boundary'][target_index]
        )
        shape_difference = _neighborhood_shape_difference(
            source_lengths,
            features['edge_lengths'][target_index],
        )
        spatial_score = distance / max(local_scale, tolerance)
        score = (
            spatial_score
            + valence_difference * 0.65
            + face_difference * 0.35
            + float(boundary_difference) * 0.75
            + shape_difference * 0.50
        )
        candidates.append((score, distance, target_index))

    candidates.sort()
    return [candidate for candidate in candidates if candidate[0] <= 3.0]


def _assign_unique_targets(candidate_map, reserved_targets=()):
    """Return a maximum one-to-one assignment using ranked smart candidates.

    An augmenting path lets a source that loses a contested target move to its
    next-best candidate instead of cancelling the whole operation. Sources
    with fewer choices are attempted first so constrained points keep their
    only viable match.
    """
    reserved = set(reserved_targets)
    source_to_target = {}
    target_to_source = {}

    def assign(start_source):
        source_queue = [start_source]
        queue_index = 0
        visited_sources = {start_source}
        visited_targets = set()
        parent_source_by_target = {}

        while queue_index < len(source_queue):
            source_index = source_queue[queue_index]
            queue_index += 1
            for _score, _distance, target_index in candidate_map.get(source_index, ()):
                if target_index in reserved or target_index in visited_targets:
                    continue
                visited_targets.add(target_index)
                parent_source_by_target[target_index] = source_index
                current_source = target_to_source.get(target_index)
                if current_source is None:
                    free_target = target_index
                    while True:
                        assigned_source = parent_source_by_target[free_target]
                        previous_target = source_to_target.get(assigned_source)
                        target_to_source[free_target] = assigned_source
                        source_to_target[assigned_source] = free_target
                        if previous_target is None:
                            return True
                        free_target = previous_target
                if current_source not in visited_sources:
                    visited_sources.add(current_source)
                    source_queue.append(current_source)
        return False

    def source_priority(source_index):
        candidates = candidate_map.get(source_index, ())
        best_score = candidates[0][0] if candidates else float('inf')
        return len(candidates), best_score, source_index

    for source_index in sorted(candidate_map, key=source_priority):
        assign(source_index)
    return source_to_target


def _mirror_map(obj, indices, smart=True):
    mesh = obj.data
    tolerance = _mirror_tolerance(mesh)
    diagonal = _mesh_diagonal(mesh)
    tree = KDTree(len(mesh.vertices))
    for vertex in mesh.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()

    mapping = {}
    missing = []
    center = []
    smart_matches = []
    features = _topology_features(mesh) if smart else None
    exact_candidates = []
    unresolved = []
    for index in sorted(indices):
        vertex = mesh.vertices[index]
        if abs(vertex.co.x) <= tolerance:
            center.append(index)
            continue
        mirrored_co = Vector((-vertex.co.x, vertex.co.y, vertex.co.z))
        _co, target_index, distance = tree.find(mirrored_co)
        if target_index is not None and distance <= tolerance and target_index != index:
            exact_candidates.append((distance, index, target_index))
        else:
            unresolved.append((index, mirrored_co))

    reserved_targets = set()
    for _distance, index, target_index in sorted(exact_candidates):
        if target_index in reserved_targets:
            mirrored_co = Vector((-mesh.vertices[index].co.x,
                                  mesh.vertices[index].co.y,
                                  mesh.vertices[index].co.z))
            unresolved.append((index, mirrored_co))
            continue
        mapping[index] = target_index
        reserved_targets.add(target_index)

    if smart:
        candidate_map = {
            index: _smart_mirror_candidates(
                mesh,
                tree,
                index,
                mirrored_co,
                tolerance,
                features,
                diagonal,
            )
            for index, mirrored_co in unresolved
        }
        smart_mapping = _assign_unique_targets(candidate_map, reserved_targets)
        mapping.update(smart_mapping)
        smart_matches.extend(sorted(smart_mapping))
        missing.extend(
            index for index, _mirrored_co in unresolved
            if index not in smart_mapping
        )
    else:
        missing.extend(index for index, _mirrored_co in unresolved)
    return mapping, missing, center, tolerance, smart_matches


def _selection_has_bilateral_pair(obj):
    selected = _selected_vertex_indices(obj)
    if not selected:
        return False
    scene = getattr(bpy.context, 'scene', None)
    smart = bool(getattr(scene, 'faidlix_weight_smart_match', True))
    mapping, _missing, _center, _tolerance, _smart = _mirror_map(obj, selected, smart)
    selected_set = set(selected)
    return any(target in selected_set for target in mapping.values())


def _weights_by_name(obj, vertex_index):
    result = {}
    vertex = obj.data.vertices[vertex_index]
    for membership in vertex.groups:
        group = obj.vertex_groups[membership.group]
        result[group.name] = membership.weight
    return result


def _mirrored_weights(weights):
    result = {}
    for name, weight in weights.items():
        target_name = mirror_group_name(name)
        # Blender group names are unique, but two unusual source names can map
        # to one counterpart. Keep the strongest influence deterministically.
        result[target_name] = max(weight, result.get(target_name, 0.0))
    return result


def _build_operations(selected, mapping, flip):
    operations = {}
    conflicts = {}
    for source_index in selected:
        mirror_index = mapping.get(source_index)
        if mirror_index is None:
            continue
        donor, recipient = (
            (mirror_index, source_index) if flip else (source_index, mirror_index)
        )
        previous = operations.get(recipient)
        if previous is not None and previous != donor:
            conflicts.setdefault(recipient, {previous}).add(donor)
        operations[recipient] = donor
    return operations, conflicts


def _locked_weight_conflicts(obj, desired_by_vertex):
    locked = {group.name for group in obj.vertex_groups if group.lock_weight}
    if not locked:
        return []
    conflicts = []
    for vertex_index, desired in desired_by_vertex.items():
        current = _weights_by_name(obj, vertex_index)
        for name in locked:
            if abs(current.get(name, 0.0) - desired.get(name, 0.0)) > 1.0e-8:
                conflicts.append((vertex_index, name))
    return conflicts


def _apply_weights(obj, desired_by_vertex):
    required_names = {
        name for desired in desired_by_vertex.values() for name in desired
    }
    for name in sorted(required_names, key=str.casefold):
        if obj.vertex_groups.get(name) is None:
            obj.vertex_groups.new(name=name)

    for vertex_index, desired in desired_by_vertex.items():
        current_names = tuple(_weights_by_name(obj, vertex_index))
        for name in current_names:
            group = obj.vertex_groups.get(name)
            if group is not None and not group.lock_weight:
                group.remove([vertex_index])
        for name, weight in desired.items():
            group = obj.vertex_groups[name]
            if not group.lock_weight:
                group.add([vertex_index], weight, 'REPLACE')


class FAIDLIXWEIGHT_OT_toggle_flip(Operator):
    bl_idname = "faidlix_weight.toggle_flip"
    bl_label = "Flip"
    bl_description = "Reverse the copy direction: copy the opposite side onto the selected side"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            context.mode == 'PAINT_WEIGHT'
            and obj is not None
            and obj.type == 'MESH'
            and obj.data.use_paint_mask_vertex
        )

    def execute(self, context):
        obj = context.active_object
        if _selection_has_bilateral_pair(obj):
            self.report({'INFO'}, "Flip is locked because both sides are selected")
            return {'CANCELLED'}
        context.scene.faidlix_weight_flip = not context.scene.faidlix_weight_flip
        return {'FINISHED'}


class FAIDLIXWEIGHT_OT_online_update(Operator):
    bl_idname = "faidlix_weight.online_update"
    bl_label = "Online Update"
    bl_description = "Check GitHub and download a newer Faidlix_Weight package"
    bl_options = {'INTERNAL'}

    force: BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        context.preferences.system.use_online_access = True
        repo_index, repo = _ensure_github_repository(context)
        if repo is None:
            self.report({'ERROR'}, "Could not create the Faidlix Blender Add-ons repository")
            return {'CANCELLED'}

        try:
            sync_result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
        except RuntimeError as exc:
            self.report({'ERROR'}, f"GitHub sync failed: {exc}")
            return {'CANCELLED'}
        if sync_result != {'FINISHED'}:
            self.report({'ERROR'}, "GitHub sync did not finish")
            return {'CANCELLED'}

        index_data = _cached_repository_index(repo)
        latest = _latest_version_from_index(index_data or {})
        if not latest:
            self.report({'ERROR'}, "Faidlix_Weight was not found in the GitHub index")
            return {'CANCELLED'}

        if latest <= ADDON_VERSION and not self.force:
            bpy.ops.wm.save_userpref()
            current = '.'.join(str(part) for part in ADDON_VERSION)
            self.report({'INFO'}, f"Faidlix_Weight {current} is already up to date")
            return {'FINISHED'}

        version = '.'.join(str(part) for part in latest)

        def install_after_operator_returns():
            try:
                install_result = bpy.ops.extensions.package_install(
                    repo_index=repo_index,
                    pkg_id=PACKAGE_ID,
                    enable_on_install=True,
                )
                if install_result == {'FINISHED'}:
                    bpy.ops.wm.save_userpref()
                    print(
                        f"Faidlix_Weight {version} downloaded from "
                        "Faidlix Blender Add-ons"
                    )
                else:
                    print("Faidlix_Weight online update did not finish")
            except Exception as exc:
                print(f"Faidlix_Weight online update failed: {exc}")
            return None

        bpy.app.timers.register(
            install_after_operator_returns,
            first_interval=0.1,
        )
        self.report({'INFO'}, f"Preparing Faidlix_Weight {version} update")
        return {'FINISHED'}


class FAIDLIXWEIGHT_Preferences(AddonPreferences):
    bl_idname = __package__

    def draw(self, _context):
        layout = self.layout
        version = '.'.join(str(part) for part in ADDON_VERSION)
        layout.label(text=f"Installed version: {version}")
        layout.label(text="Source: Faidlix Blender Add-ons")
        layout.operator(
            FAIDLIXWEIGHT_OT_online_update.bl_idname,
            text="Check and Install Online Update",
            icon='FILE_REFRESH',
        )


class FAIDLIXWEIGHT_OT_toggle_smart_match(Operator):
    bl_idname = "faidlix_weight.toggle_smart_match"
    bl_label = "Smart Match"
    bl_description = "Use nearby position and topology when no exact mirrored vertex exists"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            context.mode == 'PAINT_WEIGHT'
            and obj is not None
            and obj.type == 'MESH'
            and obj.data.use_paint_mask_vertex
        )

    def execute(self, context):
        context.scene.faidlix_weight_smart_match = (
            not context.scene.faidlix_weight_smart_match
        )
        return {'FINISHED'}


class FAIDLIXWEIGHT_OT_mirror_selected(Operator):
    bl_idname = "faidlix_weight.mirror_selected"
    bl_label = "MirrorSelectWeight"
    bl_description = "Mirror selected vertex weights across local X with left/right group names"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            context.mode == 'PAINT_WEIGHT'
            and obj is not None
            and obj.type == 'MESH'
            and obj.data.use_paint_mask_vertex
            and bool(_selected_vertex_indices(obj))
        )

    def execute(self, context):
        obj = context.active_object
        selected = _selected_vertex_indices(obj)
        mapping, missing, center, tolerance, smart_matches = _mirror_map(
            obj,
            selected,
            context.scene.faidlix_weight_smart_match,
        )
        bilateral = any(target in set(selected) for target in mapping.values())
        flip = bilateral or context.scene.faidlix_weight_flip
        operations, conflicts = _build_operations(selected, mapping, flip)

        if conflicts:
            self.report(
                {'ERROR'},
                f"Cancelled: {len(conflicts)} mirror targets have multiple sources",
            )
            return {'CANCELLED'}
        if not operations:
            self.report(
                {'WARNING'},
                f"No mirror targets found (tolerance {tolerance:.6g})",
            )
            return {'CANCELLED'}

        # Snapshot every donor before changing any recipient. This is required
        # for a true two-sided swap instead of copying the first result twice.
        donor_snapshots = {
            donor: _weights_by_name(obj, donor)
            for donor in set(operations.values())
        }
        desired_by_vertex = {
            recipient: _mirrored_weights(donor_snapshots[donor])
            for recipient, donor in operations.items()
        }

        locked_conflicts = _locked_weight_conflicts(obj, desired_by_vertex)
        if locked_conflicts:
            groups = sorted({name for _vertex, name in locked_conflicts}, key=str.casefold)
            self.report(
                {'ERROR'},
                "Cancelled: locked vertex groups would change: " + ", ".join(groups[:5]),
            )
            return {'CANCELLED'}

        _apply_weights(obj, desired_by_vertex)
        obj.data.update()

        action = "swapped" if bilateral else ("flipped" if flip else "mirrored")
        notes = []
        if missing:
            notes.append(f"{len(missing)} missing")
        if center:
            notes.append(f"{len(center)} center skipped")
        if smart_matches:
            notes.append(f"{len(smart_matches)} smart matched")
        suffix = f"; {', '.join(notes)}" if notes else ""
        self.report({'INFO'}, f"{len(operations)} vertices {action}{suffix}")
        return {'FINISHED'}


def _draw_weight_context_menu(self, context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return

    layout = self.layout
    layout.separator()
    layout.label(text="Faidlix Weight", icon='MOD_VERTEX_WEIGHT')

    bilateral = _selection_has_bilateral_pair(obj)
    flip = bilateral or context.scene.faidlix_weight_flip
    row = layout.row(align=True)
    row.enabled = not bilateral
    row.operator(
        FAIDLIXWEIGHT_OT_toggle_flip.bl_idname,
        text="Flip",
        icon='CHECKBOX_HLT' if flip else 'CHECKBOX_DEHLT',
        depress=flip,
    )
    if bilateral:
        row.label(text="Both sides selected (locked)")

    smart = context.scene.faidlix_weight_smart_match
    row = layout.row(align=True)
    row.operator(
        FAIDLIXWEIGHT_OT_toggle_smart_match.bl_idname,
        text="Smart Match",
        icon='CHECKBOX_HLT' if smart else 'CHECKBOX_DEHLT',
        depress=smart,
    )

    layout.operator(
        FAIDLIXWEIGHT_OT_mirror_selected.bl_idname,
        text="MirrorSelectWeight",
        icon='MOD_MIRROR',
    )
    layout.separator()
    layout.operator(
        FAIDLIXWEIGHT_OT_online_update.bl_idname,
        text="Online Update",
        icon='FILE_REFRESH',
    )


CLASSES = (
    FAIDLIXWEIGHT_OT_online_update,
    FAIDLIXWEIGHT_Preferences,
    FAIDLIXWEIGHT_OT_toggle_flip,
    FAIDLIXWEIGHT_OT_toggle_smart_match,
    FAIDLIXWEIGHT_OT_mirror_selected,
)


def _find_context_menu():
    return getattr(
        bpy.types,
        "VIEW3D_PT_paint_weight_context_menu",
        getattr(bpy.types, "VIEW3D_MT_paint_weight_context_menu", None),
    )


def register():
    global _CONTEXT_MENU
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.faidlix_weight_flip = BoolProperty(
        name="Flip",
        description="Copy the opposite side onto selected vertices",
        default=False,
    )
    bpy.types.Scene.faidlix_weight_smart_match = BoolProperty(
        name="Smart Match",
        description="Use topology and nearby relative position as a fallback",
        default=True,
    )
    _CONTEXT_MENU = _find_context_menu()
    if _CONTEXT_MENU is None:
        del bpy.types.Scene.faidlix_weight_smart_match
        del bpy.types.Scene.faidlix_weight_flip
        for cls in reversed(CLASSES):
            bpy.utils.unregister_class(cls)
        raise RuntimeError("Weight Paint context menu is unavailable")
    _CONTEXT_MENU.append(_draw_weight_context_menu)


def unregister():
    global _CONTEXT_MENU
    if _CONTEXT_MENU is not None:
        try:
            _CONTEXT_MENU.remove(_draw_weight_context_menu)
        except (ValueError, RuntimeError):
            pass
        _CONTEXT_MENU = None
    if hasattr(bpy.types.Scene, "faidlix_weight_flip"):
        del bpy.types.Scene.faidlix_weight_flip
    if hasattr(bpy.types.Scene, "faidlix_weight_smart_match"):
        del bpy.types.Scene.faidlix_weight_smart_match
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
