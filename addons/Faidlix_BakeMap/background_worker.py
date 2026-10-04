import bpy
import importlib
import importlib.util
import json
import os
import re
import sys
import time
import traceback


ADDON_TAG = "Faidlix_BakeMap"
PASS_PROPERTIES = {
    'Diffuse': 'bake_diffuse',
    'Normal': 'bake_normal',
    'Emit': 'bake_emit',
    'Combined': 'bake_combined',
    'Metallic': 'bake_metallic',
    'Roughness': 'bake_roughness',
}


def read_job(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def write_job(path, job):
    temporary = f"{path}.worker.tmp"
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(job, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def load_addon():
    module_name = "bl_ext.user_default.faidlix_bakemap"
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        module = None
    if not hasattr(bpy.types.Scene, 'faidlix_bakemap'):
        if module is None:
            addon_path = os.path.join(os.path.dirname(__file__), '__init__.py')
            spec = importlib.util.spec_from_file_location("faidlix_bakemap_background", addon_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        module.register()
    return module


def safe_name(value):
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '_', value).strip('._')
    return cleaned or 'BakeMap'


def bake_materials(target):
    return [
        slot.material
        for slot in target.material_slots
        if slot.material and slot.material.get('faidlix_bake_material')
    ]


def restore_snapshot_image_paths(main_file, known_paths=None):
    """A background snapshot lives in Temp, not beside the user's blend."""
    base_dir = os.path.dirname(main_file)
    known_paths = known_paths or {}
    for image in bpy.data.images:
        if image.source != 'FILE' or image.packed_file:
            continue
        path = image.filepath
        if not path.startswith('//'):
            continue
        snapshot_path = bpy.path.abspath(path, library=image.library)
        if os.path.isfile(snapshot_path):
            continue
        original_path = known_paths.get(image.name)
        if not original_path or not os.path.isfile(original_path):
            original_path = os.path.normpath(os.path.join(base_dir, path[2:]))
        if os.path.isfile(original_path):
            image.filepath = original_path
            image.reload()


def save_pass_images(job, target, pass_name):
    results = []
    tag = f"{ADDON_TAG}:{pass_name}"
    for slot_index, slot in enumerate(target.material_slots):
        material = slot.material
        if not material or not material.get('faidlix_bake_material') or not material.use_nodes:
            continue
        material['faidlix_background_job'] = job['job_id']
        node = next(
            (
                item for item in material.node_tree.nodes
                if item.type == 'TEX_IMAGE' and item.get('faidlix_tag') == tag and item.image
            ),
            None,
        )
        if node is None:
            continue
        image = node.image
        desired_image_name = image.get('faidlix_desired_name', image.name)
        filename = safe_name(f"{target.name}_slot{slot_index}_{pass_name}_{job['job_id'][:8]}")
        final_path = os.path.join(job['output_dir'], f"{filename}.png")
        part_path = os.path.join(job['output_dir'], f"{filename}.part.png")
        image.file_format = 'PNG'
        image.filepath_raw = part_path
        image.save()
        os.replace(part_path, final_path)
        loaded = bpy.data.images.load(final_path, check_existing=False)
        loaded.colorspace_settings.name = image.colorspace_settings.name
        node.image = loaded
        if image.users == 0:
            bpy.data.images.remove(image)
        loaded.name = desired_image_name
        loaded['faidlix_bake_image'] = True
        loaded['faidlix_desired_name'] = desired_image_name
        loaded['faidlix_pass_name'] = pass_name
        if image.get('faidlix_intermediate_map'):
            loaded['faidlix_intermediate_map'] = True
        results.append({
            'pass_name': pass_name,
            'material': material.name,
            'target_slot': slot_index,
            'image': loaded.name,
            'desired_image_name': desired_image_name,
            'filepath': final_path,
        })
    if not results:
        raise RuntimeError(f"No baked {pass_name} image was found")
    return results


def main():
    separator = sys.argv.index('--') if '--' in sys.argv else -1
    if separator < 0 or separator + 1 >= len(sys.argv):
        raise RuntimeError("Background job path was not provided")
    job_file = sys.argv[separator + 1]
    job = read_job(job_file)
    try:
        load_addon()
        restore_snapshot_image_paths(job['main_file'], job.get('image_paths'))
        settings = bpy.context.scene.faidlix_bakemap
        target = bpy.data.objects.get(job['target'])
        if not target:
            raise RuntimeError("TargetObject was not found in the scene snapshot")
        job['pid'] = os.getpid()
        job['status'] = 'RUNNING'
        job['message'] = 'Background Blender loaded the scene snapshot'
        write_job(job_file, job)
        for pass_name in job['passes']:
            latest = read_job(job_file)
            if latest.get('cancel_requested') or latest.get('status') == 'CANCEL_REQUESTED':
                job = latest
                job['status'] = 'CANCELLED'
                job['message'] = "Cancellation received between map passes"
                write_job(job_file, job)
                return
            for property_name in PASS_PROPERTIES.values():
                setattr(settings, property_name, False)
            setattr(settings, PASS_PROPERTIES[pass_name], True)
            job = latest
            job['pid'] = os.getpid()
            job['status'] = 'RUNNING'
            job['current_pass'] = pass_name
            job['message'] = f"Baking {pass_name}"
            write_job(job_file, job)
            result = bpy.ops.faidlix.bake()
            if 'FINISHED' not in result:
                raise RuntimeError(f"{pass_name} bake was cancelled")
            pass_results = save_pass_images(job, target, pass_name)
            if pass_name == 'Roughness' and settings.roughness_output == 'METALLIC_ALPHA':
                # Refresh the packed image after Roughness has filled its alpha channel.
                save_pass_images(job, target, 'Metallic')
            known = {
                (item.get('pass_name'), item.get('material'), item.get('target_slot'))
                for item in job.get('results', [])
            }
            for item in pass_results:
                key = (item['pass_name'], item['material'], item['target_slot'])
                if key not in known:
                    job.setdefault('results', []).append(item)
            materials = bake_materials(target)
            job['material_names'] = [material.name for material in materials]
            job['completed'] = int(job.get('completed', 0)) + 1
            job['message'] = f"Completed {pass_name}"
            bpy.ops.wm.save_as_mainfile(filepath=job['bake_file'], check_existing=False)
            write_job(job_file, job)
        job['status'] = 'COMPLETE'
        job['current_pass'] = ''
        job['message'] = f"Completed {job.get('completed', 0)} background map(s)"
        job['finished_at'] = time.time()
        bpy.ops.wm.save_as_mainfile(filepath=job['bake_file'], check_existing=False)
        write_job(job_file, job)
    except Exception as exc:
        job = read_job(job_file)
        job['status'] = 'ERROR'
        job['message'] = str(exc)
        job['traceback'] = traceback.format_exc()
        job['finished_at'] = time.time()
        write_job(job_file, job)


if __name__ == '__main__':
    main()
