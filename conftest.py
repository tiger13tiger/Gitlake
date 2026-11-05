import sys
from pathlib import Path

# pipelines/ is a flat script directory (matches how the workflow invokes
# them: `python pipelines/bronze_to_silver.py`, which puts that directory
# on sys.path for its sibling import of _runlog) — mirror that here so
# tests can import the same modules the same way.
sys.path.insert(0, str(Path(__file__).parent / "pipelines"))
