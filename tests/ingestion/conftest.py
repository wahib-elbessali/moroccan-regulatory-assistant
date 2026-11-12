"""Path configuration for ingestion tests."""

import sys
from pathlib import Path

# Ensure repository root is on sys.path so 'tests.ingestion.doubles' can be imported cleanly
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
