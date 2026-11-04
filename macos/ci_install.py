"""CI-only entry: run a package's unchanged setup against an ephemeral profile, without opening a browser."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("distributed_setup", Path(sys.argv[1]) / "setup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.BASE = Path(sys.argv[2])
raise SystemExit(module.main(launch=False))
