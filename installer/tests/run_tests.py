"""Unit + integration tests for the installer.

Run from anywhere:

    python3 installer/tests/run_tests.py

Uses only the standard library. Tests never touch the real environment: they
pin ``HOME``/``XDG_*`` to temporary directories and spin up a local HTTP server
for download tests.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main() -> int:
    import unittest

    suite = unittest.defaultTestLoader.discover(
        os.path.dirname(os.path.abspath(__file__)), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    # Keep the environment untouched for every test.
    os.environ.setdefault("HOME", "/tmp/installer-test-home")
    os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/installer-test-cfg")
    os.environ.setdefault("XDG_DATA_HOME", "/tmp/installer-test-data")
    sys.exit(main())
