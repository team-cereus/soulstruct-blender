import sys
import traceback
from pathlib import Path
io = Path(r"S:/_modding/tools/soulstruct-blender/io_soulstruct")
sys.path.insert(0, str(io))
try:
    import importlib
    spec_name = "io_soulstruct_test"
    # emulate addon load by executing __init__
    import runpy
    runpy.run_path(str(io / "__init__.py"), run_name="__main__")
    print("ADDON_LOAD_OK")
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
