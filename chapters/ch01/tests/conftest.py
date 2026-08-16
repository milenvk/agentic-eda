import sys
from pathlib import Path

# The demo script lives in the chapter directory, not in a package.
sys.path.insert(0, str(Path(__file__).parent.parent))
