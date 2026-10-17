"""Go/no-go eval. Runs from the repo root with the plain requirements.txt venv.

The app's adapter and contracts aren't pip-installed there, so put their source
folders on the path (uv users get them installed and this is a no-op).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _src in ("apps/api", "packages/contracts"):
    if str(_ROOT / _src) not in sys.path:
        sys.path.append(str(_ROOT / _src))
