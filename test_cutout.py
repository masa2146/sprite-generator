"""cutout tests. Run: python3 test_cutout.py"""
import tempfile
from pathlib import Path

import cutout


def test_iter_pngs_walks_dirs_and_skips_sheets():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in ("beta.png", "alpha.png", "_style.png",
                     "_contact_sheet.png", "notes.txt"):
            (root / name).write_bytes(b"")
        loose = root / "loose.png"

        found = cutout.iter_pngs([root, loose])

        assert [p.name for p in found] == ["alpha.png", "beta.png", "loose.png"], found


if __name__ == "__main__":
    test_iter_pngs_walks_dirs_and_skips_sheets()
    print("ok")
