"""Convenience passthrough so `python main.py` runs the app.
This is also the PyInstaller entry script — using absolute imports here
avoids the "relative import with no known parent package" failure that
occurs when src/wispr_clone/main.py is treated as a top-level script.

The canonical entrypoint is `python -m wispr_clone.main` or the
`wispr-clone` console script declared in pyproject.toml.
"""
import sys

from wispr_clone.main import main

if __name__ == "__main__":
    sys.exit(main())
