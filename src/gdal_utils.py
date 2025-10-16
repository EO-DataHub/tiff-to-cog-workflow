"""GDAL utilities for TIFF to COG conversion."""

import json
import logging
import sys
import shutil
import requests
from pathlib import Path
from typing import Dict, Optional
from osgeo import gdal


def get_default_gdal_options() -> Dict[str, str]:
    """Get default GDAL creation options for COG conversion.

    Returns:
        Dictionary of default GDAL creation options with sensible defaults:
        - COMPRESS: LZW compression (good balance of speed and size)
        - BLOCKSIZE: 512 pixel tiles (standard for COGs)
        - OVERVIEW_RESAMPLING: NEAREST neighbor (fast, preserves values)
    """
    return {
        "COMPRESS": "LZW",
        "BLOCKSIZE": "512",
        "OVERVIEW_RESAMPLING": "NEAREST",
    }


def parse_gdal_options(options_str: Optional[str] = None) -> Dict[str, str]:
    """Parse GDAL options from JSON string and merge with defaults.

    User-provided options override defaults. Any GDAL creation option can be
    specified, for example:
    - COMPRESS: LZW, DEFLATE, ZSTD, WEBP, JPEG, NONE
    - BLOCKSIZE: 256, 512, 1024, 2048
    - PREDICTOR: 1 (none), 2 (horizontal), 3 (floating point)
    - NUM_THREADS: ALL_CPUS or specific number
    - OVERVIEW_RESAMPLING: NEAREST, BILINEAR, CUBIC, AVERAGE

    Args:
        options_str: JSON string containing GDAL options, e.g.,
                    '{"COMPRESS":"ZSTD","BLOCKSIZE":"1024"}'
                    If None, returns default options only.

    Returns:
        Dictionary of GDAL creation options (user options merged with defaults)

    Raises:
        ValueError: If JSON string is invalid or not a dictionary
    """
    defaults = get_default_gdal_options()

    if options_str is None:
        return defaults

    try:
        user_options = json.loads(options_str)
        if not isinstance(user_options, dict):
            raise ValueError("GDAL options must be a JSON object/dictionary")

        # Merge user options with defaults (user options take precedence)
        merged = {**defaults, **user_options}

        logging.info(f"Using GDAL options: {merged}")
        return merged

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in --gdal_options: {e}")


def run_gdal_translate(
    tiff_path: str, output_path: str, gdal_options: Optional[Dict[str, str]] = None
) -> None:
    """Convert a TIFF file to Cloud Optimized GeoTIFF (COG) format using GDAL.

    This function uses the GDAL COG driver which automatically creates:
    - Tiled GeoTIFF with internal overviews
    - Optimized for cloud-based streaming access
    - Proper internal structure for range requests

    Remote URLs (http/https) are automatically accessed via GDAL's /vsicurl/
    virtual file system for efficient remote reading.

    Args:
        tiff_path: Path or URL to the input TIFF file. HTTP/HTTPS URLs are
                   automatically prefixed with /vsicurl/ for GDAL remote access.
                   Can also be a local file path.
        output_path: Local filesystem path where the COG will be saved
        gdal_options: Dictionary of GDAL creation options. If None, uses defaults.
                     See get_default_gdal_options() for default values.

    Raises:
        RuntimeError: If GDAL cannot open the input file
        SystemExit: If GDAL conversion fails (exits with code 1)

    Example:
        >>> run_gdal_translate(
        ...     "https://example.com/data.tif",
        ...     "output.tif",
        ...     {"COMPRESS": "ZSTD", "BLOCKSIZE": "1024"}
        ... )
    """
    # Use defaults if no options provided
    if gdal_options is None:
        gdal_options = get_default_gdal_options()

    # Check if the path is a local file or a remote URL
    if tiff_path.startswith(("http://", "https://")):
        # Remote URL - use /vsicurl/ prefix for GDAL virtual file system
        input_path = f"/vsicurl/{tiff_path}"
    else:
        # Local file path - use directly
        input_path = tiff_path

    logging.debug(f"Opening input file: {input_path}")
    logging.debug(f"Using GDAL options: {gdal_options}")

    # Configure GDAL to suppress warnings to stdout (use Python logging instead)
    gdal.UseExceptions()

    try:
        # Open the input dataset
        src_ds = gdal.Open(input_path, gdal.GA_ReadOnly)
        if src_ds is None:
            error_msg = f"Failed to open input file: {input_path}"
            last_error = gdal.GetLastErrorMsg()
            if last_error:
                error_msg += f" - {last_error}"
            raise RuntimeError(error_msg)

        # Convert options dict to GDAL format (list of "KEY=VALUE" strings)
        creation_options = [f"{key}={value}" for key, value in gdal_options.items()]

        # Get COG driver
        driver = gdal.GetDriverByName("COG")
        if driver is None:
            raise RuntimeError(
                "COG driver not found. GDAL 3.1+ is required. "
                "Current GDAL version: " + gdal.__version__
            )

        # Perform the translation to COG format
        logging.info(f"Converting {input_path} to COG format...")
        dst_ds = driver.CreateCopy(
            output_path,
            src_ds,
            strict=0,  # Non-strict mode allows some flexibility
            options=creation_options,
        )

        if dst_ds is None:
            error_msg = "GDAL CreateCopy failed"
            last_error = gdal.GetLastErrorMsg()
            if last_error:
                error_msg += f": {last_error}"
            raise RuntimeError(error_msg)

        # Explicitly close datasets to flush to disk
        dst_ds = None
        src_ds = None

        logging.info(f"Successfully converted to COG: {output_path}")

    except RuntimeError as e:
        logging.error(f"GDAL conversion failed: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error during GDAL conversion: {e}")
        last_error = gdal.GetLastErrorMsg()
        if last_error:
            logging.error(f"GDAL error message: {last_error}")
        sys.exit(1)
    finally:
        # Ensure datasets are closed even if an error occurred
        gdal.ErrorReset()


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
