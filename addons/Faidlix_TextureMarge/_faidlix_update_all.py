import bpy
from bpy.types import Operator, Panel


UPDATERS = (
    ("texture_merge", "ftm.online_update"),
    ("retarget_motion", "fbr.online_update"),
    ("bakemap", "faidlix.online_update"),
    ("fbx_zip", "export_scene.fbx_zip_online_update"),
    ("outliner", "faidlix_outliner.online_update"),
    ("weight", "faidlix_weight.online_update"),
    ("paint", "faidlix_paint.online_update"),
)
PANEL_PROVIDERS = (
    ("texture_merge", "FAIDLIX_PT_update_all_TextureMerge"),
    ("retarget_motion", "FAIDLIX_PT_update_all_RetargetMotion"),
    ("bakemap", "FAIDLIX_PT_update_all_BakeMap"),
    ("fbx_zip", "FAIDLIX_PT_update_all_FBXZip"),
    ("outliner", "FAIDLIX_PT_update_all_Outliner"),
    ("weight", "FAIDLIX_PT_update_all_Weight"),
    ("paint", "FAIDLIX_PT_update_all_Paint"),
)
STATE_KEY = "_faidlix_update_all_state"
RESTORE_DELAY_SECONDS = 1.0


def _operator(idname):
    namespace, name = idname.split(".", 1)
    group = getattr(bpy.ops, namespace, None)
    if group is None or name not in dir(group):
        return None
    return getattr(group, name)


def available_updaters():
    return [(key, idname) for key, idname in UPDATERS if _operator(idname) is not None]


def available_panel_owners():
    owners = []
    for key, class_name in PANEL_PROVIDERS:
        panel_class = getattr(bpy.types, class_name, None)
        if panel_class and getattr(panel_class, "faidlix_update_all_protocol", 0) >= 2:
            owners.append(key)
    return owners


def _state():
    return bpy.app.driver_namespace.setdefault(
        STATE_KEY, {"running": False, "done": 0, "total": 0, "errors": 0}
    )


def _tag_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def _restore_button_text():
    state = _state()
    state.update(running=False, done=0, total=0, errors=0)
    _tag_redraw()
    return None


def make_classes(owner_key, class_token):
    operator_id = f"faidlix.update_all_{class_token.lower()}"

    class FAIDLIX_OT_update_all(Operator):
        bl_idname = operator_id
        bl_label = "全部更新"
        bl_description = "依序檢查並更新所有已安裝、支援聯網更新的 Faidlix 外掛"
        bl_options = {"INTERNAL"}

        @classmethod
        def poll(cls, _context):
            return len(available_updaters()) >= 2 and not _state()["running"]

        def execute(self, context):
            if not getattr(bpy.app, "online_access", False):
                self.report({"ERROR"}, "請先在偏好設定 > 系統開啟 Allow Online Access")
                return {"CANCELLED"}

            items = available_updaters()
            items.sort(key=lambda item: item[0] == owner_key)
            state = _state()
            state.update(running=True, done=0, total=len(items), errors=0)

            def run_next():
                state = _state()
                if not items:
                    state["running"] = False
                    _tag_redraw()
                    bpy.app.timers.register(
                        _restore_button_text,
                        first_interval=RESTORE_DELAY_SECONDS,
                    )
                    return None

                _key, idname = items.pop(0)
                op = _operator(idname)
                try:
                    if op is None or not op.poll():
                        raise RuntimeError("目前狀態無法執行")
                    result = op("EXEC_DEFAULT")
                    if "CANCELLED" in result:
                        raise RuntimeError("更新被取消")
                except Exception as exc:
                    state["errors"] += 1
                    print(f"Faidlix 全部更新：{idname} 失敗：{exc}")
                state["done"] += 1
                _tag_redraw()
                return 1.5

            bpy.app.timers.register(run_next, first_interval=0.1)
            self.report({"INFO"}, f"開始更新 {len(items)} 個 Faidlix 外掛")
            return {"FINISHED"}

    FAIDLIX_OT_update_all.__name__ = f"FAIDLIX_OT_update_all_{class_token}"

    class FAIDLIX_PT_update_all(Panel):
        bl_label = "Faidlix 全部更新"
        bl_idname = f"FAIDLIX_PT_update_all_{class_token}"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Faidlix"
        bl_order = -100
        bl_options = {"HIDE_HEADER"}
        faidlix_update_all_protocol = 2

        @classmethod
        def poll(cls, _context):
            items = available_updaters()
            panel_owners = available_panel_owners()
            return len(items) >= 2 and bool(panel_owners) and panel_owners[0] == owner_key

        def draw(self, _context):
            state = _state()
            row = self.layout.row(align=True)
            if state["running"]:
                row.enabled = False
                row.operator(
                    operator_id,
                    text=f"全部更新（{state['done']}/{state['total']}）",
                    icon="FILE_REFRESH",
                )
            elif state["total"] and state["done"] == state["total"]:
                suffix = f"，{state['errors']} 個失敗" if state["errors"] else ""
                row.operator(operator_id, text=f"全部更新完成{suffix}", icon="CHECKMARK")
            else:
                row.operator(operator_id, text="全部更新", icon="FILE_REFRESH")

    FAIDLIX_PT_update_all.__name__ = f"FAIDLIX_PT_update_all_{class_token}"
    return FAIDLIX_OT_update_all, FAIDLIX_PT_update_all
