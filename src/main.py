"""TIFF to COG conversion script with STAC catalog generation."""

import argparse
from pathlib import Path
import sys
import logging
import os
import boto3
from typing import Tuple
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from stac_utils import create_stac_catalog_from_item
from gdal_utils import (
    run_gdal_translate,
    parse_gdal_options,
    get_output_cog_path,
    is_tiff_asset,
    copy_asset,
    download_stac_item,
)
from validation import ValidationError, validate_input_url, validate_downloaded_file

logging.basicConfig(
    level=logging.DEBUG, format="[%(levelname)s] %(message)s", stream=sys.stderr
)


def download_file_from_s3(bucket_name: str, key: str, output_path: str) -> None:
    """Download a file from S3 bucket to local filesystem.

    Args:
        bucket_name: Name of the S3 bucket
        key: S3 object key (path within bucket)
        output_path: Local filesystem path where file will be saved
    """
    s3 = boto3.client("s3")
    s3.download_file(bucket_name, key, output_path)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Namespace containing the parsed arguments:
            - stac_item_url: URL to STAC item JSON file
            - gdal_options: Optional JSON string with GDAL creation options
    """
    parser = argparse.ArgumentParser(
        description="Convert STAC item TIFF assets to Cloud Optimized GeoTIFF (COG) format"
    )
    parser.add_argument("--stac_item_url", type=str, help="URL to STAC item JSON file")
    parser.add_argument(
        "--gdal-options",
        type=str,
        default=None,
        help='Optional GDAL creation options as JSON string, e.g., \'{"COMPRESS":"ZSTD","BLOCKSIZE":"1024"}\'. '
        "If not provided, uses defaults: COMPRESS=LZW, BLOCKSIZE=512, OVERVIEW_RESAMPLING=NEAREST",
    )
    return parser.parse_args()


def parse_eodatahub_url(url: str) -> Tuple[str, str, str]:
    """Parse eodatahub-workspaces.org.uk URL to extract S3 bucket and key.

    Args:
        url: URL from eodatahub-workspaces.org.uk pointing to a TIFF file

    Returns:
        Tuple containing:
            - bucket_name: Name of the S3 bucket
            - key: S3 object key (path within bucket)
            - local_tiff_path: Local path where the file will be downloaded
    """
    url_parts = url.split("/")
    files_idx = url_parts.index("files")
    bucket_name = url_parts[files_idx + 1]
    workspace_name = url_parts[2].split(".")[0]
    key = f"{workspace_name}/" + "/".join(url_parts[files_idx + 2 :])
    file_name = key.split("/")[-1]
    local_tiff_path = f"/tmp/{file_name}"

    return bucket_name, key, local_tiff_path


def main() -> None:
    """Main entry point for the STAC item to COG conversion script.

    Handles the workflow of:
    1. Parsing command line arguments
    2. Validating input STAC item URL
    3. Parsing optional GDAL options (uses defaults if not provided)
    4. Downloading and parsing STAC item JSON
    5. Processing each asset in the STAC item:
       - Convert TIFF assets to COG format
       - Copy non-TIFF assets to output directory
    6. Creating output STAC catalog with updated asset references

    Raises:
        SystemExit: If required arguments are missing or any step fails
    """
    try:
        args = parse_args()

        if not args.stac_item_url:
            logging.error("You must provide a --stac_item_url")
            sys.exit(1)

        # Validate input URL before processing
        try:
            validate_input_url(args.stac_item_url)
        except ValidationError as e:
            logging.error(f"Input validation failed: {e}")
            sys.exit(1)

        # Parse GDAL options (will use defaults if not provided)
        try:
            gdal_options = parse_gdal_options(args.gdal_options)
        except ValueError as e:
            logging.error(f"Invalid GDAL options: {e}")
            sys.exit(1)

        # Download and parse STAC item
        try:
            stac_item = download_stac_item(args.stac_item_url)
        except RuntimeError as e:
            logging.error(f"Failed to download STAC item: {e}")
            sys.exit(1)

        # Process assets
        processed_assets = {}
        output_dir = "output_cog"

        # Create item-specific directory
        item_id = stac_item.get("id", "processed_item")
        item_output_dir = f"{output_dir}/{item_id}"
        Path(item_output_dir).mkdir(parents=True, exist_ok=True)

        for asset_key, asset in stac_item.get("assets", {}).items():
            asset_href = asset.get("href")
            if not asset_href:
                logging.warning(f"Asset {asset_key} has no href, skipping")
                continue

            logging.info(f"Processing asset: {asset_key}")

            # Check if this is an EODH workspace URL that needs S3 download
            if "eodatahub-workspaces.org.uk" in asset_href:
                logging.info(
                    f"EODH workspace URL detected for asset {asset_key} - parsing and downloading from S3"
                )
                try:
                    bucket_name, key, local_path = parse_eodatahub_url(asset_href)
                    logging.info(
                        f"Downloading from S3: {bucket_name}, {key}, {local_path}"
                    )
                    download_file_from_s3(bucket_name, key, local_path)

                    # Validate downloaded file
                    try:
                        validate_downloaded_file(local_path)
                    except ValidationError as e:
                        logging.error(f"Downloaded file validation failed: {e}")
                        sys.exit(1)

                    # Use local path for further processing
                    asset_href = local_path

                except Exception as e:
                    logging.error(f"Failed to download EODH asset {asset_key}: {e}")
                    sys.exit(1)

            if is_tiff_asset(asset):
                # Convert TIFF to COG
                logging.info(f"Converting TIFF asset {asset_key} to COG")
                try:
                    # Get output path for COG
                    filename = Path(asset_href.split("?")[0]).name
                    output_cog = get_output_cog_path(filename, item_output_dir)

                    # Convert to COG
                    run_gdal_translate(asset_href, output_cog, gdal_options)

                    # Get file size
                    file_size = os.path.getsize(output_cog)

                    # Determine media type
                    media_type = "image/tiff; application=geotiff"

                    processed_assets[asset_key] = {
                        "href": f"./{Path(output_cog).name}",
                        "size": file_size,
                        "type": media_type,
                    }

                    logging.info(
                        f"Successfully converted {asset_key} to COG: {output_cog}"
                    )

                except Exception as e:
                    logging.error(f"Failed to convert TIFF asset {asset_key}: {e}")
                    sys.exit(1)
            else:
                # Copy non-TIFF asset
                logging.info(f"Copying non-TIFF asset {asset_key}")
                try:
                    copied_path = copy_asset(
                        asset_href, item_output_dir, preserve_structure=False
                    )

                    # Get file size
                    file_size = os.path.getsize(copied_path)

                    # Determine media type from original asset or file extension
                    media_type = asset.get("type", "application/octet-stream")

                    # Create relative path for STAC item
                    relative_path = f"./{Path(copied_path).name}"

                    processed_assets[asset_key] = {
                        "href": relative_path,
                        "size": file_size,
                        "type": media_type,
                    }

                    logging.info(f"Successfully copied {asset_key} to: {copied_path}")

                except Exception as e:
                    logging.error(f"Failed to copy asset {asset_key}: {e}")
                    sys.exit(1)

        # Create output STAC catalog
        if processed_assets:
            try:
                create_stac_catalog_from_item(
                    stac_item, processed_assets, item_output_dir
                )
                logging.info(
                    f"Successfully created STAC catalog with {len(processed_assets)} assets"
                )
            except Exception as e:
                logging.error(f"Failed to create STAC catalog: {e}")
                sys.exit(1)
        else:
            logging.error("No assets were processed successfully")
            sys.exit(1)

    # Validation errors
    except ValidationError as e:
        logging.error(f"Validation error: {e}")
        sys.exit(1)

    # GDAL option parsing errors
    except ValueError as e:
        logging.error(f"Invalid value or format: {e}")
        sys.exit(1)

    # AWS/S3 specific errors
    except NoCredentialsError:
        logging.error("AWS credentials not found. Please configure AWS credentials.")
        sys.exit(1)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "NoSuchBucket":
            logging.error(f"S3 bucket does not exist: {e}")
        elif error_code == "NoSuchKey":
            logging.error(f"S3 object not found: {e}")
        elif error_code == "403":
            logging.error(f"Permission denied to access S3 object: {e}")
        else:
            logging.error(f"S3 error ({error_code}): {e}")
        sys.exit(1)
    except BotoCoreError as e:
        logging.error(f"AWS SDK error: {e}")
        sys.exit(1)

    # File system errors
    except FileNotFoundError as e:
        logging.error(f"File not found: {e}")
        sys.exit(1)
    except PermissionError as e:
        logging.error(f"Permission denied: {e}")
        sys.exit(1)
    except OSError as e:
        logging.error(f"OS error (disk full, network issue, etc.): {e}")
        sys.exit(1)

    # GDAL/Runtime errors (from gdal_utils)
    except RuntimeError as e:
        logging.error(f"Runtime error: {e}")
        sys.exit(1)

    # Keyboard interrupt
    except KeyboardInterrupt:
        logging.warning("Operation cancelled by user")
        sys.exit(130)  # Standard exit code for Ctrl+C

    # Catch-all for truly unexpected errors
    except Exception as e:
        logging.error(f"Unexpected error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
