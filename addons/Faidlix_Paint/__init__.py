bl_info = {
    "name": "Faidlix Paint",
    "author": "Faidlix",
    "version": (0, 4, 8),
    "blender": (4, 5, 0),
    "location": "Image Editor Paint / 3D View Texture Paint toolbar",
    "description": "Fill an entire image, paint mask, or selected UV island",
    "category": "Paint",
}

from array import array
import colorsys
import json
import os
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, FloatProperty, StringProperty, IntProperty
from bpy.types import AddonPreferences, Operator, PropertyGroup, WorkSpaceTool


ADDON_VERSION = (0, 4, 8)
PACKAGE_ID = "faidlix_paint"
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
        name="Faidlix Paint GitHub", remote_url=GITHUB_REPOSITORY_URL,
        use_sync_on_startup=True, type='REMOTE')
    if result != {'FINISHED'}:
        return None, None
    return _github_repository(context)


def _version_tuple(version):
    try:
        return tuple(int(part) for part in version.split('.'))
    except (AttributeError, TypeError, ValueError):
        return ()


def _latest_version_from_index(index_data):
    versions = [_version_tuple(item.get('version')) for item in index_data.get('data', [])
                if item.get('id') == PACKAGE_ID]
    return max((version for version in versions if version), default=())


def _cached_repository_index(repo):
    path = os.path.join(repo.directory, '.blender_ext', 'index.json')
    try:
        with open(path, 'r', encoding='utf8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _active_image(context):
    space = getattr(context, "space_data", None)
    if space and space.type == 'IMAGE_EDITOR' and getattr(space, "image", None):
        return space.image

    obj = context.active_object
    if obj and obj.type == 'MESH':
        material = obj.active_material
        if material and material.use_nodes and material.node_tree:
            node = material.node_tree.nodes.get(material.node_tree.nodes.active.name) \
                if material.node_tree.nodes.active else None
            if node and node.type == 'TEX_IMAGE' and node.image:
                return node.image
            for node in material.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    return node.image
    return None


def _uv_data(mesh):
    layer = mesh.uv_layers.active
    return layer.data if layer else None


def _selected_polygons(obj, mode):
    mesh = obj.data
    uv_data = _uv_data(mesh)
    if uv_data is None:
        return []

    selected = [p for p in mesh.polygons if p.select and not p.hide]
    if mode == 'LAYER':
        if mesh.use_paint_mask:
            return selected
        return []

    # In Edit/UV workflows, UV-loop selection is authoritative. Texture Paint
    # face masking instead uses selected mesh faces.
    uv_selected = []
    for poly in mesh.polygons:
        if poly.hide:
            continue
        loops = [uv_data[i] for i in poly.loop_indices]
        if loops and all(getattr(loop, "select", False) for loop in loops):
            uv_selected.append(poly)
    return uv_selected or selected


def _uv_edge_key(a, b):
    a = (round(a[0], 6), round(a[1], 6))
    b = (round(b[0], 6), round(b[1], 6))
    return tuple(sorted((a, b)))


def _uv_island(mesh, seed_index):
    """Return the complete UV-contiguous island containing seed_index."""
    uv_data = _uv_data(mesh)
    if uv_data is None or seed_index < 0 or seed_index >= len(mesh.polygons):
        return []
    edge_to_polys = {}
    poly_edges = {}
    for poly in mesh.polygons:
        points = _polygon_uvs(poly, uv_data)
        edges = [_uv_edge_key(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
        poly_edges[poly.index] = edges
        for edge in edges:
            edge_to_polys.setdefault(edge, []).append(poly.index)

    found = {seed_index}
    pending = [seed_index]
    while pending:
        current = pending.pop()
        for edge in poly_edges[current]:
            for neighbor in edge_to_polys[edge]:
                if neighbor not in found:
                    found.add(neighbor)
                    pending.append(neighbor)
    return [mesh.polygons[index] for index in sorted(found)]


def _point_in_polygon(point, points):
    x, y = point
    inside = False
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        if ((yi > y) != (yj > y)) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _seed_from_uv(mesh, uv):
    uv_data = _uv_data(mesh)
    if uv_data is None:
        return -1
    for poly in mesh.polygons:
        if _point_in_polygon(uv, _polygon_uvs(poly, uv_data)):
            return poly.index
    return -1


def _seed_from_view3d(context, x, y):
    from bpy_extras import view3d_utils
    region = context.region
    rv3d = context.region_data
    obj = context.active_object
    if not region or not rv3d or not obj or obj.type != 'MESH':
        return -1
    coord = (x, y)
    origin_world = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction_world = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    matrix_inv = obj.matrix_world.inverted()
    origin_local = matrix_inv @ origin_world
    direction_local = (matrix_inv.to_3x3() @ direction_world).normalized()
    hit, _location, _normal, face_index = obj.ray_cast(origin_local, direction_local)
    return face_index if hit else -1


def _uv_from_click(context, x, y, image):
    if context.area.type == 'IMAGE_EDITOR':
        vx, vy = context.region.view2d.region_to_view(x, y)
        width, height = image.size[:]
        return (vx / width, vy / height) if abs(vx) > 2.0 or abs(vy) > 2.0 else (vx, vy)

    from bpy_extras import view3d_utils
    from mathutils.geometry import barycentric_transform
    obj = context.active_object
    region, rv3d = context.region, context.region_data
    if not obj or obj.type != 'MESH' or not region or not rv3d:
        return None
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
    inv = eval_obj.matrix_world.inverted()
    hit, location, _normal, face_index = eval_obj.ray_cast(
        inv @ origin, (inv.to_3x3() @ direction).normalized())
    if not hit:
        return None
    mesh = eval_obj.data
    uv_data = _uv_data(mesh)
    if uv_data is None or face_index < 0 or face_index >= len(mesh.polygons):
        return None
    poly = mesh.polygons[face_index]
    loops = list(poly.loop_indices)
    if len(loops) < 3 or any(index < 0 or index >= len(uv_data) for index in loops):
        return None
    for i in range(1, len(loops) - 1):
        ids = (loops[0], loops[i], loops[i + 1])
        verts = [mesh.vertices[mesh.loops[index].vertex_index].co for index in ids]
        uv3 = [uv_data[index].uv.to_3d() for index in ids]
        result = barycentric_transform(location, *verts, *uv3)
        # Accept the triangle whose barycentric reconstruction lies inside.
        from mathutils.geometry import closest_point_on_tri
        if (closest_point_on_tri(location, *verts) - location).length < 1.0e-5:
            return (result.x, result.y)
    return None


def _mask_image(source, create=False):
    name = source.get("faidlix_paint_mask", "")
    mask = bpy.data.images.get(name) if name else None
    if mask and tuple(mask.size[:]) != tuple(source.size[:]):
        mask.scale(source.size[0], source.size[1])
    if mask is None and create:
        name = f"{source.name}.MaskMap"
        mask = bpy.data.images.get(name) or bpy.data.images.new(
            name, width=source.size[0], height=source.size[1], alpha=True)
        pixels = array('f', [0.0]) * (source.size[0] * source.size[1] * 4)
        for index in range(source.size[0] * source.size[1]):
            pixels[index * 4 + 3] = 1.0
        mask.pixels.foreach_set(pixels)
        mask["faidlix_mask_base_ready"] = True
        source["faidlix_paint_mask"] = mask.name
    return mask


_mask_overlay_revision = 0
_mask_overlay_cache = {"key": None, "positions": []}
_mask_image_overlay_cache = {"key": None, "runs": []}


def _tag_mask_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'IMAGE_EDITOR'}:
                area.tag_redraw()


def _ensure_mask_base(mask, pixels):
    if mask.get("faidlix_mask_base_ready", False):
        return
    for index in range(len(pixels) // 4):
        pixels[index * 4] = pixels[index * 4 + 1]
    mask["faidlix_mask_base_ready"] = True


def _box_blur(values, width, height, radius):
    if radius <= 0:
        return values
    horizontal = array('f', [0.0]) * (width * height)
    for y in range(height):
        row = y * width
        total = 0.0
        right = min(width - 1, radius)
        for x in range(right + 1):
            total += values[row + x]
        left = 0
        for x in range(width):
            horizontal[row + x] = total / (right - left + 1)
            next_right = min(width - 1, x + radius + 1)
            next_left = max(0, x - radius + 1)
            if next_right > right:
                total += values[row + next_right]
                right = next_right
            if next_left > left:
                total -= values[row + left]
                left = next_left
    vertical = array('f', [0.0]) * (width * height)
    for x in range(width):
        total = 0.0
        bottom = 0
        top = min(height - 1, radius)
        for y in range(top + 1):
            total += horizontal[y * width + x]
        for y in range(height):
            vertical[y * width + x] = total / (top - bottom + 1)
            next_top = min(height - 1, y + radius + 1)
            next_bottom = max(0, y - radius + 1)
            if next_top > top:
                total += horizontal[next_top * width + x]
                top = next_top
            if next_bottom > bottom:
                total -= horizontal[bottom * width + x]
                bottom = next_bottom
    return vertical


def _apply_mask_feather(pixels, width, height, radius):
    base = array('f', (pixels[index * 4] for index in range(width * height)))
    softened = _box_blur(base, width, height, int(radius))
    for index, amount in enumerate(softened):
        offset = index * 4
        pixels[offset + 1] = amount
        pixels[offset + 2] = 0.0
        pixels[offset + 3] = 1.0


def _mask_feather_radius():
    settings = getattr(bpy.context.scene, "faidlix_paint", None)
    return int(getattr(settings, "mask_feather", 0)) if settings else 0


def _write_mask(source, indices, value=1.0, strength=1.0):
    global _mask_overlay_revision
    mask = _mask_image(source, create=True)
    pixels = array('f', [0.0]) * (source.size[0] * source.size[1] * 4)
    mask.pixels.foreach_get(pixels)
    _ensure_mask_base(mask, pixels)
    strength = max(0.0, min(1.0, strength))
    for index in indices:
        offset = index * 4
        current = pixels[offset]
        amount = current * (1.0 - strength) + value * strength
        # R stores the stable hard mask; G stores the feathered result used by
        # Fill and both green overlays.
        pixels[offset] = amount
    _apply_mask_feather(pixels, source.size[0], source.size[1], _mask_feather_radius())
    mask.pixels.foreach_set(pixels)
    mask.update()
    _mask_overlay_revision += 1
    _tag_mask_redraw()
    return len(indices)


def _write_all_mask(source, value):
    return _write_mask(source, range(source.size[0] * source.size[1]), value)


def _mask_protected_indices(mask, pixel_count):
    pixels = array('f', [0.0]) * (pixel_count * 4)
    mask.pixels.foreach_get(pixels)
    return {index for index in range(pixel_count)
            if pixels[index * 4 + 1] > 1.0e-5}


def _mask_protection_values(mask, pixel_count):
    pixels = array('f', [0.0]) * (pixel_count * 4)
    mask.pixels.foreach_get(pixels)
    return array('f', (pixels[index * 4 + 1] for index in range(pixel_count)))


def _rebuild_mask_feather(source, radius):
    global _mask_overlay_revision
    mask = _mask_image(source, create=False)
    if mask is None:
        return False
    width, height = source.size[:]
    pixels = array('f', [0.0]) * (width * height * 4)
    mask.pixels.foreach_get(pixels)
    _ensure_mask_base(mask, pixels)
    _apply_mask_feather(pixels, width, height, radius)
    mask.pixels.foreach_set(pixels)
    mask.update()
    _mask_overlay_revision += 1
    _tag_mask_redraw()
    return True


def _update_mask_feather(settings, context):
    if context is None:
        return
    source = _active_image(context)
    if source is not None:
        _rebuild_mask_feather(source, settings.mask_feather)


def _mask_to_bw_image(source):
    mask = _mask_image(source, create=False)
    if mask is None:
        return None
    width, height = source.size[:]
    mask_pixels = array('f', [0.0]) * (width * height * 4)
    mask.pixels.foreach_get(mask_pixels)
    output_name = f"{source.name}.MaskBW"
    output = bpy.data.images.get(output_name) or bpy.data.images.new(
        output_name, width=width, height=height, alpha=True)
    if tuple(output.size[:]) != (width, height):
        output.scale(width, height)
    output_pixels = array('f', [0.0]) * (width * height * 4)
    for index in range(width * height):
        amount = mask_pixels[index * 4 + 1]
        output_pixels[index * 4:index * 4 + 4] = array('f', (amount, amount, amount, 1.0))
    output.pixels.foreach_set(output_pixels)
    output.update()
    output["faidlix_mask_source"] = source.name
    return output


def _finish_native_mask_stroke(state):
    global _mask_overlay_revision
    paint = state["paint"]
    brush = state["brush"]
    color_owner = state["color_owner"]
    try:
        paint.mode = state["mode"]
        paint.canvas = state["canvas"]
        paint.use_occlude = state["use_occlude"]
        paint.use_backface_culling = state["use_backface_culling"]
        color_owner.color = state["color"]
        brush.hardness = state["hardness"]
    except (ReferenceError, RuntimeError):
        pass
    mask = state["mask"]
    if mask and mask.name in bpy.data.images:
        mask["faidlix_mask_base_ready"] = True
        mask.update()
    _mask_overlay_revision += 1
    _tag_mask_redraw()
    return None


def _invoke_native_mask_brush(context, source, erase):
    mask = _mask_image(source, create=True)
    paint = context.tool_settings.image_paint
    brush = paint.brush
    if brush is None:
        return None, "目前沒有作用中的 Texture Paint 筆刷"
    ups = paint.unified_paint_settings
    color_owner = ups if ups.use_unified_color else brush
    size_owner = ups if ups.use_unified_size else brush
    radius = max(1, int(size_owner.size))
    feather = context.scene.faidlix_paint.mask_feather
    state = {
        "paint": paint,
        "brush": brush,
        "color_owner": color_owner,
        "mode": paint.mode,
        "canvas": paint.canvas,
        "use_occlude": paint.use_occlude,
        "use_backface_culling": paint.use_backface_culling,
        "color": tuple(color_owner.color),
        "hardness": brush.hardness,
        "mask": mask,
    }
    include_backfaces = context.scene.faidlix_paint.mask_include_backfaces
    paint.mode = 'IMAGE'
    paint.canvas = mask
    paint.use_occlude = not include_backfaces
    paint.use_backface_culling = not include_backfaces
    # UI black means add protection and UI white means erase protection. The
    # native canvas stores protection as grayscale, so its paint color is the
    # inverse of the user-facing control.
    color_owner.color = (0.0, 0.0, 0.0) if erase else (1.0, 1.0, 1.0)
    brush.hardness = max(0.0, min(1.0, 1.0 - feather / radius))
    try:
        result = bpy.ops.paint.image_paint('INVOKE_DEFAULT')
    except RuntimeError as exc:
        _finish_native_mask_stroke(state)
        return None, str(exc)
    return (state, None) if 'RUNNING_MODAL' in result else (state, None)


def _mask_brush_state(context):
    from bl_ui.properties_paint_common import UnifiedPaintPanel
    paint = UnifiedPaintPanel.paint_settings(context)
    brush = paint.brush if paint else None
    if brush is None:
        return 32, 1.0, False
    ups = paint.unified_paint_settings
    size_owner = ups if ups.use_unified_size else brush
    strength_owner = ups if ups.use_unified_strength else brush
    color_owner = ups if ups.use_unified_color else brush
    color = color_owner.color
    erase = (color[0] + color[1] + color[2]) / 3.0 >= 0.5
    return int(size_owner.size), float(strength_owner.strength), erase


def _circle_pixels(width, height, uv, radius):
    cx, cy = uv[0] * width, uv[1] * height
    x0, x1 = max(0, int(cx - radius)), min(width - 1, int(cx + radius))
    y0, y1 = max(0, int(cy - radius)), min(height - 1, int(cy + radius))
    rr = radius * radius
    return {y * width + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= rr}


def _uv_inside_image(uv):
    return bool(uv is not None and 0.0 <= uv[0] <= 1.0 and 0.0 <= uv[1] <= 1.0)


def _click_hits_mesh(context, x, y):
    if not context.area or context.area.type != 'VIEW_3D':
        return False
    from bpy_extras import view3d_utils
    obj = context.active_object
    if not obj or obj.type != 'MESH' or not context.region or not context.region_data:
        return False
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    origin = view3d_utils.region_2d_to_origin_3d(
        context.region, context.region_data, (x, y))
    direction = view3d_utils.region_2d_to_vector_3d(
        context.region, context.region_data, (x, y))
    inverse = evaluated.matrix_world.inverted()
    hit, _location, _normal, _face = evaluated.ray_cast(
        inverse @ origin, (inverse.to_3x3() @ direction).normalized())
    return hit


def _lasso_pixels(width, height, uvs):
    if len(uvs) < 3:
        return set()
    xs, ys = [uv[0] for uv in uvs], [uv[1] for uv in uvs]
    x0, x1 = max(0, int(min(xs) * width)), min(width - 1, int(max(xs) * width))
    y0, y1 = max(0, int(min(ys) * height)), min(height - 1, int(max(ys) * height))
    return {y * width + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if _point_in_polygon(((x + 0.5) / width, (y + 0.5) / height), uvs)}


def _adaptive_subdivisions(screen_points, spacing=8.0, maximum=128):
    """Choose enough samples that large on-screen faces cannot hide a stroke."""
    if len(screen_points) < 2:
        return 4
    max_edge = max(
        ((screen_points[index] - screen_points[(index + 1) % len(screen_points)]).length
         for index in range(len(screen_points))), default=0.0)
    return max(4, min(maximum, int(max_edge / spacing) + 1))


def _projected_mask_pixels(context, source, screen_points, radius, include_backfaces):
    """Project a screen lasso/brush onto evaluated mesh UV pixels."""
    from bpy_extras import view3d_utils
    obj = context.active_object
    if not obj or obj.type != 'MESH' or not context.region_data:
        return set()
    eval_obj = obj.evaluated_get(context.evaluated_depsgraph_get())
    mesh = eval_obj.data
    uv_data = _uv_data(mesh)
    if uv_data is None:
        return set()
    region, rv3d = context.region, context.region_data
    width, height = source.size[:]
    matrix = eval_obj.matrix_world
    normal_matrix = matrix.to_3x3().inverted().transposed()
    restrict_to_selected_faces = bool(obj.data.use_paint_mask)

    def in_shape(point):
        if radius is None:
            return _point_in_polygon(point, screen_points)
        rr = radius * radius
        return any((point[0] - p[0]) ** 2 + (point[1] - p[1]) ** 2 <= rr
                   for p in screen_points)

    def lerp(a, b, c, s, t):
        return a + (b - a) * s + (c - a) * t

    result = set()
    for poly in mesh.polygons:
        if restrict_to_selected_faces and not poly.select:
            continue
        world_normal = (normal_matrix @ poly.normal).normalized()
        loops = list(poly.loop_indices)
        for corner in range(1, len(loops) - 1):
            ids = (loops[0], loops[corner], loops[corner + 1])
            verts = [matrix @ mesh.vertices[mesh.loops[index].vertex_index].co for index in ids]
            uvs = [uv_data[index].uv.copy() for index in ids]
            projected = [view3d_utils.location_3d_to_region_2d(region, rv3d, vertex)
                         for vertex in verts]
            if any(point is None for point in projected):
                continue
            # A fixed four-way split misses small brush/lasso regions on a
            # large polygon. Keep samples roughly eight screen pixels apart,
            # while capping pathological close-up geometry.
            subdivisions = _adaptive_subdivisions(projected)
            for i in range(subdivisions):
                for j in range(subdivisions - i):
                    s, t = i / subdivisions, j / subdivisions
                    s1, t1 = (i + 1) / subdivisions, (j + 1) / subdivisions
                    micro = [((s, t), (s1, t), (s, t1))]
                    if i + j + 2 <= subdivisions:
                        micro.append(((s1, t), (s1, t1), (s, t1)))
                    for coords in micro:
                        world = [lerp(verts[0], verts[1], verts[2], ss, tt) for ss, tt in coords]
                        center = sum(world, world[0] * 0.0) / 3.0
                        screen = view3d_utils.location_3d_to_region_2d(region, rv3d, center)
                        if screen is None or not in_shape((screen.x, screen.y)):
                            continue
                        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, screen)
                        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, screen)
                        if not include_backfaces:
                            if world_normal.dot(origin - center) <= 0.0:
                                continue
                            inv = matrix.inverted()
                            hit, _loc, _normal, hit_index = eval_obj.ray_cast(
                                inv @ origin, (inv.to_3x3() @ direction).normalized())
                            if not hit or hit_index != poly.index:
                                continue
                        uv_tri = tuple(lerp(uvs[0], uvs[1], uvs[2], ss, tt) for ss, tt in coords)
                        result.update(_rasterized_pixels(width, height, [uv_tri]))
    return result


_lasso_preview = {"area": 0, "points": [], "erase": False}
_draw_handlers = []


def _draw_lasso_preview():
    if not _lasso_preview["points"] or not bpy.context.area:
        return
    if bpy.context.area.as_pointer() != _lasso_preview["area"]:
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    shader.bind()
    points = list(_lasso_preview["points"])
    shade = 1.0 if _lasso_preview["erase"] else 0.0
    if len(points) >= 3:
        triangles = []
        for index in range(1, len(points) - 1):
            triangles.extend((points[0], points[index], points[index + 1]))
        fill = batch_for_shader(shader, 'TRIS', {"pos": triangles})
        shader.uniform_float("color", (shade, shade, shade, 0.35))
        fill.draw(shader)
    outline_points = points + ([points[0]] if len(points) > 2 else [])
    outline = batch_for_shader(shader, 'LINE_STRIP', {"pos": outline_points})
    shader.uniform_float("color", (shade, shade, shade, 1.0))
    outline.draw(shader)
    gpu.state.blend_set('NONE')


_mask_gpu_shader = None
_mask_gpu_batch_cache = {"key": None, "batch": None}


def _get_mask_gpu_shader():
    global _mask_gpu_shader
    if _mask_gpu_shader is not None:
        return _mask_gpu_shader
    import gpu
    interface = gpu.types.GPUStageInterfaceInfo("faidlix_mask_interface")
    interface.smooth('VEC2', "uvInterp")
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('MAT4', "viewProjectionMatrix")
    info.sampler(0, 'FLOAT_2D', "maskTexture")
    info.vertex_in(0, 'VEC3', "position")
    info.vertex_in(1, 'VEC2', "uv")
    info.vertex_out(interface)
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source(
        "void main() {"
        "  uvInterp = uv;"
        "  vec4 clip = viewProjectionMatrix * vec4(position, 1.0);"
        "  clip.z -= 0.0002 * clip.w;"
        "  gl_Position = clip;"
        "}")
    info.fragment_source(
        "void main() {"
        "  float amount = texture(maskTexture, uvInterp).g;"
        "  if (amount <= 0.00001) discard;"
        "  FragColor = vec4(0.0, 1.0, 0.0, amount * 0.35);"
        "}")
    _mask_gpu_shader = gpu.shader.create_from_info(info)
    return _mask_gpu_shader


def _mask_gpu_batch(obj, shader):
    mesh = obj.data
    uv_data = _uv_data(mesh)
    if uv_data is None:
        return None
    key = (obj.as_pointer(), mesh.as_pointer(), len(mesh.vertices),
           len(mesh.loops), len(mesh.polygons), mesh.uv_layers.active.name)
    if _mask_gpu_batch_cache["key"] == key:
        return _mask_gpu_batch_cache["batch"]
    positions = []
    uvs = []
    for poly in mesh.polygons:
        loops = list(poly.loop_indices)
        for corner in range(1, len(loops) - 1):
            for loop_index in (loops[0], loops[corner], loops[corner + 1]):
                positions.append(mesh.vertices[mesh.loops[loop_index].vertex_index].co)
                uvs.append(uv_data[loop_index].uv)
    if not positions:
        return None
    from gpu_extras.batch import batch_for_shader
    batch = batch_for_shader(
        shader, 'TRIS', {"position": positions, "uv": uvs})
    _mask_gpu_batch_cache["key"] = key
    _mask_gpu_batch_cache["batch"] = batch
    return batch


def _draw_mask_overlay_3d():
    context = bpy.context
    if not context.area or context.area.type != 'VIEW_3D' or context.mode != 'PAINT_TEXTURE':
        return
    obj = context.active_object
    source = _active_image(context)
    if not obj or obj.type != 'MESH' or source is None or context.region_data is None:
        return
    mask = _mask_image(source, create=False)
    if mask is None:
        return
    import gpu
    shader = _get_mask_gpu_shader()
    batch = _mask_gpu_batch(obj, shader)
    if batch is None:
        return
    texture = gpu.texture.from_image(mask)
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('LESS_EQUAL')
    shader.bind()
    shader.uniform_float(
        "viewProjectionMatrix", context.region_data.perspective_matrix @ obj.matrix_world)
    shader.uniform_sampler("maskTexture", texture)
    batch.draw(shader)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _mask_horizontal_runs(mask):
    key = (mask.as_pointer(), tuple(mask.size[:]), _mask_overlay_revision)
    if _mask_image_overlay_cache["key"] == key:
        return _mask_image_overlay_cache["runs"]
    width, height = mask.size[:]
    pixels = array('f', [0.0]) * (width * height * 4)
    mask.pixels.foreach_get(pixels)
    runs = []
    for y in range(height):
        x = 0
        while x < width:
            while x < width and pixels[(y * width + x) * 4 + 1] <= 1.0e-5:
                x += 1
            start = x
            while x < width and pixels[(y * width + x) * 4 + 1] > 1.0e-5:
                x += 1
            if start < x:
                runs.append((start, y, x))
    _mask_image_overlay_cache["key"] = key
    _mask_image_overlay_cache["runs"] = runs
    return runs


_mask_image_gpu_shader = None


def _get_mask_image_gpu_shader():
    global _mask_image_gpu_shader
    if _mask_image_gpu_shader is not None:
        return _mask_image_gpu_shader
    import gpu
    interface = gpu.types.GPUStageInterfaceInfo("faidlix_mask_image_interface")
    interface.smooth('VEC2', "uvInterp")
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant('VEC2', "viewportSize")
    info.sampler(0, 'FLOAT_2D', "maskTexture")
    info.vertex_in(0, 'VEC2', "position")
    info.vertex_in(1, 'VEC2', "uv")
    info.vertex_out(interface)
    info.fragment_out(0, 'VEC4', "FragColor")
    info.vertex_source(
        "void main() {"
        "  uvInterp = uv;"
        "  vec2 ndc = (position / viewportSize) * 2.0 - 1.0;"
        "  gl_Position = vec4(ndc, 0.0, 1.0);"
        "}")
    info.fragment_source(
        "void main() {"
        "  float amount = texture(maskTexture, uvInterp).g;"
        "  if (amount <= 0.00001) discard;"
        "  FragColor = vec4(0.0, 1.0, 0.0, amount * 0.35);"
        "}")
    _mask_image_gpu_shader = gpu.shader.create_from_info(info)
    return _mask_image_gpu_shader


def _draw_mask_overlay_image():
    context = bpy.context
    if not context.area or context.area.type != 'IMAGE_EDITOR':
        return
    source = getattr(context.space_data, "image", None)
    if source is None:
        return
    mask = _mask_image(source, create=False)
    if mask is None:
        return
    region = context.region
    view2d = region.view2d
    width, height = mask.size[:]
    bounds = view2d.cur
    pixel_coordinates = max(
        abs(bounds.xmin), abs(bounds.xmax), abs(bounds.ymin), abs(bounds.ymax)) > 2.0

    def region_point(x, y):
        if not pixel_coordinates:
            x, y = x / width, y / height
        return view2d.view_to_region(x, y, clip=False)

    left, bottom = region_point(0, 0)
    right, top = region_point(width, height)
    positions = ((left, bottom), (right, bottom), (right, top),
                 (left, bottom), (right, top), (left, top))
    uvs = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0),
           (0.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    import gpu
    from gpu_extras.batch import batch_for_shader
    shader = _get_mask_image_gpu_shader()
    batch = batch_for_shader(
        shader, 'TRIS', {"position": positions, "uv": uvs})
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_sampler("maskTexture", gpu.texture.from_image(mask))
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _clear_lasso_preview():
    _lasso_preview["area"] = 0
    _lasso_preview["points"] = []
    _lasso_preview["erase"] = False


def _polygon_uvs(poly, uv_data):
    return [(float(uv_data[i].uv.x), float(uv_data[i].uv.y)) for i in poly.loop_indices]


def _triangles(polygons, uv_data):
    result = []
    for poly in polygons:
        points = _polygon_uvs(poly, uv_data)
        for index in range(1, len(points) - 1):
            result.append((points[0], points[index], points[index + 1]))
    return result


def _inside_triangle(px, py, tri):
    (ax, ay), (bx, by), (cx, cy) = tri
    d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    return not ((d1 < 0.0 or d2 < 0.0 or d3 < 0.0) and
                (d1 > 0.0 or d2 > 0.0 or d3 > 0.0))


def _rasterized_pixels(width, height, triangles):
    covered = set()
    for tri in triangles:
        xs = [p[0] * width for p in tri]
        ys = [p[1] * height for p in tri]
        x0 = max(0, int(min(xs)))
        y0 = max(0, int(min(ys)))
        x1 = min(width - 1, int(max(xs)))
        y1 = min(height - 1, int(max(ys)))
        for y in range(y0, y1 + 1):
            v = (y + 0.5) / height
            for x in range(x0, x1 + 1):
                u = (x + 0.5) / width
                if _inside_triangle(u, v, tri):
                    covered.add(y * width + x)
    return covered


def _paint_face_mask_indices(context, source):
    obj = context.active_object
    if not obj or obj.type != 'MESH' or not obj.data.use_paint_mask:
        return None
    if obj.mode == 'EDIT':
        obj.update_from_editmode()
    polygons = [poly for poly in obj.data.polygons if poly.select and not poly.hide]
    uv_data = _uv_data(obj.data)
    if uv_data is None or not polygons:
        return set()
    return _rasterized_pixels(
        source.size[0], source.size[1], _triangles(polygons, uv_data))


def _write_mask_scope(context, source, value):
    face_indices = _paint_face_mask_indices(context, source)
    if face_indices is None:
        return _write_all_mask(source, value)
    return _write_mask(source, face_indices, value)


def _expand_pixels(indices, width, height, padding):
    if padding <= 0:
        return set(indices)
    expanded = set(indices)
    for index in indices:
        x, y = index % width, index // width
        for dy in range(-padding, padding + 1):
            yy = y + dy
            if yy < 0 or yy >= height:
                continue
            limit = int((padding * padding - dy * dy) ** 0.5)
            for dx in range(-limit, limit + 1):
                xx = x + dx
                if 0 <= xx < width:
                    expanded.add(yy * width + xx)
    return expanded


def _mode_channel(base, paint, mode):
    eps = 1.0e-8
    if mode == 'DARKEN': return min(base, paint)
    if mode == 'MUL': return base * paint
    if mode == 'COLORBURN': return 0.0 if paint <= eps else 1.0 - min(1.0, (1.0 - base) / paint)
    if mode == 'LINEARBURN': return max(0.0, base + paint - 1.0)
    if mode == 'LIGHTEN': return max(base, paint)
    if mode == 'SCREEN': return 1.0 - (1.0 - base) * (1.0 - paint)
    if mode == 'COLORDODGE': return 1.0 if paint >= 1.0 - eps else min(1.0, base / (1.0 - paint))
    if mode == 'ADD': return min(1.0, base + paint)
    if mode == 'OVERLAY': return 2.0 * base * paint if base < 0.5 else 1.0 - 2.0 * (1.0 - base) * (1.0 - paint)
    if mode == 'SOFTLIGHT': return (1.0 - 2.0 * paint) * base * base + 2.0 * paint * base
    if mode == 'HARDLIGHT': return 2.0 * base * paint if paint < 0.5 else 1.0 - 2.0 * (1.0 - base) * (1.0 - paint)
    if mode == 'VIVIDLIGHT': return _mode_channel(base, 2.0 * paint, 'COLORBURN') if paint < 0.5 else _mode_channel(base, 2.0 * (paint - 0.5), 'COLORDODGE')
    if mode == 'LINEARLIGHT': return max(0.0, min(1.0, base + 2.0 * paint - 1.0))
    if mode == 'PINLIGHT': return min(base, 2.0 * paint) if paint < 0.5 else max(base, 2.0 * paint - 1.0)
    if mode == 'DIFFERENCE': return abs(base - paint)
    if mode == 'EXCLUSION': return base + paint - 2.0 * base * paint
    if mode == 'SUB': return max(0.0, base - paint)
    return paint


def _mode_rgb(base, paint, mode):
    if mode in {'HUE', 'SATURATION', 'COLOR', 'LUMINOSITY'}:
        bh, bs, bv = colorsys.rgb_to_hsv(*base)
        ph, ps, pv = colorsys.rgb_to_hsv(*paint)
        values = {
            'HUE': (ph, bs, bv), 'SATURATION': (bh, ps, bv),
            'COLOR': (ph, ps, bv), 'LUMINOSITY': (bh, bs, pv),
        }
        return colorsys.hsv_to_rgb(*values[mode])
    return tuple(_mode_channel(base[i], paint[i], mode) for i in range(3))


def _blend(pixels, index, color, strength=1.0, mode='MIX'):
    offset = index * 4
    factor = max(0.0, min(1.0, strength))
    if mode == 'ERASE_ALPHA':
        pixels[offset + 3] *= 1.0 - factor
        return
    if mode == 'ADD_ALPHA':
        pixels[offset + 3] = min(1.0, pixels[offset + 3] + factor)
        return
    base = tuple(pixels[offset + i] for i in range(3))
    target = _mode_rgb(base, tuple(color[:3]), mode)
    for channel in range(3):
        pixels[offset + channel] = base[channel] * (1.0 - factor) + target[channel] * factor
    pixels[offset + 3] = pixels[offset + 3] * (1.0 - factor) + color[3] * factor


def _brush_state(context):
    from bl_ui.properties_paint_common import UnifiedPaintPanel
    paint = UnifiedPaintPanel.paint_settings(context)
    brush = paint.brush if paint else None
    if brush is None:
        return tuple(context.scene.faidlix_paint.color), 1.0, 'MIX'
    ups = paint.unified_paint_settings
    color_owner = ups if ups.use_unified_color else brush
    strength_owner = ups if ups.use_unified_strength else brush
    color = (color_owner.color[0], color_owner.color[1], color_owner.color[2], 1.0)
    return color, strength_owner.strength, brush.blend


def _draw_fill_settings(context, layout, show_padding=False):
    from bl_ui.properties_paint_common import UnifiedPaintPanel
    paint = UnifiedPaintPanel.paint_settings(context)
    brush = paint.brush if paint else None
    if brush:
        row = layout.row(align=True)
        row.ui_units_x = 4
        UnifiedPaintPanel.prop_unified_color(row, context, brush, "color", text="")
        UnifiedPaintPanel.prop_unified_color(row, context, brush, "secondary_color", text="")
        layout.prop(brush, "blend", text="")
        UnifiedPaintPanel.prop_unified(
            layout, context, brush, "strength", unified_name="use_unified_strength",
            text="Strength", slider=True, header=True)
    if show_padding:
        layout.prop(context.scene.faidlix_paint, "island_padding", text="外擴邊緣")


class FAIDLIXPAINT_Properties(PropertyGroup):
    color: FloatVectorProperty(
        name="顏色", subtype='COLOR', size=4,
        min=0.0, max=1.0, default=(0.8, 0.08, 0.03, 1.0),
        description="填色使用的 RGBA 顏色",
    )
    mask_brush_radius: IntProperty(
        name="遮罩筆刷大小", min=1, max=1024, default=32,
        description="圖片像素遮罩筆刷的半徑（像素）")
    island_padding: IntProperty(
        name="外擴邊緣", min=0, max=128, default=2,
        description="UV 島填色向外擴張的像素數，避免接縫漏色")
    mask_include_backfaces: BoolProperty(
        name="背面", default=False,
        description="勾選時將螢幕範圍內的背面投影也寫入 MaskMap")
    mask_feather: IntProperty(
        name="邊緣柔化", min=0, max=128, default=0,
        description="以像素為單位柔化遮罩邊緣；0 表示硬邊",
        update=_update_mask_feather)


class FAIDLIXPAINT_OT_fill(Operator):
    bl_idname = "faidlix_paint.fill"
    bl_label = "Faidlix 填色"
    bl_description = "填滿整張圖片／遮罩，或選取的 UV 島"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="範圍",
        items=(
            ('LAYER', "整個塗層", "整張圖片；啟用面遮罩時只填選取面"),
            ('UV_ISLAND', "UV 島", "填滿 UV 編輯器或網格中選取的 UV 島"),
        ),
        default='LAYER',
    )
    click_x: FloatProperty(options={'HIDDEN', 'SKIP_SAVE'})
    click_y: FloatProperty(options={'HIDDEN', 'SKIP_SAVE'})
    click_area: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        image = _active_image(context)
        return bool(image and image.type in {'IMAGE', 'GENERATED'} and image.size[0] and image.size[1])

    def execute(self, context):
        image = _active_image(context)
        if image is None:
            self.report({'ERROR'}, "找不到作用中的繪製圖片")
            return {'CANCELLED'}
        if image.source == 'TILED':
            self.report({'ERROR'}, "目前版本尚未支援 UDIM 圖片")
            return {'CANCELLED'}

        width, height = image.size[:]
        pixel_count = width * height
        if width < 1 or height < 1:
            self.report({'ERROR'}, "圖片尺寸無效")
            return {'CANCELLED'}

        obj = context.active_object
        indices = None
        restrict_to_uv = self.target == 'UV_ISLAND'
        if self.target == 'LAYER' and obj and obj.type == 'MESH':
            restrict_to_uv = bool(obj.data.use_paint_mask)

        if restrict_to_uv:
            if not obj or obj.type != 'MESH' or not obj.data.uv_layers.active:
                self.report({'ERROR'}, "需要有作用中 UV 的網格物件")
                return {'CANCELLED'}
            if obj.mode == 'EDIT':
                obj.update_from_editmode()
            if self.target == 'UV_ISLAND':
                uv = _uv_from_click(context, self.click_x, self.click_y, image)
                seed = _seed_from_uv(obj.data, uv) if uv else -1
                polygons = _uv_island(obj.data, seed)
                if obj.data.use_paint_mask:
                    polygons = [poly for poly in polygons if poly.select and not poly.hide]
            else:
                polygons = _selected_polygons(obj, self.target)
            if not polygons:
                self.report({'ERROR'}, "游標下找不到 UV 島，或面遮罩沒有選取面")
                return {'CANCELLED'}
            indices = _rasterized_pixels(width, height, _triangles(polygons, _uv_data(obj.data)))
            if self.target == 'UV_ISLAND':
                indices = _expand_pixels(
                    indices, width, height, context.scene.faidlix_paint.island_padding)
            if not indices:
                self.report({'ERROR'}, "選取範圍未落在目前圖片內")
                return {'CANCELLED'}

        target_indices = indices if indices is not None else range(pixel_count)
        mask = _mask_image(image, create=False)
        protection_values = None
        if mask is not None:
            protection_values = _mask_protection_values(mask, pixel_count)
            if all(protection_values[index] >= 1.0 - 1.0e-5
                   for index in target_indices):
                self.report({'ERROR'}, "目標範圍已全部受到遮罩保護")
                return {'CANCELLED'}

        pixels = array('f', [0.0]) * (pixel_count * 4)
        image.pixels.foreach_get(pixels)
        color, strength, blend_mode = _brush_state(context)
        for index in target_indices:
            protection = protection_values[index] if protection_values is not None else 0.0
            effective_strength = strength * (1.0 - protection)
            if effective_strength > 1.0e-5:
                _blend(pixels, index, color, effective_strength, blend_mode)
        image.pixels.foreach_set(pixels)
        image.update()
        scope = "UV／遮罩範圍" if indices is not None else "整張圖片"
        self.report({'INFO'}, f"已填色：{scope}")
        return {'FINISHED'}

    def invoke(self, context, event):
        self.click_x = event.mouse_region_x
        self.click_y = event.mouse_region_y
        self.click_area = context.area.type if context.area else ""
        return self.execute(context)


class FAIDLIXPAINT_OT_sample_color(Operator):
    bl_idname = "faidlix_paint.sample_color"
    bl_label = "Faidlix 滴管"
    bl_description = "點一下圖片或模型以吸取顏色"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        area = context.area
        if not area:
            return False
        return ((area.type == 'VIEW_3D' and context.mode == 'PAINT_TEXTURE') or
                (area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'PAINT'))

    def invoke(self, context, event):
        return _invoke_native_eyedropper(context)


def _invoke_native_eyedropper(context):
    paint = context.tool_settings.image_paint
    if paint.brush is None:
        return {'CANCELLED'}
    if paint.unified_paint_settings.use_unified_color:
        path = "scene.tool_settings.image_paint.unified_paint_settings.color"
    else:
        path = "scene.tool_settings.image_paint.brush.color"
    # Use Blender's native UI eyedropper, the same operator used by the
    # eyedropper beside a color property. This samples the rendered screen,
    # supports drag averaging, Enter/left-click confirm, and Esc cancel.
    result = bpy.ops.ui.eyedropper_color('INVOKE_DEFAULT', prop_data_path=path)
    return {'FINISHED'} if 'RUNNING_MODAL' in result else result


class FAIDLIXPAINT_OT_activate_eyedropper(Operator):
    bl_idname = "faidlix_paint.activate_eyedropper"
    bl_label = "Faidlix 暫時滴管"
    bl_description = "暫時吸取一次顏色，不切換目前工具"

    @classmethod
    def poll(cls, context):
        area = context.area
        if not area:
            return False
        return ((area.type == 'VIEW_3D' and context.mode == 'PAINT_TEXTURE') or
                (area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'PAINT'))

    def invoke(self, context, _event):
        return _invoke_native_eyedropper(context)

    def execute(self, context):
        # Keymap items execute operators by default; keep this identical to
        # clicking the bottom toolbar eyedropper.
        return _invoke_native_eyedropper(context)


class FAIDLIXPAINT_OT_online_update(Operator):
    bl_idname = "faidlix_paint.online_update"
    bl_label = "線上更新"
    bl_description = "從 Faidlix/BlenderAddons 檢查並安裝較新版本"
    bl_options = {'INTERNAL'}

    force: BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        context.preferences.system.use_online_access = True
        repo_index, repo = _ensure_github_repository(context)
        if repo is None:
            self.report({'ERROR'}, "無法建立 Faidlix Paint GitHub 來源")
            return {'CANCELLED'}
        try:
            sync_result = bpy.ops.extensions.repo_sync(repo_index=repo_index)
        except RuntimeError as exc:
            self.report({'ERROR'}, f"GitHub 同步失敗：{exc}")
            return {'CANCELLED'}
        if sync_result != {'FINISHED'}:
            self.report({'ERROR'}, "GitHub 同步未完成")
            return {'CANCELLED'}
        latest = _latest_version_from_index(_cached_repository_index(repo) or {})
        if not latest:
            self.report({'ERROR'}, "GitHub 索引中找不到 Faidlix Paint")
            return {'CANCELLED'}
        if latest <= ADDON_VERSION and not self.force:
            bpy.ops.wm.save_userpref()
            self.report({'INFO'}, f"Faidlix Paint {'.'.join(map(str, ADDON_VERSION))} 已是最新版")
            return {'FINISHED'}
        version_text = '.'.join(map(str, latest))

        def install_after_operator_returns():
            try:
                result = bpy.ops.extensions.package_install(
                    repo_index=repo_index, pkg_id=PACKAGE_ID, enable_on_install=True)
                if result == {'FINISHED'}:
                    bpy.ops.wm.save_userpref()
                    print(f"Faidlix Paint {version_text} installed from GitHub")
                else:
                    print("Faidlix Paint online update did not finish")
            except Exception as exc:
                print(f"Faidlix Paint online update failed: {exc}")
            return None

        bpy.app.timers.register(install_after_operator_returns, first_interval=0.1)
        self.report({'INFO'}, f"已找到 {version_text}，準備從 GitHub 安裝")
        return {'FINISHED'}


class FAIDLIXPAINT_Preferences(AddonPreferences):
    bl_idname = __package__

    def draw(self, _context):
        layout = self.layout
        layout.label(text=f"Installed version: {'.'.join(map(str, ADDON_VERSION))}")
        layout.operator(FAIDLIXPAINT_OT_online_update.bl_idname,
                        text="Check and Install Online Update", icon='FILE_REFRESH')


class FAIDLIXPAINT_OT_mask_to_image(Operator):
    bl_idname = "faidlix_paint.mask_to_image"
    bl_label = "將 Mask 轉為黑白圖片"
    bl_description = "建立白色受保護、黑色可繪製的 MaskBW 圖片"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        source = _active_image(context)
        return bool(source and _mask_image(source, create=False))

    def execute(self, context):
        source = _active_image(context)
        output = _mask_to_bw_image(source) if source else None
        if output is None:
            self.report({'ERROR'}, "目前圖片尚未建立 MaskMap")
            return {'CANCELLED'}
        self.report({'INFO'}, f"已建立黑白遮罩圖片：{output.name}")
        return {'FINISHED'}


class FAIDLIXPAINT_OT_mask_edit(Operator):
    bl_idname = "faidlix_paint.mask_edit"
    bl_label = "編輯圖片像素遮罩"
    bl_description = "以筆刷、UV 島或選取工具建立受保護的圖片像素遮罩"
    bl_options = {'REGISTER', 'UNDO'}

    action: EnumProperty(items=(
        ('BRUSH', "筆刷塗抹", "以圓形筆刷塗抹遮罩"),
        ('UV_ISLAND', "UV 島填滿", "點擊並填滿完整 UV 島遮罩"),
        ('LASSO', "Lasso 框選", "拖曳圈選遮罩像素"),
        ('BOX', "Select Box", "拖曳矩形範圍遮罩"),
        ('CIRCLE', "Select Circle", "拖曳圓形範圍遮罩"),
    ))
    erase: BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return FAIDLIXPAINT_OT_fill.poll(context)

    def _uv(self, context, event):
        uv = _uv_from_click(context, event.mouse_region_x, event.mouse_region_y, self._source)
        return uv if _uv_inside_image(uv) else None

    def invoke(self, context, event):
        self._source = _active_image(context)
        if not self._source or self._source.source == 'TILED':
            self.report({'ERROR'}, "找不到可用圖片，或圖片是尚未支援的 UDIM")
            return {'CANCELLED'}
        width, height = self._source.size[:]
        self._erase = bool(self.erase)
        self._mask_strength = 1.0
        self._brush_radius = context.scene.faidlix_paint.mask_brush_radius
        if self.action == 'BRUSH':
            self._brush_radius, self._mask_strength, color_erase = _mask_brush_state(context)
            self._erase = self._erase or color_erase
        uv = self._uv(context, event)
        if self.action == 'BRUSH':
            hits_target = (_uv_inside_image(uv) if context.area.type == 'IMAGE_EDITOR'
                           else _click_hits_mesh(
                               context, event.mouse_region_x, event.mouse_region_y))
            if not hits_target:
                count = _write_mask_scope(
                    context, self._source, 0.0 if self._erase else 1.0)
                if not count:
                    self.report({'WARNING'}, "面選取遮罩中沒有可修改的像素")
                    return {'CANCELLED'}
                self.report({'INFO'}, "已清空全部遮罩" if self._erase else "已遮罩整張圖片")
                return {'FINISHED'}
            state, error = _invoke_native_mask_brush(
                context, self._source, self._erase)
            if error:
                self.report({'ERROR'}, f"無法啟動原生遮罩筆刷：{error}")
                return {'CANCELLED'}
            self._native_state = state
            self._finish_timer = None
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        if self.action == 'UV_ISLAND':
            obj = context.active_object
            if not uv:
                count = _write_mask_scope(
                    context, self._source, 0.0 if self._erase else 1.0)
                if not count:
                    self.report({'WARNING'}, "面選取遮罩中沒有可修改的像素")
                    return {'CANCELLED'}
                self.report({'INFO'}, "已清空全部遮罩" if self._erase else "已遮罩整張圖片")
                return {'FINISHED'}
            if not obj or obj.type != 'MESH':
                self.report({'ERROR'}, "游標下找不到有 UV 的網格")
                return {'CANCELLED'}
            seed = _seed_from_uv(obj.data, uv)
            polygons = _uv_island(obj.data, seed)
            if obj.data.use_paint_mask:
                polygons = [poly for poly in polygons if poly.select and not poly.hide]
            indices = _rasterized_pixels(width, height, _triangles(polygons, _uv_data(obj.data)))
            if not indices:
                self.report({'ERROR'}, "游標下找不到 UV 島")
                return {'CANCELLED'}
            _write_mask(self._source, indices, 0.0 if self._erase else 1.0)
            self.report({'INFO'}, "已從遮罩移除 UV 島" if self._erase else "已將 UV 島加入遮罩")
            return {'FINISHED'}

        self._indices = set()
        self._points = []
        self._screen_points = [(event.mouse_region_x, event.mouse_region_y)]
        self._start = self._screen_points[0]
        self._straight = False
        brush_hits_mesh = (
            self.action == 'BRUSH' and context.area.type == 'VIEW_3D'
            and _click_hits_mesh(context, event.mouse_region_x, event.mouse_region_y))
        if uv or brush_hits_mesh:
            if self.action == 'BRUSH':
                if context.area.type == 'IMAGE_EDITOR':
                    self._indices.update(_circle_pixels(
                        width, height, uv, self._brush_radius))
            else:
                self._points.append(uv)
        elif self.action == 'BRUSH':
            count = _write_mask_scope(
                context, self._source, 0.0 if self._erase else 1.0)
            if not count:
                self.report({'WARNING'}, "面選取遮罩中沒有可修改的像素")
                return {'CANCELLED'}
            self.report({'INFO'}, "已清空全部遮罩" if self._erase else "已遮罩整張圖片")
            return {'FINISHED'}
        if self.action in {'LASSO', 'BOX', 'CIRCLE'}:
            _lasso_preview["area"] = context.area.as_pointer()
            _lasso_preview["points"] = list(self._screen_points)
            _lasso_preview["erase"] = self._erase
            context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self.action == 'BRUSH' and hasattr(self, "_native_state"):
            if event.type in {'LEFTMOUSE', 'ESC', 'RIGHTMOUSE'} and (
                    event.value == 'RELEASE' or event.type in {'ESC', 'RIGHTMOUSE'}):
                if self._finish_timer is None:
                    self._finish_timer = context.window_manager.event_timer_add(
                        0.05, window=context.window)
                return {'PASS_THROUGH'}
            if event.type == 'TIMER' and event.timer == self._finish_timer:
                context.window_manager.event_timer_remove(self._finish_timer)
                _finish_native_mask_stroke(self._native_state)
                del self._native_state
                return {'FINISHED'}
            return {'PASS_THROUGH'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            _clear_lasso_preview()
            if context.area:
                context.area.tag_redraw()
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            uv = self._uv(context, event)
            if self.action == 'BRUSH':
                if uv:
                    self._screen_points.append((event.mouse_region_x, event.mouse_region_y))
                    if context.area.type == 'IMAGE_EDITOR':
                        self._indices.update(_circle_pixels(
                            self._source.size[0], self._source.size[1], uv,
                            self._brush_radius))
            elif self.action == 'LASSO':
                point = (event.mouse_region_x, event.mouse_region_y)
                if event.shift:
                    if not self._straight:
                        self._straight = True
                        self._screen_points.append(point)
                    else:
                        self._screen_points[-1] = point
                else:
                    self._straight = False
                    self._screen_points.append(point)
                self._points = [
                    value for value in (
                        _uv_from_click(context, x, y, self._source)
                        for x, y in self._screen_points)
                    if value is not None]
                _lasso_preview["points"] = list(self._screen_points)
                context.area.tag_redraw()
            elif self.action in {'BOX', 'CIRCLE'}:
                x0, y0 = self._start
                x1, y1 = event.mouse_region_x, event.mouse_region_y
                if self.action == 'BOX':
                    self._screen_points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                else:
                    import math
                    radius = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
                    self._screen_points = [
                        (x0 + math.cos(index * math.tau / 48) * radius,
                         y0 + math.sin(index * math.tau / 48) * radius)
                        for index in range(48)]
                _lasso_preview["points"] = list(self._screen_points)
                context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self.action == 'BRUSH' and context.area.type == 'VIEW_3D':
                self._indices = _projected_mask_pixels(
                    context, self._source, self._screen_points,
                    self._brush_radius,
                    context.scene.faidlix_paint.mask_include_backfaces)
            elif self.action in {'LASSO', 'BOX', 'CIRCLE'}:
                moved = ((event.mouse_region_x - self._start[0]) ** 2 +
                         (event.mouse_region_y - self._start[1]) ** 2) ** 0.5
                _clear_lasso_preview()
                if context.area:
                    context.area.tag_redraw()
                if moved < 4.0 and self._uv(context, event) is None:
                    count = _write_mask_scope(
                        context, self._source, 0.0 if self._erase else 1.0)
                    if not count:
                        self.report({'WARNING'}, "面選取遮罩中沒有可修改的像素")
                        return {'CANCELLED'}
                    self.report({'INFO'}, "已清空全部遮罩" if self._erase else "已遮罩整張圖片")
                    return {'FINISHED'}
                if context.area.type == 'VIEW_3D':
                    self._indices = _projected_mask_pixels(
                        context, self._source, self._screen_points, None,
                        context.scene.faidlix_paint.mask_include_backfaces)
                else:
                    self._points = [
                        value for value in (
                            _uv_from_click(context, x, y, self._source)
                            for x, y in self._screen_points)
                        if value is not None]
                    self._indices = _lasso_pixels(
                        self._source.size[0], self._source.size[1], self._points)
            face_indices = _paint_face_mask_indices(context, self._source)
            if face_indices is not None:
                self._indices.intersection_update(face_indices)
            if not self._indices:
                self.report({'WARNING'}, "沒有可寫入的遮罩像素")
                return {'CANCELLED'}
            count = _write_mask(
                self._source, self._indices, 0.0 if self._erase else 1.0,
                self._mask_strength if self.action == 'BRUSH' else 1.0)
            action = "移除" if self._erase else "加入"
            self.report({'INFO'}, f"已{action}圖片像素遮罩：{count} 像素")
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class _FaidlixPaintToolBase:
    bl_icon = "brush.paint_texture.fill"
    bl_widget = None

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_fill_settings(context, layout)


def _tool_keymap(target):
    return (("faidlix_paint.fill", {"type": 'LEFTMOUSE', "value": 'PRESS'},
             {"properties": [("target", target)]}),)


class FAIDLIXPAINT_WST_layer_view3d(_FaidlixPaintToolBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.layer_view3d"
    bl_label = "整個塗層"
    bl_description = "點擊填滿整張圖片；啟用面遮罩時只填選取面"
    bl_keymap = _tool_keymap('LAYER')


class FAIDLIXPAINT_WST_island_view3d(_FaidlixPaintToolBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.island_view3d"
    bl_label = "UV 島"
    bl_description = "點擊填滿選取的 UV 島"
    bl_keymap = _tool_keymap('UV_ISLAND')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_fill_settings(context, layout, show_padding=True)


class FAIDLIXPAINT_WST_layer_image(_FaidlixPaintToolBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'
    bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.layer_image"
    bl_label = "整個塗層"
    bl_description = "點擊填滿整張圖片；啟用面遮罩時只填選取面"
    bl_keymap = _tool_keymap('LAYER')


class FAIDLIXPAINT_WST_island_image(_FaidlixPaintToolBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'
    bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.island_image"
    bl_label = "UV 島"
    bl_description = "點擊填滿選取的 UV 島"
    bl_keymap = _tool_keymap('UV_ISLAND')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_fill_settings(context, layout, show_padding=True)


class _FaidlixEyedropperToolBase:
    bl_label = "滴管"
    bl_description = "點一下圖片或模型吸取顏色（快捷鍵 C）"
    bl_icon = "ops.paint.eyedropper_add"
    bl_cursor = 'EYEDROPPER'
    bl_widget = None
    bl_keymap = (("faidlix_paint.sample_color", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),)

    @staticmethod
    def draw_settings(context, layout, _tool):
        layout.prop(context.scene.faidlix_paint, "color", text="吸取顏色")


class FAIDLIXPAINT_WST_eyedropper_view3d(_FaidlixEyedropperToolBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.eyedropper_view3d"


class FAIDLIXPAINT_WST_eyedropper_image(_FaidlixEyedropperToolBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'
    bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.eyedropper_image"


class _OnlineUpdateToolBase:
    bl_label = "線上更新"
    bl_description = "從 GitHub 檢查並安裝 Faidlix Paint 更新"
    bl_icon = "ops.mesh.primitive_sphere_add_gizmo"
    bl_widget = None
    bl_keymap = ()


class FAIDLIXPAINT_WST_update_view3d(_OnlineUpdateToolBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.update_view3d"


class FAIDLIXPAINT_WST_update_image(_OnlineUpdateToolBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.update_image"


def _mask_keymap(action):
    # Blender tool keymaps match modifiers exactly. Register Ctrl explicitly;
    # otherwise Ctrl+LMB never reaches the operator and cannot erase a mask.
    return (
        ("faidlix_paint.mask_edit", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
         {"properties": [("action", action), ("erase", True)]}),
        ("faidlix_paint.mask_edit", {"type": 'LEFTMOUSE', "value": 'PRESS'},
         {"properties": [("action", action), ("erase", False)]}),
    )


def _draw_mask_settings(context, layout):
    settings = context.scene.faidlix_paint
    layout.prop(settings, "mask_include_backfaces", text="背面")
    layout.prop(settings, "mask_feather", text="邊緣柔化")
    layout.operator(
        FAIDLIXPAINT_OT_mask_to_image.bl_idname,
        text="轉黑白圖", icon='IMAGE_DATA')


class _MaskBrushBase:
    bl_label = "筆刷塗抹"
    bl_description = "使用原生筆刷加入圖片像素遮罩；Ctrl 塗抹移除"
    bl_icon = "brush.generic"
    bl_cursor = 'PAINT_CROSS'
    bl_widget = None
    bl_options = {'USE_BRUSHES'}
    bl_keymap = _mask_keymap('BRUSH')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_mask_settings(context, layout)


class _MaskIslandBase:
    bl_label = "UV 島填滿"
    bl_description = "點一下，將完整 UV 島加入圖片像素遮罩"
    bl_icon = "brush.paint_texture.fill"
    bl_widget = None
    bl_keymap = _mask_keymap('UV_ISLAND')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_mask_settings(context, layout)


class _MaskLassoBase:
    bl_label = "Lasso 框選"
    bl_description = "拖曳圈選並加入圖片像素遮罩"
    bl_icon = "ops.generic.select_lasso"
    bl_cursor = 'CROSSHAIR'
    bl_widget = None
    bl_keymap = _mask_keymap('LASSO')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_mask_settings(context, layout)


class _MaskBoxBase:
    bl_label = "Select Box"
    bl_description = "拖曳矩形範圍加入 MaskMap；Ctrl 為減選"
    bl_icon = "ops.generic.select_box"
    bl_cursor = 'CROSSHAIR'
    bl_widget = None
    bl_keymap = _mask_keymap('BOX')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_mask_settings(context, layout)


class _MaskCircleBase:
    bl_label = "Select Circle"
    bl_description = "由中心拖出圓形範圍加入 MaskMap；Ctrl 為減選"
    bl_icon = "ops.generic.select_circle"
    bl_cursor = 'CROSSHAIR'
    bl_widget = None
    bl_keymap = _mask_keymap('CIRCLE')

    @staticmethod
    def draw_settings(context, layout, _tool):
        _draw_mask_settings(context, layout)


class FAIDLIXPAINT_WST_mask_brush_view3d(_MaskBrushBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.mask_brush_view3d"


class FAIDLIXPAINT_WST_mask_island_view3d(_MaskIslandBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.mask_island_view3d"


class FAIDLIXPAINT_WST_mask_lasso_view3d(_MaskLassoBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.mask_lasso_view3d"


class FAIDLIXPAINT_WST_mask_brush_image(_MaskBrushBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.mask_brush_image"


class FAIDLIXPAINT_WST_mask_island_image(_MaskIslandBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.mask_island_image"


class FAIDLIXPAINT_WST_mask_lasso_image(_MaskLassoBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.mask_lasso_image"


class FAIDLIXPAINT_WST_mask_box_view3d(_MaskBoxBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.mask_box_view3d"


class FAIDLIXPAINT_WST_mask_circle_view3d(_MaskCircleBase, WorkSpaceTool):
    bl_space_type = 'VIEW_3D'; bl_context_mode = 'PAINT_TEXTURE'
    bl_idname = "faidlix_paint.mask_circle_view3d"


class FAIDLIXPAINT_WST_mask_box_image(_MaskBoxBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.mask_box_image"


class FAIDLIXPAINT_WST_mask_circle_image(_MaskCircleBase, WorkSpaceTool):
    bl_space_type = 'IMAGE_EDITOR'; bl_context_mode = 'PAINT'
    bl_idname = "faidlix_paint.mask_circle_image"


CLASSES = (
    FAIDLIXPAINT_Properties,
    FAIDLIXPAINT_OT_fill,
    FAIDLIXPAINT_OT_sample_color,
    FAIDLIXPAINT_OT_activate_eyedropper,
    FAIDLIXPAINT_OT_online_update,
    FAIDLIXPAINT_OT_mask_to_image,
    FAIDLIXPAINT_OT_mask_edit,
    FAIDLIXPAINT_Preferences,
)
TOOLS = (
    (FAIDLIXPAINT_WST_update_view3d, {}),
    (FAIDLIXPAINT_WST_update_image, {}),
    (FAIDLIXPAINT_WST_island_view3d, {"after": {"builtin_brush.fill"}}),
    (FAIDLIXPAINT_WST_island_image, {}),
    (FAIDLIXPAINT_WST_mask_brush_view3d, {"after": {"builtin_brush.mask"}}),
    (FAIDLIXPAINT_WST_mask_island_view3d, {"after": {"faidlix_paint.mask_brush_view3d"}}),
    (FAIDLIXPAINT_WST_mask_lasso_view3d, {"after": {"faidlix_paint.mask_island_view3d"}}),
    (FAIDLIXPAINT_WST_mask_box_view3d, {"after": {"faidlix_paint.mask_lasso_view3d"}}),
    (FAIDLIXPAINT_WST_mask_circle_view3d, {"after": {"faidlix_paint.mask_box_view3d"}}),
    (FAIDLIXPAINT_WST_mask_brush_image, {"after": {"builtin_brush.mask"}}),
    (FAIDLIXPAINT_WST_mask_island_image, {"after": {"faidlix_paint.mask_brush_image"}}),
    (FAIDLIXPAINT_WST_mask_lasso_image, {"after": {"faidlix_paint.mask_island_image"}}),
    (FAIDLIXPAINT_WST_mask_box_image, {"after": {"faidlix_paint.mask_lasso_image"}}),
    (FAIDLIXPAINT_WST_mask_circle_image, {"after": {"faidlix_paint.mask_box_image"}}),
    # No `after`: append after Blender's existing paint tools. The separator
    # produces the independent bottom slot requested by the user.
    (FAIDLIXPAINT_WST_eyedropper_view3d, {"separator": True}),
    (FAIDLIXPAINT_WST_eyedropper_image, {"separator": True}),
)

_addon_keymaps = []
_last_tool_state = {}
_last_non_eyedropper = {}

_TOOL_SYNC = {
    'faidlix_paint.island_view3d': 'faidlix_paint.island_image',
    'faidlix_paint.mask_brush_view3d': 'faidlix_paint.mask_brush_image',
    'faidlix_paint.mask_island_view3d': 'faidlix_paint.mask_island_image',
    'faidlix_paint.mask_lasso_view3d': 'faidlix_paint.mask_lasso_image',
    'faidlix_paint.mask_box_view3d': 'faidlix_paint.mask_box_image',
    'faidlix_paint.mask_circle_view3d': 'faidlix_paint.mask_circle_image',
}
_TOOL_SYNC_REVERSE = {value: key for key, value in _TOOL_SYNC.items()}


def _set_tool_in_area(window, area, tool_id):
    region = next((item for item in area.regions if item.type == 'WINDOW'), None)
    if region is None:
        return
    with bpy.context.temp_override(
            window=window, area=area, region=region, space_data=area.spaces.active):
        try:
            bpy.ops.wm.tool_set_by_id(name=tool_id)
        except RuntimeError:
            pass


def _prepare_mask_brush_colors(context):
    paint = context.tool_settings.image_paint
    brush = paint.brush
    if brush is None:
        return
    ups = paint.unified_paint_settings
    owner = ups if ups.use_unified_color else brush
    owner.color = (0.0, 0.0, 0.0)
    owner.secondary_color = (1.0, 1.0, 1.0)


def _sync_paint_tools():
    if not hasattr(bpy.types.Scene, "faidlix_paint"):
        return None
    for window in bpy.context.window_manager.windows:
        workspace = window.workspace
        key = workspace.as_pointer()
        view_tool = workspace.tools.from_space_view3d_mode('PAINT_TEXTURE', create=False)
        image_tool = workspace.tools.from_space_image_mode('PAINT', create=False)
        view_id = view_tool.idname if view_tool else ""
        image_id = image_tool.idname if image_tool else ""
        previous = _last_tool_state.get(key, (view_id, image_id))
        stable = _last_non_eyedropper.get(key, ('builtin.brush', 'builtin.brush'))

        if ((view_id == 'faidlix_paint.mask_brush_view3d' and view_id != previous[0]) or
                (image_id == 'faidlix_paint.mask_brush_image' and image_id != previous[1])):
            _prepare_mask_brush_colors(bpy.context)

        if view_id == 'faidlix_paint.update_view3d':
            restore = stable[0]
            area = next((item for item in window.screen.areas if item.type == 'VIEW_3D'), None)
            if area:
                _set_tool_in_area(window, area, restore)
                region = next((item for item in area.regions if item.type == 'WINDOW'), None)
                if region:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.faidlix_paint.online_update()
            view_id = restore
        elif image_id == 'faidlix_paint.update_image':
            restore = stable[1]
            area = next((item for item in window.screen.areas
                         if item.type == 'IMAGE_EDITOR' and item.spaces.active.mode == 'PAINT'), None)
            if area:
                _set_tool_in_area(window, area, restore)
                region = next((item for item in area.regions if item.type == 'WINDOW'), None)
                if region:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.faidlix_paint.online_update()
            image_id = restore

        # The bottom eyedropper is a transient command disguised as a toolbar
        # entry. Immediately restore the previous tool, then launch the native
        # Color eyedropper once. This keeps Active Tool and its settings intact.
        if view_id == 'faidlix_paint.eyedropper_view3d':
            restore = stable[0]
            area = next((item for item in window.screen.areas if item.type == 'VIEW_3D'), None)
            if area:
                _set_tool_in_area(window, area, restore)
                region = next((item for item in area.regions if item.type == 'WINDOW'), None)
                if region:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        _invoke_native_eyedropper(bpy.context)
            view_id = restore
        elif image_id == 'faidlix_paint.eyedropper_image':
            restore = stable[1]
            area = next((item for item in window.screen.areas
                         if item.type == 'IMAGE_EDITOR' and item.spaces.active.mode == 'PAINT'), None)
            if area:
                _set_tool_in_area(window, area, restore)
                region = next((item for item in area.regions if item.type == 'WINDOW'), None)
                if region:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        _invoke_native_eyedropper(bpy.context)
            image_id = restore

        if view_id != previous[0] and view_id in _TOOL_SYNC:
            target = _TOOL_SYNC[view_id]
            for area in window.screen.areas:
                if area.type == 'IMAGE_EDITOR' and area.spaces.active.mode == 'PAINT':
                    _set_tool_in_area(window, area, target)
            image_id = target
        elif image_id != previous[1] and image_id in _TOOL_SYNC_REVERSE:
            target = _TOOL_SYNC_REVERSE[image_id]
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    _set_tool_in_area(window, area, target)
            view_id = target
        _last_tool_state[key] = (view_id, image_id)
        _last_non_eyedropper[key] = (
            view_id if view_id and not any(word in view_id for word in ('eyedropper', '.update_')) else stable[0],
            image_id if image_id and not any(word in image_id for word in ('eyedropper', '.update_')) else stable[1],
        )
    return 0.2


def _merge_with_builtin_tool(space_type, context_mode, builtin_id, custom_ids):
    """Place our entries in the built-in Fill flyout (hold-click menu)."""
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper, ToolDef
    toolbar = ToolSelectPanelHelper._tool_class_from_space_type(space_type)
    tools = toolbar._tools[context_mode]
    wanted = set(custom_ids)
    builtin = None
    custom = []
    rebuilt = []
    insert_at = None
    for item in tools:
        entries = (item,) if isinstance(item, ToolDef) else (item if isinstance(item, tuple) else (item,))
        kept = []
        for entry in entries:
            if isinstance(entry, ToolDef) and entry.idname == builtin_id:
                builtin = entry
                if insert_at is None:
                    insert_at = len(rebuilt)
            elif isinstance(entry, ToolDef) and entry.idname in wanted:
                custom.append(entry)
            else:
                kept.append(entry)
        if kept:
            rebuilt.append(tuple(kept) if isinstance(item, tuple) and not isinstance(item, ToolDef) else kept[0])
    if builtin and len(custom) == len(wanted):
        order = {name: index for index, name in enumerate(custom_ids)}
        custom.sort(key=lambda item: order[item.idname])
        rebuilt.insert(insert_at, tuple([builtin] + custom))
        tools[:] = rebuilt
        return True
    return False


def _move_tool_to_top(space_type, context_mode, tool_id):
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper, ToolDef
    toolbar = ToolSelectPanelHelper._tool_class_from_space_type(space_type)
    tools = toolbar._tools[context_mode]
    found = None
    rebuilt = []
    for item in tools:
        if isinstance(item, ToolDef) and item.idname == tool_id:
            found = item
        else:
            rebuilt.append(item)
    if found:
        tools[:] = [found, None] + rebuilt
        return True
    return False


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.faidlix_paint = bpy.props.PointerProperty(type=FAIDLIXPAINT_Properties)
    for tool, options in TOOLS:
        bpy.utils.register_tool(tool, **options)
    _move_tool_to_top('VIEW_3D', 'PAINT_TEXTURE', 'faidlix_paint.update_view3d')
    _move_tool_to_top('IMAGE_EDITOR', 'PAINT', 'faidlix_paint.update_image')
    _merge_with_builtin_tool('VIEW_3D', 'PAINT_TEXTURE', 'builtin_brush.fill', (
        'faidlix_paint.island_view3d',))
    _merge_with_builtin_tool('IMAGE_EDITOR', 'PAINT', 'builtin_brush.fill', (
        'faidlix_paint.island_image',))
    _merge_with_builtin_tool('VIEW_3D', 'PAINT_TEXTURE', 'builtin_brush.mask', (
        'faidlix_paint.mask_brush_view3d', 'faidlix_paint.mask_island_view3d',
        'faidlix_paint.mask_lasso_view3d', 'faidlix_paint.mask_box_view3d',
        'faidlix_paint.mask_circle_view3d'))
    _merge_with_builtin_tool('IMAGE_EDITOR', 'PAINT', 'builtin_brush.mask', (
        'faidlix_paint.mask_brush_image', 'faidlix_paint.mask_island_image',
        'faidlix_paint.mask_lasso_image', 'faidlix_paint.mask_box_image',
        'faidlix_paint.mask_circle_image'))
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig:
        for name, space_type in (("3D View", 'VIEW_3D'), ("Image Paint", 'EMPTY')):
            keymap = keyconfig.keymaps.new(name=name, space_type=space_type)
            item = keymap.keymap_items.new(
                "faidlix_paint.activate_eyedropper", 'C', 'PRESS')
            _addon_keymaps.append((keymap, item))
    if not bpy.app.timers.is_registered(_sync_paint_tools):
        bpy.app.timers.register(_sync_paint_tools, first_interval=0.2, persistent=True)
    _draw_handlers.append((bpy.types.SpaceView3D,
                           bpy.types.SpaceView3D.draw_handler_add(
                               _draw_lasso_preview, (), 'WINDOW', 'POST_PIXEL')))
    _draw_handlers.append((bpy.types.SpaceView3D,
                           bpy.types.SpaceView3D.draw_handler_add(
                               _draw_mask_overlay_3d, (), 'WINDOW', 'POST_VIEW')))
    _draw_handlers.append((bpy.types.SpaceImageEditor,
                           bpy.types.SpaceImageEditor.draw_handler_add(
                               _draw_lasso_preview, (), 'WINDOW', 'POST_PIXEL')))
    _draw_handlers.append((bpy.types.SpaceImageEditor,
                           bpy.types.SpaceImageEditor.draw_handler_add(
                               _draw_mask_overlay_image, (), 'WINDOW', 'POST_PIXEL')))


def unregister():
    _clear_lasso_preview()
    for space_type, handler in reversed(_draw_handlers):
        space_type.draw_handler_remove(handler, 'WINDOW')
    _draw_handlers.clear()
    if bpy.app.timers.is_registered(_sync_paint_tools):
        bpy.app.timers.unregister(_sync_paint_tools)
    _last_tool_state.clear()
    _last_non_eyedropper.clear()
    for keymap, item in reversed(_addon_keymaps):
        keymap.keymap_items.remove(item)
    _addon_keymaps.clear()
    for tool, _options in reversed(TOOLS):
        try:
            bpy.utils.unregister_tool(tool)
        except Exception:
            pass
    del bpy.types.Scene.faidlix_paint
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
