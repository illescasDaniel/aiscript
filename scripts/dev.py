"""Run aiscript from this checkout with a throwaway config in ./.dev (gitignored).

Use through taskipy: `uv run task dev --init`, `uv run task dev sizes ~/Downloads`.
Set AISCRIPT_HOME yourself to use another folder.
"""

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env = {**os.environ}
env.setdefault("AISCRIPT_HOME", str(root / ".dev"))
sys.exit(subprocess.call([sys.executable, "-m", "aiscript", *sys.argv[1:]], env=env))
