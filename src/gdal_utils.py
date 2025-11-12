"""GDAL utilities for TIFF to COG conversion."""

import json
import logging
import os
import shutil
import tempfile
import requests
from pathlib import Path
from typing import Dict

from chunking_utils import (
    calculate_chunk_size,
    create_chunks,
    process_chunk,
    create_output_cog_dataset,
)
import rasterio
from rasterio.enums import Resampling
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles


def get_raster_metadata(file_path: str) -> Dict:
    """Get raster metadata from a TIFF file.

    Reads raster metadata using rasterio to get dimensions, bands, and data type.
    This is a simplified version that just extracts metadata without complex memory calculations.

    Args:
        file_path: Path or URL to the TIFF file

    Returns:
        Dictionary with keys:
        - width (int): Raster width in pixels
        - height (int): Raster height in pixels
        - bands (int): Number of bands
        - data_type (str): Data type (e.g., "uint8", "float32")
        - bytes_per_pixel (int): Bytes per pixel
        - crs: CRS object
        - transform: Transform object

    Raises:
        ValueError: If file_path is invalid or file cannot be accessed
        RuntimeError: If raster metadata cannot be read
    """
    # Data type to bytes per pixel mapping
    dtype_to_bytes = {
        "uint8": 1,
        "int8": 1,
        "uint16": 2,
        "int16": 2,
        "uint32": 4,
        "int32": 4,
        "float32": 4,
        "float64": 8,
        "complex64": 8,
        "complex128": 16,
    }

    try:
        # Open raster file to read metadata
        # Handle remote URLs by using /vsicurl/ prefix if needed
        if file_path.startswith(("http://", "https://")):
            input_path = f"/vsicurl/{file_path}"
        else:
            input_path = file_path

        with rasterio.open(input_path) as src:
            width = src.width
            height = src.height
            bands = src.count
            data_type = str(src.dtypes[0])  # Assume all bands have same dtype
            crs = src.crs
            transform = src.transform

            # Get bytes per pixel from data type
            bytes_per_pixel = dtype_to_bytes.get(
                data_type, 4
            )  # Default to 4 bytes if unknown

            return {
                "width": width,
                "height": height,
                "bands": bands,
                "data_type": data_type,
                "bytes_per_pixel": bytes_per_pixel,
                "crs": crs,  # Keep as CRS object for rasterio compatibility
                "transform": transform,  # Keep as Affine object for rasterio compatibility
            }

    except rasterio.errors.RasterioIOError as e:
        error_msg = f"Failed to open raster file {file_path}: {e}"
        logging.error(error_msg)
        raise ValueError(error_msg) from e
    except Exception as e:
        error_msg = f"Failed to read raster metadata from {file_path}: {e}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def run_gdal_translate_chunked(
    tiff_path: str,
    output_path: str,
) -> None:
    """Convert a TIFF file to COG format using chunked processing.

    Processes the file in chunks using rasterio windowed reading and writing
    to avoid loading the entire file into memory. Uses default GDAL options.
    Then reorganizes the file into proper COG-compliant structure using rio-cogeo.

    Args:
        tiff_path: Path or URL to the input TIFF file
        output_path: Local filesystem path where the COG will be saved

    Raises:
        RuntimeError: If GDAL cannot open the input file or conversion fails
        SystemExit: If conversion fails (exits with code 1)

    Example:
        >>> run_gdal_translate_chunked(
        ...     "https://example.com/large_file.tif",
        ...     "output.tif"
        ... )
    """
    # Create temporary file for initial chunked processing
    tmp_file = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    tmp_path = tmp_file.name
    tmp_file.close()

    try:
        # Get raster metadata
        raster_metadata = get_raster_metadata(tiff_path)

        chunk_size_config = calculate_chunk_size(raster_metadata)

        # Create chunks
        chunks = create_chunks(raster_metadata, chunk_size_config)

        # Create output COG dataset in temporary file
        output_dataset = create_output_cog_dataset(tmp_path, raster_metadata)

        try:
            # Process each chunk sequentially
            for chunk in chunks:
                # Process chunk
                result = process_chunk(tiff_path, chunk, output_dataset)

                if result["status"] != "completed":
                    raise RuntimeError(
                        f"Chunk {result['chunk_id']} processing failed: {result.get('error', 'Unknown error')}"
                    )

                # Log progress
                progress = (chunk["chunk_id"] + 1) / len(chunks) * 100
                logging.info(
                    f"Progress: {progress:.1f}% ({chunk['chunk_id'] + 1}/{len(chunks)} chunks)"
                )

        finally:
            # Close output dataset before building overviews
            output_dataset.close()

        # Build overviews for COG compliance (required for COG specification)
        # COGs require internal overviews for efficient cloud-based streaming access
        logging.info("Building overviews for COG compliance...")
        overview_levels = []
        try:
            with rasterio.open(tmp_path, "r+") as dst:
                # Calculate overview levels (powers of 2, up to reasonable limit)
                width = dst.width
                height = dst.height
                level = 2
                while width // level > 256 and height // level > 256:
                    overview_levels.append(level)
                    level *= 2
                    if len(overview_levels) >= 5:  # Limit to 5 overview levels
                        break

                if overview_levels:
                    dst.build_overviews(overview_levels, resampling=Resampling.nearest)
                    # Write overviews to file
                    dst.update_tags(ns="rio_overview", resampling="nearest")
                    logging.info(
                        f"Built {len(overview_levels)} overview levels: {overview_levels}"
                    )
                else:
                    logging.warning(
                        "No overview levels built (raster too small or calculation failed)"
                    )

        except Exception as e:
            logging.warning(
                f"Failed to build overviews: {e}. File may not be fully COG-compliant."
            )

        # Reorganize into proper COG structure using rio-cogeo
        logging.info("Reorganizing file into COG-compliant structure...")
        try:
            # Get COG profile with default options
            output_profile = cog_profiles.get("lzw")
            output_profile.update(
                {
                    "blockxsize": 512,
                    "blockysize": 512,
                }
            )

            # Configure GDAL options for COG creation
            config = {
                "GDAL_TIFF_OVR_BLOCKSIZE": "512",
            }

            # Use cog_translate to reorganize file into COG-compliant structure
            # This reorganizes the file layout without loading all data into memory
            cog_translate(
                tmp_path,
                output_path,
                output_profile,
                config=config,
                in_memory=False,  # Process on disk to maintain memory efficiency
                quiet=True,  # Suppress verbose output
            )
            logging.info("Successfully reorganized into COG-compliant structure")

        except Exception as e:
            error_msg = f"Failed to reorganize into COG structure: {e}"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e

        logging.info(
            f"Successfully converted to COG using chunked processing: {output_path}"
        )

    except Exception as e:
        error_msg = f"Chunked conversion failed: {e}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    finally:
        # Clean up temporary file
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception as e:
                logging.warning(f"Failed to clean up temporary file {tmp_path}: {e}")


def run_gdal_translate(tiff_path: str, output_path: str) -> None:
    """Convert a TIFF file to Cloud Optimized GeoTIFF (COG) format using chunked processing.

    All files are processed using chunked processing for consistency and memory efficiency.
    Uses default GDAL options.

    Args:
        tiff_path: Path or URL to the input TIFF file
        output_path: Local filesystem path where the COG will be saved

    Raises:
        RuntimeError: If GDAL cannot open the input file or conversion fails

    Example:
        >>> run_gdal_translate(
        ...     "https://example.com/data.tif",
        ...     "output.tif"
        ... )
    """
    run_gdal_translate_chunked(tiff_path, output_path)


def get_output_cog_path(input_path: str, output_dir: str = "output_cog") -> str:
    """Generate the output path for the COG file.

    Creates an output directory if it doesn't exist and generates a new filename
    by appending '_cog' to the original filename before the extension.

    Args:
        input_path: Path to the input TIFF file (or URL - only filename is used)
        output_dir: Directory where COG files will be saved (default: "output_cog")

    Returns:
        Path to the output COG file as a string

    Example:
        >>> get_output_cog_path("data.tif")
        'output_cog/data_cog.tif'
        >>> get_output_cog_path("https://example.com/image.tiff", "my_cogs")
        'my_cogs/image_cog.tiff'
    """
    input_path = Path(input_path)
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(exist_ok=True)
    new_name = input_path.stem + "_cog" + input_path.suffix
    return str(output_dir_path / new_name)


def is_tiff_asset(asset: Dict[str, any]) -> bool:
    """Check if an asset is a TIFF file based on media type or file extension.

    Args:
        asset: STAC asset dictionary containing href, type, and other metadata

    Returns:
        True if the asset is a TIFF file, False otherwise
    """
    # Check media type first
    media_type = asset.get("type", "").lower()
    if "tiff" in media_type or "geotiff" in media_type:
        return True

    # Check file extension
    href = asset.get("href", "")
    if not href:
        return False

    # Extract filename from URL or path
    filename = Path(href.split("?")[0]).name.lower()
    tiff_extensions = [".tif", ".tiff", ".tiff"]

    return any(filename.endswith(ext) for ext in tiff_extensions)


def copy_asset(
    asset_href: str, output_dir: str, preserve_structure: bool = True
) -> str:
    """Download and copy a non-TIFF asset to the output directory.

    Args:
        asset_href: URL or path to the asset file
        output_dir: Directory where the asset will be copied
        preserve_structure: Whether to preserve subdirectory structure

    Returns:
        Path to the copied asset file

    Raises:
        RuntimeError: If download or copy fails
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(exist_ok=True)

    # Extract filename from URL
    filename = Path(asset_href.split("?")[0]).name

    if preserve_structure and "/" in asset_href:
        # Try to preserve some directory structure
        # For URLs, use the last two path segments
        url_parts = asset_href.split("/")
        if len(url_parts) > 2:
            subdir = url_parts[-2]  # Second to last part
            output_path = output_dir_path / subdir / filename
            output_path.parent.mkdir(exist_ok=True)
        else:
            output_path = output_dir_path / filename
    else:
        output_path = output_dir_path / filename

    # Download the file
    try:
        if asset_href.startswith(("http://", "https://")):
            logging.info(f"Downloading asset: {asset_href}")
            response = requests.get(asset_href, stream=True)
            response.raise_for_status()

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        else:
            # Local file copy
            logging.info(f"Copying local asset: {asset_href}")
            shutil.copy2(asset_href, output_path)

        logging.info(f"Successfully copied asset to: {output_path}")
        return str(output_path)

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to download asset {asset_href}: {e}")
    except (OSError, IOError) as e:
        raise RuntimeError(f"Failed to copy asset {asset_href}: {e}")


def download_stac_item(stac_item_url: str) -> Dict[str, any]:
    """Download and parse a STAC item from URL.

    Args:
        stac_item_url: URL to the STAC item JSON file (supports http/https/file URLs)

    Returns:
        Parsed STAC item as a dictionary

    Raises:
        RuntimeError: If download or parsing fails
    """
    try:
        logging.info(f"Downloading STAC item: {stac_item_url}")

        if stac_item_url.startswith("file://"):
            # Handle local file URLs
            file_path = stac_item_url[7:]  # Remove "file://" prefix
            with open(file_path, "r") as f:
                stac_item = json.load(f)
        else:
            # Handle HTTP/HTTPS URLs
            response = requests.get(stac_item_url)
            response.raise_for_status()
            stac_item = response.json()

        # Basic validation
        if not isinstance(stac_item, dict):
            raise RuntimeError("STAC item is not a valid JSON object")

        if stac_item.get("type") != "Feature":
            raise RuntimeError("STAC item is not a Feature type")

        if "assets" not in stac_item:
            raise RuntimeError("STAC item has no assets")

        logging.info(
            f"Successfully downloaded STAC item with {len(stac_item['assets'])} assets"
        )
        return stac_item

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to download STAC item {stac_item_url}: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse STAC item JSON: {e}")
    except (OSError, IOError) as e:
        raise RuntimeError(f"Failed to read local STAC item file {stac_item_url}: {e}")
