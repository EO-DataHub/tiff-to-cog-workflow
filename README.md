# TIFF to COG CWL Workflow

This repository provides a Common Workflow Language (CWL) workflow for converting a remote TIFF file to a Cloud Optimized GeoTIFF (COG) and generating a STAC catalog, using a custom Python script packaged in a Docker image.

## Overview

- **Input:** URL to a STAC item JSON file OR a full STAC item as JSON string
- **Output:** A directory (`output_cog`) containing COG files, a STAC `catalog.json`, and a STAC item JSON
- **Docker Image:** [public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest](https://gallery.ecr.aws/i2j9m5r4/eodh/tif2cog)

## Requirements

- [CWLTool](https://github.com/common-workflow-language/cwltool) or another CWL runner
- Docker (with access to pull from public.ecr.aws)
- Internet/network access (required for downloading remote TIFFs)

## Usage

1. **Run the workflow:**

   **Option A: Using a STAC item URL**

   ```bash
   cwltool tiff_to_cog.cwl#tiff-to-cog \
     --stac_item_url https://example.com/path/to/stac_item.json
   ```

   **Option B: Using a full STAC item JSON string**

   ```bash
   cwltool tiff_to_cog.cwl#tiff-to-cog \
     --stac_item '{"type":"Feature","stac_version":"1.0.0",...}'
   ```

   **Note:** You must provide exactly one of `stac_item_url` or `stac_item`, not both.

2. **Outputs:**
   - The workflow will create an `output_cog` directory in the working directory.
   - Inside `output_cog` you will find:
     - COG files (converted from TIFF assets)
     - `catalog.json` (STAC catalog)
     - `<item_id>.json` (STAC item)

## Notes

- The workflow uses the Docker image `public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest`.
- Network access is enabled in the workflow to allow downloading remote TIFF files.
- All outputs are written flat into the `output_cog` directory (no subfolders).

## Example Output Structure

```text
output_cog/
├── catalog.json
├── your_cog.tif
└── your_cog.json
```

## Troubleshooting

- If you see network errors, ensure your Docker and CWL runner allow network access.
- If you have platform mismatch warnings (e.g., ARM vs AMD), ensure your Docker supports the image architecture or use an appropriate platform flag.
