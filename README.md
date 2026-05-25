# ffcplugin

Reusable flat-field correction tools for camera-scanned film:

- `ffc-apply`: a standalone raw-to-DNG flat-field correction CLI.
- `lightroom-flatfield.lrplugin`: a Lightroom Classic helper plugin that stages an existing calibration raw as the last selected frame so Lightroom's built-in Flat-Field Correction can use it.

## CLI Quick Start

```sh
uv sync --extra apple --extra dev
uv run ffc-apply "sample scans/correctionimage.ARW" "sample scans" --output corrected --overwrite
```

By default the CLI processes `.ARW` files in the input folder, writes mosaic raw DNGs, and uses a compact lossless DNG compressor when available. It prefers the open-source `dnglab` tool for lossless JPEG DNGs, then falls back to Adobe DNG Converter, then to uncompressed DNGs.

Useful options:

```sh
uv run ffc-apply correctionimage.ARW scans/ --output corrected/
uv run ffc-apply correctionimage.ARW scans/ --include "*.NEF" --include "*.CR3" --recursive
uv run ffc-apply correctionimage.ARW scans/ --backend mlx --compression lossless-jxl
uv run ffc-apply correctionimage.ARW scans/ --compressor dnglab
uv run ffc-apply correctionimage.ARW scans/ --compressor adobe
uv run ffc-apply correctionimage.ARW scans/ --smooth-sigma 0 --compression none
```

Backends:

- `auto`: uses NumExpr when available, otherwise NumPy.
- `numpy`: vectorized NumPy CPU path.
- `numexpr`: multi-threaded native expression evaluation.
- `mlx`: optional Apple Silicon/Metal path for the elementwise correction step.

The raw decode path uses LibRaw through `rawpy`. The default smoothing step uses SciPy's native Gaussian filter once per correction frame, then reuses that gain profile for all scans in the batch.

Optional compact-DNG tools:

```sh
brew install dnglab
```

Adobe DNG Converter is still supported, and is required for `--compression lossless-jxl`.

## Lightroom Plugin Loading

1. In Lightroom Classic, open `File > Plug-in Manager`.
2. Click `Add`.
3. Select the `lightroom-flatfield.lrplugin` folder from this repo.
4. Configure Python and ExifTool paths in the plugin manager if the defaults are not correct.
5. In Library, select the scans for one batch.
6. Run `Library > Plug-in Extras > Stage Flat-Field Calibration Frame...` to use Lightroom's Flat-Field Correction, or `Library > Plug-in Extras > Apply Flat-Field With Python Pipeline...` to run this repo's raw/DNG implementation directly.
7. Pick your reusable calibration raw.
8. For the staging flow, after the plugin imports and selects the staged frame, run `Library > Flat-Field Correction`.

For the Python pipeline menu item, set the plugin's Python command to an environment with the project installed, for example:

```sh
/Users/sdierauf/git/ffcplugin/.venv/bin/python
```

The Python pipeline writes corrected DNGs to a `flatfield-corrected` subfolder next to the selected scans by default, imports them into the catalog, and selects the generated DNGs.

ExifTool is optional but recommended for the Lightroom helper because Lightroom sorts and detects calibration frames more reliably when the duplicate calibration raw has a capture timestamp after the selected batch. Without ExifTool, the helper falls back to changing only filesystem timestamps.

## Notes

- The standalone CLI writes true single-sample CFA mosaic DNGs, not JPEGs and not rendered RGB TIFFs.
- If neither `dnglab` nor Adobe DNG Converter is available, output DNGs are valid but uncompressed and therefore large.
- The CLI preserves the raw mosaic geometry and key DNG color/camera tags. It does not yet clone every proprietary MakerNote, lens, serial, preview, or Lightroom XMP field from the source raw.
- Keep calibration frames matched to the same light source, camera, lens, aperture, focus distance, and scan geometry whenever possible.
