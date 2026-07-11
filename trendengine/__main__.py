"""Enable `python -m trendengine ...` (thin shim over run.py)."""
import sys
from pathlib import Path

# run.py lives at the project root (parent of this package).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
