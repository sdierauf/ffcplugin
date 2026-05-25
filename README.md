# ffcplugin

Raw flat-field correction tools for camera-scanned film.

This repo contains two related workflows:

- `ffc-apply`: a standalone CLI that applies a reusable flat-field raw to a folder of scan raws and writes true mosaic DNGs.
- `lightroom-flatfield.lrplugin`: a Lightroom Classic plugin with two commands:
  - stage an existing calibration raw so Lightroom Classic's built-in `Library > Flat-Field Correction` can use it;
  - run this repo's Python raw/DNG pipeline directly from Lightroom, including a crop-aware mode for masked backlight frames.

## Prerequisites

Install the normal macOS command-line dependencies with Homebrew:

```sh
brew install uv dnglab exiftool
```

Optional: install Adobe DNG Converter if you want Adobe's DNG compressor or `--compression lossless-jxl`:

```sh
brew install --cask adobe-dng-converter
```

Then create the Python environment:

```sh
uv sync --extra apple --extra dev
```

The `apple` extra installs MLX for the optional Apple Silicon backend. The default backend uses NumExpr when available.

## Standalone CLI

Run flat-field correction on a scan folder:

```sh
uv run ffc-apply "sample scans/correctionimage.ARW" "sample scans" --overwrite
```

Default behavior:

- reads `.ARW` files in the input folder;
- excludes the correction raw itself;
- writes corrected DNGs into the scan folder root with an `_ffc.dng` suffix;
- moves the source raws, and matching `.xmp` / `.XMP` sidecars, into `originals/` after successful DNG creation;
- prefers `dnglab` for compact lossless JPEG DNGs, then Adobe DNG Converter, then uncompressed DNGs.

Useful options:

```sh
uv run ffc-apply correctionimage.ARW scans/ --keep-originals
uv run ffc-apply correctionimage.ARW scans/ --output corrected/
uv run ffc-apply correctionimage.ARW scans/ --originals-dir raw-originals
uv run ffc-apply correctionimage.ARW scans/ --include "*.NEF" --include "*.CR3" --recursive
uv run ffc-apply correctionimage.ARW scans/ --backend mlx --compression lossless-jxl
uv run ffc-apply correctionimage.ARW scans/ --compressor dnglab
uv run ffc-apply correctionimage.ARW scans/ --compressor adobe
uv run ffc-apply correctionimage.ARW scans/ --smooth-sigma 0 --compression none
uv run ffc-apply correctionimage.ARW scans/ --norm-percentile 50
```

Backends:

- `auto`: uses NumExpr when available, otherwise NumPy.
- `numpy`: vectorized NumPy CPU path.
- `numexpr`: multi-threaded native expression evaluation.
- `mlx`: optional Apple Silicon/Metal path for the elementwise correction step.

## Lightroom Plugin

Load the plugin:

1. In Lightroom Classic, open `File > Plug-in Manager`.
2. Click `Add`.
3. Select the `lightroom-flatfield.lrplugin` folder from this repo.
4. Click `Configure...` in the plugin panel.
5. Set `Python command/path` to this repo's environment, for example:

```sh
/Users/sdierauf/git/ffcplugin/.venv/bin/python
```

The plugin has three Library menu commands under `Library > Plug-in Extras`:

- `Stage Flat-Field Calibration Frame...`
- `Apply Flat-Field With Python Pipeline...`
- `Configure Flat-Field Stager...`

### Stage For Lightroom FFC

Use this when you want Lightroom Classic's built-in correction.

1. Select the scans in Library.
2. Run `Library > Plug-in Extras > Stage Flat-Field Calibration Frame...`.
3. Pick an existing calibration raw from disk.
4. The plugin copies that raw beside the selected batch, timestamps it after the latest selected photo when ExifTool is available, imports it, and selects the scans plus the staged calibration frame.
5. Run Lightroom's `Library > Flat-Field Correction`.

ExifTool is optional but recommended for this staging workflow because Lightroom's built-in FFC is sensitive to capture order.

### Run The Python Pipeline

Use this when you want this repo's raw/DNG implementation from inside Lightroom.

1. Select the scans in Library.
2. Run `Library > Plug-in Extras > Apply Flat-Field With Python Pipeline...`.
3. Choose a calibration source:
   - `Use Active Photo` uses the active selected Lightroom photo as the calibration frame and removes it from the scan list.
   - `Choose File` picks an uncataloged raw from disk.
4. The plugin writes corrected DNGs to a `flatfield-corrected/` subfolder next to the selected scans, imports them into Lightroom, and selects the generated DNGs.

This Lightroom command does not move already-imported source raws; moving them would make Lightroom catalog entries go missing. The standalone CLI is the workflow that archives source raws into `originals/`.

### Crop-Aware Masked Calibration

Use this when the flat-field image still contains the film holder or mask.

1. Import the negatives and the masked backlight/flat-field image.
2. Apply the same Lightroom crop to the negatives and the flat-field image so the mask is outside the visible crop.
3. Select the negatives plus the flat-field image.
4. Make the flat-field image the active selected photo.
5. Run `Library > Plug-in Extras > Apply Flat-Field With Python Pipeline...`.
6. Choose `Use Active Photo`.

The helper reads Lightroom's `CropLeft`, `CropTop`, `CropRight`, `CropBottom`, and `CropAngle` develop settings. It builds the flat-field gain map from the actual Lightroom crop polygon, so straightened crops can exclude a mask even when the uncropped raw still contains it.

Corrected DNGs receive an axis-aligned default crop that bounds the selected Lightroom crop. When run from Lightroom, the plugin also reapplies adjusted crop settings to the imported DNGs so the catalog view keeps the same rotated crop.

## Output Notes

- The CLI and Python plugin workflow write true single-sample CFA mosaic DNGs, not JPEGs and not rendered RGB TIFFs.
- The raw decode path uses LibRaw through `rawpy`.
- The flat-field profile is built per CFA phase from black-subtracted raw values; smoothing is done once per correction frame.
- The default smoothing sigma is `192` full-resolution pixels. Use `--smooth-sigma 96` for the previous default or `--smooth-sigma 0` to disable smoothing.
- The default flat-field normalization uses the 70th percentile of the smoothed correction frame. On the sample set, this is closer to Lightroom Classic's output than median normalization. Use `--norm-percentile 50` for the previous median behavior.
- If neither `dnglab` nor Adobe DNG Converter is available, output DNGs are valid but uncompressed and therefore large.
- The DNG writer preserves raw mosaic geometry and key DNG color/camera tags. It does not yet clone every proprietary MakerNote, lens, serial, preview, Lightroom XMP, or all EXIF sub-IFDs from the source raw.
- Keep calibration frames matched to the same light source, camera, lens, aperture, focus distance, and scan geometry whenever possible.
