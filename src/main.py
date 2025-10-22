"""TIFF to COG conversion script with STAC catalog generation."""

import argparse
from pathlib import Path
import sys
import logging
import os
import time
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
from validation import (
    ValidationError,
    validate_input_url,
    validate_downloaded_file,
    validate_file_size,
)

logging.basicConfig(
    level=logging.DEBUG, format="[%(levelname)s] %(message)s", stream=sys.stderr
)

# Suppress verbose boto3 and s3transfer logs
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("s3transfer").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class ProgressCallback:
    """Callback for tracking S3 download progress."""

    def __init__(self, filename, file_size):
        self._filename = filename
        self._size = file_size
        self._seen_so_far = 0
        self._start_time = time.time()
        self._last_log_time = time.time()

    def __call__(self, bytes_amount):
        self._seen_so_far += bytes_amount
        current_time = time.time()

        # Log progress every 5 seconds or at completion
        if current_time - self._last_log_time >= 5 or self._seen_so_far >= self._size:
            percentage = (self._seen_so_far / self._size) * 100 if self._size > 0 else 0
            elapsed = current_time - self._start_time
            speed_mbps = (
                (self._seen_so_far / (1024 * 1024)) / elapsed if elapsed > 0 else 0
            )

            logging.info(
                f"📥 Downloading {self._filename}: {percentage:.1f}% "
                f"({self._seen_so_far / (1024 * 1024):.1f}/{self._size / (1024 * 1024):.1f} MB) "
                f"Speed: {speed_mbps:.2f} MB/s"
            )
            self._last_log_time = current_time


def check_aws_credentials() -> bool:
    """Check if AWS credentials are available for S3 access.

    Returns:
        True if credentials are valid and S3 access is available, False otherwise
    """
    try:
        # Get AWS region from environment or use default
        aws_region = os.environ.get(
            "AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1")
        )
        logging.info(f"🌍 Using AWS region: {aws_region}")

        s3 = boto3.client("s3", region_name=aws_region)
        s3.list_buckets()
        logging.info("✅ AWS credentials validated successfully")
        return True
    except NoCredentialsError:
        logging.error("❌ AWS credentials not found. Please configure AWS credentials.")
        return False
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        if error_code == "InvalidAccessKeyId":
            logging.error("❌ Invalid AWS Access Key ID")
        elif error_code == "SignatureDoesNotMatch":
            logging.error("❌ Invalid AWS Secret Access Key")
        else:
            logging.error(f"❌ AWS credential validation failed: {error_code}")
        return False
    except BotoCoreError as e:
        logging.error(f"❌ AWS SDK error during credential validation: {e}")
        return False


def download_file_from_s3(
    bucket_name: str, key: str, output_path: str, max_retries: int = 3
) -> None:
    """Download a file from S3 bucket to local filesystem with retry logic.

    Args:
        bucket_name: Name of the S3 bucket
        key: S3 object key (path within bucket)
        output_path: Local filesystem path where file will be saved
        max_retries: Maximum number of retry attempts for transient errors

    Raises:
        ClientError: If S3 operation fails after all retries
        NoCredentialsError: If AWS credentials are not available
    """
    import time
    from botocore.exceptions import ClientError, NoCredentialsError

    # Get AWS region from environment or use default
    aws_region = os.environ.get(
        "AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1")
    )
    logging.info(f"🌍 Using AWS region for S3: {aws_region}")

    s3 = boto3.client("s3", region_name=aws_region)

    for attempt in range(max_retries + 1):
        try:
            logging.info(
                f"📥 Downloading from S3 (attempt {attempt + 1}/{max_retries + 1}): {bucket_name}/{key}"
            )

            # Get object metadata first to log file size
            try:
                response = s3.head_object(Bucket=bucket_name, Key=key)
                file_size = response.get("ContentLength", 0)
                if file_size > 0:
                    logging.info(
                        f"📊 File size: {file_size:,} bytes ({file_size / (1024 * 1024):.1f} MB)"
                    )
            except ClientError as e:
                logging.warning(f"⚠️  Could not get file metadata: {e}")

            # Download the file
            if file_size > 10 * 1024 * 1024:  # Only show progress for files > 10MB
                progress = ProgressCallback(key.split("/")[-1], file_size)
                s3.download_file(bucket_name, key, output_path, Callback=progress)
            else:
                s3.download_file(bucket_name, key, output_path)

            # Verify download
            downloaded_size = os.path.getsize(output_path)
            logging.info(
                f"✅ Successfully downloaded {downloaded_size:,} bytes to {output_path}"
            )
            return

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")

            if error_code == "NoSuchBucket":
                logging.error(f"❌ S3 bucket does not exist: {bucket_name}")
                raise
            elif error_code == "NoSuchKey":
                logging.error(f"❌ S3 object not found: {bucket_name}/{key}")
                raise
            elif error_code == "403" or error_code == "AccessDenied":
                logging.error(
                    f"❌ Permission denied to access S3 object: {bucket_name}/{key}"
                )
                raise
            elif error_code in ["RequestTimeout", "ServiceUnavailable", "SlowDown"]:
                if attempt < max_retries:
                    wait_time = 2**attempt  # Exponential backoff
                    logging.warning(
                        f"⚠️  Transient S3 error ({error_code}), retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    logging.error(
                        f"❌ S3 error after {max_retries} retries: {error_code}"
                    )
                    raise
            else:
                logging.error(f"❌ S3 error ({error_code}): {e}")
                raise

        except NoCredentialsError:
            logging.error("❌ AWS credentials not available for S3 download")
            raise

        except Exception as e:
            if attempt < max_retries:
                wait_time = 2**attempt
                logging.warning(
                    f"⚠️  Unexpected error during download, retrying in {wait_time}s: {e}"
                )
                time.sleep(wait_time)
                continue
            else:
                logging.error(f"❌ Download failed after {max_retries} retries: {e}")
                raise


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


def estimate_required_resources(stac_item: dict) -> dict:
    """Estimate required resources based on STAC item assets.

    Args:
        stac_item: STAC item dictionary

    Returns:
        Dictionary with resource estimates
    """
    assets = stac_item.get("assets", {})
    total_assets = len(assets)
    tiff_assets = sum(1 for asset in assets.values() if is_tiff_asset(asset))
    eodh_assets = sum(
        1
        for asset in assets.values()
        if asset.get("href", "").startswith("https://eodatahub-workspaces.org.uk")
    )

    # Rough estimates (these could be made more sophisticated)
    estimated_disk_space_mb = total_assets * 100  # Assume average 100MB per asset
    estimated_memory_mb = tiff_assets * 200  # Assume 200MB per TIFF for processing

    return {
        "total_assets": total_assets,
        "tiff_assets": tiff_assets,
        "eodh_assets": eodh_assets,
        "estimated_disk_space_mb": estimated_disk_space_mb,
        "estimated_memory_mb": estimated_memory_mb,
    }


def check_disk_space(required_mb: int, path: str = "/tmp") -> bool:
    """Check if sufficient disk space is available.

    Args:
        required_mb: Required disk space in MB
        path: Path to check disk space for

    Returns:
        True if sufficient space is available
    """
    try:
        statvfs = os.statvfs(path)
        available_mb = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)

        logging.info(f"💾 Available disk space: {available_mb:.1f} MB")
        logging.info(f"📊 Required disk space: {required_mb:.1f} MB")

        if available_mb < required_mb:
            logging.error(
                f"❌ Insufficient disk space: {available_mb:.1f} MB available, {required_mb:.1f} MB required"
            )
            return False

        return True
    except OSError as e:
        logging.warning(f"⚠️  Could not check disk space: {e}")
        return True  # Assume OK if we can't check


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
    logging.info(f"Parsing EODH URL: {url}")
    url_parts = url.split("/")
    files_idx = url_parts.index("files")
    bucket_name = url_parts[files_idx + 1]
    workspace_name = url_parts[2].split(".")[0]
    key = f"{workspace_name}/" + "/".join(url_parts[files_idx + 2 :])
    file_name = key.split("/")[-1]
    local_tiff_path = f"/tmp/{file_name}"
    logging.debug(
        {"bucket_name": bucket_name, "key": key, "local_tiff_path": local_tiff_path}
    )

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

        # Estimate required resources and check availability
        resource_estimate = estimate_required_resources(stac_item)
        logging.info(
            f"📊 Resource estimate: {resource_estimate['total_assets']} total assets, "
            f"{resource_estimate['tiff_assets']} TIFF assets, "
            f"{resource_estimate['eodh_assets']} EODH assets"
        )

        if resource_estimate["total_assets"] > 10:
            logging.warning(
                f"⚠️  High asset count ({resource_estimate['total_assets']}) - processing may take longer"
            )

        # Check disk space
        if not check_disk_space(resource_estimate["estimated_disk_space_mb"]):
            logging.error("❌ Insufficient disk space for processing")
            sys.exit(1)

        # Check AWS credentials if EODH assets are present
        if resource_estimate["eodh_assets"] > 0:
            logging.info(
                f"🔍 EODH assets detected ({resource_estimate['eodh_assets']}), validating AWS credentials..."
            )
            if not check_aws_credentials():
                logging.error(
                    "❌ AWS credentials validation failed - cannot process EODH assets"
                )
                sys.exit(1)

        # Process assets
        processed_assets = {}
        output_dir = "output_cog"

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
                    bucket_name, key, local_path = parse_eodatahub_url(asset_href)
                    logging.info(
                        f"📥 S3 download details: bucket={bucket_name}, key={key}, local_path={local_path}"
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
            except Exception as e:
                logging.error(f"❌ Failed to create STAC catalog: {e}")
                sys.exit(1)
        else:
            logging.error("❌ No assets were processed successfully")
            if failed_assets:
                logging.error(f"All {len(failed_assets)} assets failed processing")
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
