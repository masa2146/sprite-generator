"""Tests import the skills' scripts straight from the checkout.

There is no package and no install step, so the path the skills themselves
use at runtime is the path the tests must use too — anything else would
test a copy.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for scripts in (ROOT / ".claude" / "skills" / "sprite-brief" / "scripts",
                ROOT / ".claude" / "skills" / "procedural-sprites" / "scripts"):
    sys.path.insert(0, str(scripts))
