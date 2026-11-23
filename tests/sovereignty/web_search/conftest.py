import sys
from pathlib import Path

WEB_SEARCH_DIR = Path(__file__).resolve().parents[3] / "services" / "web-search"

if str(WEB_SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_SEARCH_DIR))
