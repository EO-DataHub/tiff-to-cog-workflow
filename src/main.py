"""TIFF to COG conversion script with STAC catalog generation."""

import argparse
from pathlib import Path
import sys
import logging
import os
import shutil
from logging_config import setup_logging
from stac_utils import create_stac_catalog_from_item
from s3_utils import (
    download_file_from_s3,
    parse_eodatahub_url,
)
from gdal_utils import (
    run_gdal_translate,
    get_output_cog_path,
    is_tiff_asset,
    copy_asset,
    download_stac_item,
)
from validation import (
    ValidationError,
    validate_downloaded_file,
    validate_file_size,
)
import gc

# Setup logging configuration
setup_logging()

# Directory configuration from environment variables with defaults
DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "/tmp")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/tmp/output")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Namespace containing the parsed arguments:
            - stac_item_url: URL to STAC item JSON file
    """
    parser = argparse.ArgumentParser(
        description="Convert STAC item TIFF assets to Cloud Optimized GeoTIFF (COG) format"
    )
    parser.add_argument("--stac_item_url", type=str, help="URL to STAC item JSON file")
    return parser.parse_args()


def main() -> None:
    """Main entry point for the STAC item to COG conversion script.

    Handles the workflow of:
    1. Parsing command line arguments
    2. Downloading and parsing STAC item JSON
    3. Processing each asset in the STAC item:
       - Convert TIFF assets to COG format
       - Copy non-TIFF assets to output directory
    4. Creating output STAC catalog with updated asset references

    Raises:
        SystemExit: If required arguments are missing or any step fails
    """
    try:
        args = parse_args()

        if not args.stac_item_url:
            logging.error("You must provide a --stac_item_url")
            sys.exit(1)

        # Download and parse STAC item
        stac_item = download_stac_item(args.stac_item_url)

        # Process assets
        processed_assets = {}
        output_dir = OUTPUT_DIR

        # Create item-specific directory
        item_id = stac_item.get("id", "processed_item")
        item_output_dir = f"{output_dir}/{item_id}"
        Path(item_output_dir).mkdir(parents=True, exist_ok=True)

        # Process assets with improved error handling
        failed_assets = []
        total_assets = len(stac_item.get("assets", {}))

        for asset_index, (asset_key, asset) in enumerate(
            stac_item.get("assets", {}).items(), 1
        ):
            asset_href = asset.get("href")
            if not asset_href:
                logging.warning(f"Asset {asset_key} has no href, skipping")
                failed_assets.append(asset_key)
                continue

            logging.info(
                f"🔄 Processing asset {asset_index}/{total_assets}: {asset_key}"
            )

            # Check asset type first to determine appropriate validation
            is_tiff = is_tiff_asset(asset)

            # Check if this is an EODH workspace URL that needs S3 download
            if "eodatahub-workspaces.org.uk" in asset_href:
                logging.info(
                    f"🌐 EODH workspace URL detected for asset {asset_key} - parsing and downloading from S3"
                )
                try:
                    bucket_name, key, local_path = parse_eodatahub_url(
                        asset_href, DOWNLOAD_DIR
                    )
                    download_file_from_s3(bucket_name, key, local_path)

                    # Apply appropriate validation based on asset type
                    try:
                        if is_tiff:
                            validate_downloaded_file(local_path)
                        else:
                            validate_file_size(local_path)
                    except ValidationError as e:
                        logging.error(
                            f"❌ Downloaded file validation failed for {asset_key}: {e}"
                        )
                        failed_assets.append(asset_key)
                        continue

                    # Use local path for further processing
                    asset_href = local_path

                except Exception as e:
                    logging.error(f"❌ Failed to download EODH asset {asset_key}: {e}")
                    failed_assets.append(asset_key)
                    continue

            if is_tiff:
                # Convert TIFF to COG
                logging.info(f"🔄 Converting TIFF asset {asset_key} to COG")
                try:
                    # Get output path for COG
                    filename = Path(asset_href.split("?")[0]).name
                    output_cog = get_output_cog_path(filename, item_output_dir)

                    # Convert to COG (automatically routes to chunked processing if needed)
                    run_gdal_translate(asset_href, output_cog)

                    # Force garbage collection to release memory between assets
                    gc.collect()

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
                        f"✅ Successfully converted {asset_key} to COG: {output_cog} ({file_size:,} bytes)"
                    )

                except Exception as e:
                    logging.error(f"❌ Failed to convert TIFF asset {asset_key}: {e}")
                    failed_assets.append(asset_key)
                    continue
            else:
                # Copy non-TIFF asset
                logging.info(f"📋 Copying non-TIFF asset {asset_key}")
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

                    logging.info(
                        f"✅ Successfully copied {asset_key} to: {copied_path} ({file_size:,} bytes)"
                    )

                except Exception as e:
                    logging.error(f"❌ Failed to copy asset {asset_key}: {e}")
                    failed_assets.append(asset_key)
                    continue

        # Log processing summary
        successful_assets = len(processed_assets)
        logging.info(
            f"📊 Processing summary: {successful_assets}/{total_assets} assets processed successfully"
        )

        if failed_assets:
            logging.warning(
                f"⚠️  Failed assets ({len(failed_assets)}): {', '.join(failed_assets)}"
            )

        # Create output STAC catalog
        if processed_assets:
            try:
                create_stac_catalog_from_item(
                    stac_item, processed_assets, item_output_dir
                )
                logging.info(
                    f"✅ Successfully created STAC catalog with {len(processed_assets)} assets"
                )

                # Copy to CWL output directory if specified (for CWL workflow compatibility)
                cwl_output_dir = os.environ.get("CWL_OUTPUT_DIR")
                if cwl_output_dir and output_dir != cwl_output_dir:
                    logging.info(
                        f"📦 Copying output from {output_dir} to {cwl_output_dir} for CWL"
                    )
                    cwl_output_path = Path(cwl_output_dir)
                    cwl_output_path.mkdir(parents=True, exist_ok=True)

                    # Copy entire output directory contents to CWL output directory
                    for item in Path(output_dir).iterdir():
                        dest = cwl_output_path / item.name
                        if item.is_dir():
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)

                    logging.info(f"✅ Successfully copied output to {cwl_output_dir}")

            except Exception as e:
                logging.error(f"❌ Failed to create STAC catalog: {e}")
                sys.exit(1)
        else:
            logging.error("❌ No assets were processed successfully")
            if failed_assets:
                logging.error(f"All {len(failed_assets)} assets failed processing")
            sys.exit(1)

    except KeyboardInterrupt:
        logging.warning("Operation cancelled by user")
        sys.exit(130)  # Standard exit code for Ctrl+C
    except Exception as e:
        logging.error(f"Error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
