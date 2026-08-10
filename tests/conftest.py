"""Tests import the skill's scripts straight from the checkout.

There is no package and no install step any more, so the path the skill
itself uses at runtime is the path the tests must use too — anything else
would test a copy.
"""
import sys
from pathlib import Path

SCRIPTS = (Path(__file__).resolve().parent.parent
           / ".claude" / "skills" / "sprite-brief" / "scripts")
sys.path.insert(0, str(SCRIPTS))
