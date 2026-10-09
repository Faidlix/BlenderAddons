# 1.1.0 verification

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

1.1.0 additions:
- Bidirectional pose-bone checkbox selection and per-Action key counts pass.
- Action switch/current highlight, new/delete, independent duplicate and mirrored copy pass.
- Euler/Quaternion/Axis-Angle curve mirror signs, center bones, missing-pair preservation and double-flip identity pass.
- Actual fractional frame ranges update without changing keys; empty Actions skip.
- Generator progress and cancellation preserve sources and remove scratch data.
- Isolated foreground modal Clean across 25 Actions / 1000 curves passes native Undo/Redo, without manual after-operation undo push.
- Expanded bone/Action scroll lists and visible progress overlay screenshots inspected.
- Real synthetic Esc event cancels the modal operation, restores scratch data and preserves original keys.
