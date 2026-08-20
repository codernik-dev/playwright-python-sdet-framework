"""Make the application importable for its own tests.

The application is deliberately not installed as a package (see
``docs/adr/0002-black-box-boundary.md``), so its own tests put its directory on
``sys.path`` here. This is scoped to ``app/tests`` only - the automation framework
never gets this path, and the ruff import ban blocks it regardless.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
