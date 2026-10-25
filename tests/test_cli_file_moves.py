from __future__ import annotations

from pathlib import Path

import pytest

from ffc.cli import _default_originals_dir, _default_output_dir, _discover_inputs, _move_originals, _parser
from ffc.cli import main as cli_main
from ffc.paths import ensure_unique_paths


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


def test_replace_existing_is_the_output_replacement_flag() -> None:
    parser = _parser()

    args = parser.parse_args(["correction.ARW", "scans", "--replace-existing"])

    assert args.replace_existing is True
    with pytest.raises(SystemExit):
        parser.parse_args(["correction.ARW", "scans", "--overwrite"])


def test_discover_inputs_ignores_macos_appledouble_files(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()
    correction = scan_dir / "correction.ARW"
    raw = scan_dir / "DSC0001.ARW"
    apple_double = scan_dir / "._DSC0001.ARW"
    correction.write_bytes(b"correction")
    raw.write_bytes(b"raw")
    apple_double.write_bytes(b"metadata")

    inputs = _discover_inputs(scan_dir, None, False, correction)

    assert inputs == [raw]


def test_discover_inputs_orders_scans_numerically(tmp_path: Path) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()
    correction = scan_dir / "correction.ARW"
    correction.write_bytes(b"correction")
    for name in ["scan10.ARW", "scan2.ARW", "scan1.ARW", "scan20.ARW", "scan3.ARW"]:
        (scan_dir / name).write_bytes(b"raw")

    inputs = _discover_inputs(scan_dir, None, False, correction)

    assert [path.name for path in inputs] == [
        "scan1.ARW",
        "scan2.ARW",
        "scan3.ARW",
        "scan10.ARW",
        "scan20.ARW",
    ]


def test_dry_run_lists_outputs_in_numeric_scan_order(tmp_path: Path, capsys) -> None:
    scan_dir = tmp_path / "roll"
    scan_dir.mkdir()
    correction = tmp_path / "correction.ARW"
    correction.write_bytes(b"correction")
    for name in ["scan10.ARW", "scan2.ARW", "scan1.ARW"]:
        (scan_dir / name).write_bytes(b"raw")

    exit_code = cli_main([str(correction), str(scan_dir), "--dry-run"])

    assert exit_code == 0
    printed = [Path(line).name for line in capsys.readouterr().out.split()]
    assert printed == ["scan1_ffc.dng", "scan2_ffc.dng", "scan10_ffc.dng"]


def test_duplicate_output_paths_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "roll1" / "DSC0001_ffc.dng"
    second = tmp_path / "roll2" / ".." / "roll1" / "DSC0001_ffc.dng"

    with pytest.raises(ValueError, match="same output DNG path"):
        ensure_unique_paths([first, second], "output DNG path")


def test_adobe_converter_runs_sequentially_to_preserve_creation_order(tmp_path: Path, monkeypatch) -> None:
    import ffc.dng as dng

    inputs = [tmp_path / name for name in ("DSC0002.dng", "DSC0010.dng", "DSC0001.dng")]
    for path in inputs:
        path.write_bytes(b"dng")
    output_dir = tmp_path / "out"
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = [str(part) for part in cmd]
        for part in cmd:
            candidate = Path(str(part))
            if candidate.parent != output_dir and candidate.suffix == ".dng":
                (output_dir / candidate.name).write_bytes(b"compressed")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(dng.subprocess, "run", fake_run)

    dng.compress_with_adobe_dng_converter(inputs, output_dir, converter_path=Path("/fake/converter"))

    cmd = captured["cmd"]
    assert "-mp" not in cmd, "multiprocess mode scrambles output creation order"
    converted = [part for part in cmd if part.endswith(".dng")]
    assert [Path(part).name for part in converted] == [path.name for path in inputs]
