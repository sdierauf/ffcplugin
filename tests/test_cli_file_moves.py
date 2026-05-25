from __future__ import annotations

from pathlib import Path

from ffc.cli import _default_originals_dir, _default_output_dir, _move_originals


def test_default_paths_are_scan_root_and_originals_subfolder(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()

    assert _default_output_dir(scan_dir) == scan_dir
    assert _default_originals_dir(scan_dir, "originals") == scan_dir / "originals"


def test_move_originals_preserves_relative_paths_and_sidecars(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    nested = scan_dir / "nested"
    nested.mkdir(parents=True)
    raw = nested / "DSC0001.ARW"
    sidecar = nested / "DSC0001.XMP"
    raw.write_bytes(b"raw")
    sidecar.write_text("sidecar", encoding="utf-8")

    moved = _move_originals([raw], scan_dir, scan_dir / "originals")

    assert moved == [scan_dir / "originals" / "nested" / "DSC0001.ARW"]
    assert not raw.exists()
    assert not sidecar.exists()
    assert (scan_dir / "originals" / "nested" / "DSC0001.ARW").read_bytes() == b"raw"
    assert (scan_dir / "originals" / "nested" / "DSC0001.XMP").read_text(encoding="utf-8") == "sidecar"
