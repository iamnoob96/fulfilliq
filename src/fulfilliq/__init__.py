"""FulfillIQ: a local, reproducible logistics data foundation."""

import os

# Bound worker discovery on local machines, including restricted macOS environments.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "2")

__version__ = "0.1.0"
