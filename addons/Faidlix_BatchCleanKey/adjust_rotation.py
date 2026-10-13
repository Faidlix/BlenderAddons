"""Read-only direction and angle overlay during a native pose rotation."""
import math
import bpy, blf, gpu
from mathutils import Matrix, Vector
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from . import adjust


def update(owner, context, obj):
    owner.rotation_preview = None
    op = next((o for o in context.window.modal_operators if o.bl_idname == 'TRANSFORM_OT_rotate'), None)
    request = owner.request
    if not op or not request or not context.region or context.region.type != 'WINDOW':
        return
    names = request.get('selected', request['times'])
    name = min(names, key=lambda n: len(obj.data.bones[n].parent_recursive))
    delta = adjust.native_deltas(request, obj)[name]
    rotation = delta.to_quaternion().normalized()
    axis, angle = rotation.to_axis_angle()
    constrained = tuple(op.constraint_axis)
    label = '自由軸'
    if any(constrained):
        index = constrained.index(True)
        label = 'XYZ'[index] + ' 軸'
        orient = op.orient_type
        if orient == 'LOCAL':
            basis = Matrix(request['before'][request['active'] or name]).to_quaternion().to_matrix()
        elif orient == 'VIEW':
            basis = context.space_data.region_3d.view_rotation.to_matrix()
        elif orient == 'CURSOR':
            basis = context.scene.cursor.rotation_euler.to_matrix()
        elif orient == 'GLOBAL':
            basis = Matrix.Identity(3)
        else:
            basis = op.orient_matrix.copy()
        axis_reference = basis.col[index].normalized()
        if axis.dot(axis_reference) < 0:
            angle = -angle
        axis = axis_reference
    elif angle >= 1e-6 and max(abs(axis[i]) for i in range(3))>.9999:
        index=max(range(3),key=lambda i:abs(axis[i]))
        if axis[index]<0: angle=-angle
        axis=Vector(tuple(1 if i==index else 0 for i in range(3)))
        label='XYZ'[index]+' 軸（世界）'
    elif angle < 1e-6:
        axis = owner.rotation_track['axis'].copy() if owner.rotation_track else Vector((0, 0, 1))
        label = owner.rotation_track['label'] if owner.rotation_track else '自由軸'
    elif owner.rotation_track and axis.dot(owner.rotation_track['axis']) < 0:
        axis = -axis
        angle = -angle
    # Native RNA retains numeric input including complete turns when available.
    native_angle = float(op.value)
    if abs(native_angle) > 1e-6 and abs(math.remainder(native_angle - angle, 2 * math.pi)) < 1e-3:
        accumulated = native_angle
    else:
        old = owner.rotation_track
        accumulated = angle if not old or old['label'] != label else old['angle'] + math.remainder(angle - old['raw'], 2 * math.pi)
    owner.rotation_track = {'raw': angle, 'angle': accumulated, 'axis': axis.copy(), 'label': label}
    before = {n: Matrix(m) for n, m in request['before'].items()}
    pivot = before[name].translation.copy() if request['pivot']=='INDIVIDUAL_ORIGINS' else adjust.center(before, names, request['pivot'], request['active'], request['cursor'])
    start = before[name].to_quaternion() @ Vector((1, 0, 0))
    start -= axis * start.dot(axis)
    if start.length < 1e-6:
        start = axis.cross(Vector((0, 1, 0)))
        if start.length < 1e-6:
            start = axis.cross(Vector((1, 0, 0)))
    start.normalize()
    owner.rotation_preview = {'pivot': pivot, 'axis': axis, 'start': start, 'angle': accumulated, 'degrees': math.degrees(accumulated), 'label': label}
    owner.area.tag_redraw()


def draw(owner, context):
    data = getattr(owner, 'rotation_preview', None)
    if not data:
        return
    region, view = context.region, context.space_data.region_3d
    pivot, axis, start = data['pivot'], data['axis'], data['start']
    center = view3d_utils.location_3d_to_region_2d(region, view, pivot)
    if center is None:
        return
    scale = context.preferences.system.ui_scale
    radius = (view3d_utils.region_2d_to_location_3d(region, view, center + Vector((85 * scale, 0)), pivot) - pivot).length
    cross = axis.cross(start)
    angle = data['angle']
    # Drawing at most one full circle keeps large numeric angles legible.
    arc_angle = math.copysign(min(abs(angle), 2 * math.pi), angle)
    points = [pivot + radius * (start * math.cos(arc_angle * i / 64) + cross * math.sin(arc_angle * i / 64)) for i in range(65)]
    end = pivot + radius * (start * math.cos(angle) + cross * math.sin(angle))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    previous_width = gpu.state.line_width_get()
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(2 * scale)
    try:
        def line(world_points, color):
            projected = [view3d_utils.location_3d_to_region_2d(region, view, p) for p in world_points]
            if any(p is None for p in projected):
                return
            shader.bind(); shader.uniform_float('color', color)
            batch_for_shader(shader, 'LINE_STRIP', {'pos': projected}).draw(shader)
        line([pivot, points[0]], (.3, .7, 1, 1))
        line([pivot, end], (1, .45, .15, 1))
        line(points, (1, .85, .15, 1))
        blf.size(0, int(14 * scale)); blf.color(0, 1, .9, .35, 1)
        blf.enable(0, blf.SHADOW); blf.shadow(0, 5, 0, 0, 0, 1); blf.shadow_offset(0, 1, -1)
        text = f"{data['label']}：0° → {data['degrees']:+.1f}°"
        blf.position(0, center.x + 12 * scale, center.y - 22 * scale, 0); blf.draw(0, text)
        blf.color(0, .3, .7, 1, 1)
        p = view3d_utils.location_3d_to_region_2d(region, view, points[0])
        if p is not None:
            blf.position(0, p.x + 5, p.y + 5, 0); blf.draw(0, '起始')
        blf.color(0, 1, .45, .15, 1)
        p = view3d_utils.location_3d_to_region_2d(region, view, end)
        if p is not None:
            blf.position(0, p.x + 5, p.y + 5, 0); blf.draw(0, '目前')
        blf.disable(0, blf.SHADOW)
    finally:
        gpu.state.line_width_set(previous_width)
        gpu.state.blend_set('NONE')
