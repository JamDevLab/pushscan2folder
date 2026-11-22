"""Entry point for the PyInstaller build (see .github/workflows/release.yml).

Kept outside the package and not named like it, so PyInstaller's search path
cannot mix up this script with the pushscan2folder package."""
import sys

from pushscan2folder.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
