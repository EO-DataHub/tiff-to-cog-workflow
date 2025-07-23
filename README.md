# TIFF to COG CWL Workflow

This repository provides a Common Workflow Language (CWL) workflow for converting a remote TIFF file to a Cloud Optimized GeoTIFF (COG) and generating a STAC catalog, using a custom Python script packaged in a Docker image.

## Overview

- **Input:** URL to a remote TIFF file
- **Output:** A directory (`output_cog`) containing the COG file, a STAC `catalog.json`, and a STAC item JSON
- **Docker Image:** [public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest](https://gallery.ecr.aws/i2j9m5r4/eodh/tif2cog)

## Requirements

- [CWLTool](https://github.com/common-workflow-language/cwltool) or another CWL runner
- Docker (with access to pull from public.ecr.aws)
- Internet/network access (required for downloading remote TIFFs)

## Usage

1. **Run the workflow:**

   ```bash
   cwltool tiff_to_cog.cwl#tiff-to-cog \
     --tiff_url https://example.com/path/to/your.tif
   ```

2. **Outputs:**
   - The workflow will create an `output_cog` directory in the working directory.
   - Inside `output_cog` you will find:
     - The COG file (e.g., `your_cog.tif`)
     - `catalog.json` (STAC catalog)
     - `<item_id>.json` (STAC item)

## Notes

- The workflow uses the Docker image `public.ecr.aws/i2j9m5r4/eodh/tif2cog:latest`.
- Network access is enabled in the workflow to allow downloading remote TIFF files.
- All outputs are written flat into the `output_cog` directory (no subfolders).

## Example Output Structure

```
output_cog/
├── catalog.json
├── your_cog.tif
└── your_cog.json
```

## Troubleshooting

- If you see network errors, ensure your Docker and CWL runner allow network access.
- If you have platform mismatch warnings (e.g., ARM vs AMD), ensure your Docker supports the image architecture or use an appropriate platform flag.
