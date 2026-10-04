# Faidlix_Outliner

Blender 5.2 Extension for selecting complete object or Collection hierarchies.

## Version 0.2.15 preview

- Object checkbox: affects the object and every descendant.
- Collection checkbox: affects every object in the Collection and nested Collections.
- Scene Collection checkbox: affects every object in the scene and is always available on the top row.
- Armature data checkbox: affects every bone. Armature objects, Collections, and Scene Collection also include their bones.
- Non-object detail rows such as Mesh Data, Modifiers, and Vertex Groups never become checkbox targets.
- Three states: none, partial, and all selected.
- Plain click toggles a hierarchy without clearing unrelated selections.
- Shift-click always adds a hierarchy; Ctrl-click removes it.
- Eye-hidden, viewport-disabled, selection-locked objects, and unavailable bones stay in an add-on logical selection without changing their visibility or lock state.
- Context-menu buttons batch the eye, viewport, selectable, and render restrictions.
- When the clicked hierarchy is fully selected, restriction changes can apply to every selected object.
- Clicking a visible eye/select/viewport/render icon on a fully selected row applies it to all current native and logical selections instead of only the clicked row.
- One `Online Update` button appears in the Outliner header after Search. It syncs the full GitHub extension index and installs only a newer version without requiring a restart.
- Online installation runs after the button operator returns, so the old module is disabled before its files are replaced and Blender can reload the extension safely.
- Internal modules are explicitly reloaded after an in-process update, preventing a new `__init__.py` from calling a stale `core.py` API.
- Updating from a manually installed ZIP migrates the package from `user_default` to the canonical GitHub repository and restores preferences on the new module.
- Registration gives remote repositories priority and disables another enabled local `faidlix_outliner` source before adding UI handlers, preventing doubled or crowded checkbox overlays.
- The add-on adds its own hierarchy-selection toggle column immediately left of Blender's native Restriction Toggles. Blender's Collection Enable and every other native toggle keep their original behavior. Scene Collection, Collections, every object, and Armature data receive the extra Faidlix checkbox.
- A second Faidlix eye column is added beside the hierarchy checkbox. It batches visibility across all current native/logical selections when the clicked object is selected, or across the clicked hierarchy when it is not. Blender's native eye remains untouched and keeps its single-row behavior.
- Both Faidlix columns support native-style press-and-drag painting: the first row determines select/deselect or show/hide, and every newly crossed row receives the same state once.
- Collapsing or expanding invalidates stale row boxes immediately and rebuilds the visible-row cache on the next frame; long empty areas stop being probed early.
- The checkbox uses a dedicated far-left gutter. A fixed gap remains for Animation, Pose, and other mode-specific Outliner icons; confirmed non-target detail rows stop drawing a checkbox.

## Using the preview overlay

The first preview draws a narrow checkbox gutter at the left edge of every Outliner window. Click a box to let Blender identify that row and apply the hierarchy action. A row becomes a live three-state box after its first gutter click. The regular Outliner names, disclosure arrows, and built-in restriction columns retain their normal behavior.

Blender cannot retain native selection on eye-hidden, viewport-disabled, or selection-locked objects. Faidlix_Outliner keeps those objects in its own logical selection set while preserving their visibility and lock states; when they become selectable again, the add-on promotes them to Blender's native selection automatically.

Blender's public Python API does not expose the Outliner's internal visible-row tree or row coordinates. For that reason, 0.2.15 uses fixed custom toggle columns and refreshes its visible-row cache after Outliner clicks. The View Layer root is explicitly mapped to Scene Collection because Blender does not consistently expose an ID for that row. The context-menu commands remain a direct-ID fallback. The legacy distributed update-all panel was removed; only the optional Faidlix Manager owns that UI.

## Install

Download `faidlix_outliner-0.2.15.zip` from the shared repository, or configure this Blender Repository URL:

`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

## Source layout

- `addons/Faidlix_Outliner/`: independent extension source and tests
- `repository/`: shared static Blender Extension repository

