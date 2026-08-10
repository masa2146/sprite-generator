"""Renderer tests. Everything renders at OVERSAMPLE=1 and 32x32 — the point
is to pin behaviour, not to look at anything."""
from pathlib import Path

import numpy as np
from PIL import Image

import sdf3d
from sdf3d import flat, render, sphere

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _small(sdf, **kw):
    """A render small enough to run in a test. OVERSAMPLE is module state, so
    it is set and restored around every call rather than left mutated."""
    before = sdf3d.OVERSAMPLE
    sdf3d.OVERSAMPLE = 1
    try:
        return render(sdf, size=(32, 32), tilt=15, **kw)
    finally:
        sdf3d.OVERSAMPLE = before


def test_the_soft_path_still_renders_exactly_as_it_did():
    """The golden was captured from the renderer as it stood before any of
    this work, with ao and rim off: those two terms are the ones this plan
    deliberately changes, and pinning them would pin the wrong thing. What
    this test protects is the diffuse and specular path — the default ramp
    must reproduce it arithmetic-for-arithmetic."""
    got = _small(sphere(0.7), color=flat((240, 160, 20)), ao=0.0, rim=0.0)
    want = Image.open(FIXTURES / "golden_soft_sphere.png")
    assert np.array_equal(np.asarray(got), np.asarray(want))
