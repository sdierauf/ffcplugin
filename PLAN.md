# Flat-Field Correction Plugin And CLI Plan

## Background

Lightroom Classic's built-in Flat-Field Correction is intended to correct shading, vignetting, and spatial color cast using a calibration frame made with the same optical setup. Adobe documents the workflow as selecting regular images and calibration frames in a natural interleaved order, then running `Library > Flat-Field Correction`; Lightroom automatically detects the calibration frames and converts corrected files to DNG. Adobe also states that the first or last selected photo must be a flat-field calibration frame.

That requirement is awkward for film scanning because a reusable backlight calibration frame is often independent of a roll. The practical workaround is to stage a duplicate of a known-good calibration raw into the current batch so Lightroom sees the calibration as the last image in the selected set.

## Research Notes

- Adobe Flat-Field Correction docs: `https://helpx.adobe.com/lightroom-classic/help/flat-field-correction.html`
  - Calibration frames should match the optical configuration.
  - Lightroom expects calibration frames interleaved with regular images.
  - The first or last selected photo must be a calibration frame.
  - Results are converted to DNG.
- Adobe Lightroom Classic SDK overview: `https://developer.adobe.com/lightroom-classic/`
  - Lightroom Classic plugins are Lua plugins.
  - Plugins can add menu items, display dialogs, work with metadata, and run external processes.
- Adobe Camera Raw XMP namespace: `https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/`
  - Adobe stores crop geometry in `CropLeft`, `CropTop`, `CropBottom`, `CropRight`, and `CropAngle` fields.
- Lightroom SDK crop-geometry discussion: `https://community.adobe.com/t5/lightroom-classic-discussions/sdk-computing-the-corners-of-a-crop-rectangle/m-p/12995794`
  - Lightroom crop coordinates are normalized in a top-left coordinate system, and `CropAngle` rotates the crop rectangle around its center.
- Lightroom SDK catalog import API reference mirror: `https://archive.stecman.co.nz/files/docs/lightroom-sdk/API-Reference/modules/LrCatalog.html`
  - `catalog:addPhoto(path, stackWithPhoto, position)` can add a staged calibration file to the active catalog from a plugin write-access gate.
- Adobe DNG Converter command-line documentation: `https://community.adobe.com/havfw69955/attachments/havfw69955/camera-raw/23452/1/DNG%20Converter%20Command%20Line.pdf`
  - The converter supports lossless compressed mosaic DNG output with `-c`, lossless JPEG XL with `-losslessJXL`, output directories with `-d`, and parallel conversion with `-mp`.
- Local sample inspection:
  - Camera: Sony ILCE-7RM4A.
  - Raw payload: `9600 x 6376`, default crop `9504 x 6336` at `(32, 20)`.
  - CFA: RGGB, black level `512`, white level `16383`.
  - Lightroom's output DNGs preserve mosaic raw data in a full-size CFA SubIFD using lossless JPEG compression.
  - A simple uncompressed mosaic DNG written with DNG tags is readable by LibRaw/rawpy; Adobe DNG Converter can recompress it to a Lightroom-style lossless DNG.

## Lightroom Plugin Plan

1. Add a Lightroom Classic Lua plugin in `lightroom-flatfield.lrplugin`.
2. Provide a Library Plug-in Extras menu item to stage a reusable calibration frame.
3. Read the current selected photos, find the latest selected capture time, and choose a destination folder beside the selected batch.
4. Ask for the existing flat-field raw image.
5. Copy the calibration raw to a new filename that sorts after the selected scans.
6. Use a helper script and ExifTool when available to rewrite only date/time metadata on the copied calibration frame so Lightroom sees it after the batch. Fall back to filesystem modification time if ExifTool is unavailable.
7. Import the staged calibration file with `catalog:addPhoto`.
8. Select the original scans plus the staged calibration photo, then instruct the user to run Lightroom's built-in `Library > Flat-Field Correction`.

The SDK does not document a way for plugins to invoke Lightroom's built-in Flat-Field Correction command directly, so the plugin stages and selects the batch rather than trying to automate that private command.

## Standalone CLI Plan

1. Build a Python package with a `ffc-apply` command.
2. Use `rawpy`/LibRaw to decode source raw files and the calibration frame into the original CFA mosaic.
3. Compute a per-CFA-phase flat-field gain profile from the black-subtracted calibration frame.
4. Smooth the calibration profile with SciPy's native Gaussian filter by default to avoid baking sensor/calibration noise into every scan.
5. Apply correction on black-subtracted raw values per CFA phase, add black level back, clamp to white level, and preserve the original mosaic geometry.
6. Write a standards-oriented mosaic DNG with `tifffile`, preserving core DNG tags: CFA pattern, black/white level, crop, color matrix, camera model, white balance, and timestamp.
7. If Adobe DNG Converter is available, recompress the intermediate uncompressed DNGs to lossless compressed mosaic DNGs using the converter's native implementation. Otherwise, keep valid uncompressed DNGs.
8. Use native/vectorized acceleration:
   - LibRaw via `rawpy` for raw decoding.
   - NumPy for vectorized memory-bandwidth-bound array math.
   - NumExpr when requested/available for multi-threaded elementwise correction.
   - Optional MLX backend on Apple Silicon for Metal-accelerated elementwise correction.

## Validation Plan

1. Unit-test the correction math on small synthetic CFA mosaics.
2. Run the CLI on one sample ARW with `correctionimage.ARW`.
3. Verify the output DNG is readable by rawpy/LibRaw and has the expected CFA geometry, black level, white level, and crop.
4. Verify Adobe DNG Converter recompression succeeds when present.
5. Keep sample raw/DNG files out of git because the folder is several gigabytes.

## Implementation Status

- Lightroom plugin: implemented in `lightroom-flatfield.lrplugin`.
- Lightroom staging helper: implemented in `scripts/stage_calibration.py`.
- Lightroom Python-pipeline helper: implemented in `scripts/run_ffc_apply.py` and exposed as `Library > Plug-in Extras > Apply Flat-Field With Python Pipeline...`.
- Crop-aware Python pipeline: when the calibration frame is the active Lightroom selection, the plugin passes Lightroom crop metadata to the helper so masks outside the crop are excluded from the flat-field gain map. Rotated/straightened Lightroom crops are modeled as polygon masks, and adjusted crop settings are reapplied to imported DNGs from the Lightroom plugin.
- Standalone CLI: implemented as `ffc-apply` in `src/ffc`.
- CLI DNG path: writes uncompressed CFA DNGs directly, then uses open-source `dnglab` or Adobe DNG Converter for lossless compressed mosaic DNGs when available.
- Acceleration path: LibRaw/rawpy decode, SciPy native smoothing, precomputed per-CFA gain maps, NumPy/NumExpr correction by default, optional MLX backend on Apple Silicon.
- Lightroom matching: the correction profile now defaults to 70th-percentile flat-field normalization and a 192 px smoothing sigma, which reduced mean raw-mosaic difference from Lightroom's sample DNGs from about 28.9 DN to about 21.0 DN while keeping dark film-mask/rebate regions effectively unchanged.
- Metadata path: preserves core DNG raw geometry, camera identity, color matrices, white balance, black/white level, default crop, original file name, and capture timestamp/mtime. It does not yet fully clone proprietary MakerNotes, lens serial data, previews, Lightroom XMP, or all EXIF sub-IFDs.
