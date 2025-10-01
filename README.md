# TIFF to COG CWL Workflow

This repository provides a Common Workflow Language (CWL) workflow for converting a remote TIFF file to a Cloud Optimized GeoTIFF (COG) and generating a STAC catalog, using a custom Python script packaged in a Docker image.

## Overview

- **Input:** URL to a remote TIFF file (HTTP/HTTPS/S3 URLs supported)
- **Output:** A directory (`output_cog`) containing the COG file, a STAC `catalog.json`, and a STAC item JSON with real metadata extracted from the GeoTIFF
- **Docker Image:** [public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest](https://gallery.ecr.aws/i2j9m5r4/eodh/tif2cog)
- **Features:**
  - Comprehensive input validation with SSRF protection
  - Support for custom GDAL options for COG conversion
  - Real metadata extraction for STAC catalogs
  - Modular, type-safe Python implementation using rasterio

## Requirements

- [CWLTool](https://github.com/common-workflow-language/cwltool) or another CWL runner
- Docker (with access to pull from public.ecr.aws)
- Internet/network access (required for downloading remote TIFFs)

## Usage

1. **Basic usage:**

   ```bash
   cwltool tiff_to_cog.cwl#tiff-to-cog \
     --tiff_url https://example.com/path/to/your.tif
   ```

2. **With custom GDAL options:**

   ```bash
   cwltool tiff_to_cog.cwl#tiff-to-cog \
     --tiff_url https://example.com/path/to/your.tif \
     --gdal_options '{"COMPRESS":"ZSTD","BLOCKSIZE":"1024","OVERVIEW_RESAMPLING":"BILINEAR"}'
   ```

3. **Outputs:**
   - The workflow will create an `output_cog` directory in the working directory.
   - Inside `output_cog` you will find:
     - The COG file (e.g., `your_cog.tif`)
     - `catalog.json` (STAC catalog)
     - `<item_id>.json` (STAC item)

## Configuration

### GDAL Options

The workflow supports custom GDAL options for COG conversion. If not specified, it uses these defaults:

- `COMPRESS=LZW`
- `BLOCKSIZE=512`
- `OVERVIEW_RESAMPLING=NEAREST`

Common GDAL options you can customize:

- `COMPRESS`: Compression method (`LZW`, `ZSTD`, `DEFLATE`, `LZ4`)
- `BLOCKSIZE`: Internal tile size (e.g., `512`, `1024`, `2048`)
- `OVERVIEW_RESAMPLING`: Overview resampling method (`NEAREST`, `BILINEAR`, `CUBIC`)
- `TILED`: Enable tiling (`YES`/`NO`)

### Input Validation

The workflow includes comprehensive input validation:

- **URL Scheme Validation**: Only HTTP, HTTPS, and S3 URLs are allowed
- **SSRF Protection**: Blocks access to localhost and private IP ranges
- **File Size Limits**: Maximum file size of 10GB
- **File Type Validation**: Validates TIFF magic bytes
- **Extension Validation**: Checks for valid TIFF file extensions (`.tif`, `.tiff`, `.gtiff`, `.geotiff`)

## Notes

- The workflow uses the Docker image `public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest`.
- Network access is enabled in the workflow to allow downloading remote TIFF files.
- All outputs are written flat into the `output_cog` directory (no subfolders).
- The STAC catalog now includes real metadata extracted from the GeoTIFF files.
- The implementation uses rasterio instead of GDAL CLI for better Python integration.

## Example Output Structure

```
output_cog/
├── catalog.json
├── your_cog.tif
└── your_cog.json
```

## Troubleshooting

### Common Issues

- **Network errors**: Ensure your Docker and CWL runner allow network access.
- **Platform mismatch warnings**: If you see ARM vs AMD warnings, ensure your Docker supports the image architecture or use an appropriate platform flag.
- **Validation errors**: Check that your input URL uses an allowed scheme (HTTP/HTTPS/S3) and doesn't point to localhost or private IP ranges.
- **File size errors**: Ensure your TIFF file is under 10GB.
- **GDAL options errors**: Verify that your GDAL options are valid JSON format and use supported parameter names.

### Error Messages

The workflow provides detailed error messages for common issues:

- `Input validation failed`: URL scheme not allowed or SSRF protection triggered
- `Downloaded file validation failed`: File doesn't appear to be a valid TIFF
- `Invalid GDAL options`: Malformed JSON or unsupported GDAL parameters
- `S3 error`: AWS credentials missing or insufficient permissions for S3 access
