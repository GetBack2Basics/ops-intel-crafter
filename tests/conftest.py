"""Test bootstrap: guarantee project root and tests dir are importable."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

for path in (str(PROJECT_ROOT), str(TESTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)
