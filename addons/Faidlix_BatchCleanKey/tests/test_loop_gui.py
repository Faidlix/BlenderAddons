"""Run the current direct loop-toggle GUI regression with Blender --enable-event-simulate --python this_file.py."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('test_loop_toggle_gui.py')),run_name='__main__')
