"""Entry point for ``python -m installer`` and the global shim."""

import os
import sys

# Allow ``python3 <src>/installer/__main__.py`` to work without the parent
# being on sys.path (the installed global shim relies on this).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
