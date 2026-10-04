import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PANELS = {
    "addons/Faidlix_Manager/__init__.py": "FAIDLIXMANAGER_PT_update_all",
    "addons/Faidlix_TextureMarge/__init__.py": "FTM_PT_panel",
    "addons/Faidlix_BakeMap/__init__.py": "FAIDLIX_PT_bakemap",
    "addons/Faidlix_BoneRemap/ui.py": "FBR_PT_main",
    "addons/Faidlix_FBXZip/__init__.py": "FBXZIP_PT_panel",
}


def _class_node(relative_path, class_name):
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative_path)
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def test_sidebar_panels_put_version_at_the_right_edge():
    for relative_path, class_name in PANELS.items():
        panel = _class_node(relative_path, class_name)
        methods = {
            node.name: node
            for node in panel.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "draw_header_preset" in methods, relative_path
        assert "draw_header" not in methods, relative_path

        source = ast.unparse(methods["draw_header_preset"])
        assert "ADDON_VERSION" in source, relative_path
        assert "alignment = 'RIGHT'" in source, relative_path


def test_sidebar_panel_names_do_not_embed_versions():
    for relative_path, class_name in PANELS.items():
        panel = _class_node(relative_path, class_name)
        label = next(
            node
            for node in panel.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "bl_label" for target in node.targets)
        )
        text = ast.literal_eval(label.value)
        assert " v" not in text.lower(), relative_path
        assert "·" not in text, relative_path


def test_manager_panel_keeps_its_header_visible():
    panel = _class_node(
        "addons/Faidlix_Manager/__init__.py",
        "FAIDLIXMANAGER_PT_update_all",
    )
    options = next(
        node
        for node in panel.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "bl_options" for target in node.targets)
    )
    assert ast.literal_eval(options.value) == {"DEFAULT_CLOSED"}
