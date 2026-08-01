"""cutout tests. Run: python3 -m pytest tests/test_cutout.py"""
import tempfile
from pathlib import Path

from spritegen import cutout


def test_iter_pngs_walks_dirs_and_skips_sheets():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("beta.png", "alpha.png", "_style.png",
                     "_contact_sheet.png", "notes.txt"):
            (root / name).write_bytes(b"")
        loose = root / "loose.png"

        found = cutout.iter_pngs([root, loose])

        assert [p.name for p in found] == ["alpha.png", "beta.png", "loose.png"], found

