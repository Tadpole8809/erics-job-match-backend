"""Eric's Job Match backend."""
import sys

# The code uses Python 3.10+ syntax. Fail early with a clear message instead of a confusing error.
if sys.version_info < (3, 10):
    raise RuntimeError(
        f"Eric's Job Match needs Python 3.10 or newer, but this is Python "
        f"{sys.version_info.major}.{sys.version_info.minor}. Install Python 3.12 and recreate "
        "the .venv with it (see README.md, 'Requirements')."
    )
