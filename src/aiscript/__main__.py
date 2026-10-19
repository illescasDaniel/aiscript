"""Allow ``python -m aiscript``."""

import sys

from aiscript.cli import main

if __name__ == "__main__":
    sys.exit(main())
