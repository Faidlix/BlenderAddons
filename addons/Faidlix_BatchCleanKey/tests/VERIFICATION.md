# 1.0.0 verification

Blender 5.2.2 LTS, factory-startup isolated processes, 2026-10-09.

- Native Clean, Decimate Ratio/Error and Delete modify selected bone keys across two Actions.
- Unselected bones, similarly prefixed bone names, object channels, Action slots and curve modifiers remain intact.
- Locked curves and unsupported Constant interpolation are skipped.
- Escaped bone names match correctly; ambiguous multi-slot Actions are skipped.
- Injected native failure leaves source keys intact and removes temporary data.
- Operator registration and execution pass. All four editor contexts preserve editor type/mode.
- Ctrl toggle, Shift range, Ctrl+Shift additive range pass selection tests. All-page selection uses the same collection.
- Isolated foreground Delete Undo/Redo passes; popup screenshot inspected.
- Plain row button receives an actual simulated click. Modifier callbacks tested with explicit event objects because Blender synthetic UI clicks did not propagate modifier state to the button's invocation event; physical Ctrl/Shift input has not been automated.

The user's working blend file is never used as a test fixture.
