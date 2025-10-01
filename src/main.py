"""TIFF to COG conversion script with STAC catalog generation."""

import argparse
from pathlib import Path
import sys
import logging
import boto3
from typing import Tuple
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from stac_utils import create_stac_catalog
from gdal_utils import run_gdal_translate, parse_gdal_options, get_output_cog_path
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
            - tiff_url: URL to remote TIFF file
            - gdal_options: Optional JSON string with GDAL creation options
    """
    parser = argparse.ArgumentParser(
        description="Convert TIFF files to Cloud Optimized GeoTIFF (COG) format"
    )
    parser.add_argument("--tiff_url", type=str, help="URL to remote TIFF file")
    parser.add_argument(
        "--gdal_options",
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
    """Main entry point for the TIFF to COG conversion script.

    Handles the workflow of:
    1. Parsing command line arguments
    2. Validating input URL
    3. Parsing optional GDAL options (uses defaults if not provided)
    4. Downloading TIFF file if from EODH workspace
    5. Validating downloaded file
    6. Converting TIFF to COG format with specified options
    7. Creating STAC catalog with metadata

    Raises:
        SystemExit: If required arguments are missing or any step fails
    """
    try:
        args = parse_args()

        if not args.tiff_url:
            logging.error("You must provide a --tiff_url")
            sys.exit(1)

        # Validate input URL before processing
        try:
            validate_input_url(args.tiff_url)
        except ValidationError as e:
            logging.error(f"Input validation failed: {e}")
            sys.exit(1)

        # Parse GDAL options (will use defaults if not provided)
        try:
            gdal_options = parse_gdal_options(args.gdal_options)
        except ValueError as e:
            logging.error(f"Invalid GDAL options: {e}")
            sys.exit(1)

        if "eodatahub-workspaces.org.uk" in args.tiff_url:
            # EODH workspace URL - parse and download from S3
            logging.info("EODH workspace URL - parsing and downloading from S3")
            bucket_name, key, tiff_url = parse_eodatahub_url(args.tiff_url)
            logging.info(f"Downloading from S3: {bucket_name}, {key}, {tiff_url}")
            download_file_from_s3(bucket_name, key, tiff_url)

            # Validate downloaded file
            try:
                validate_downloaded_file(tiff_url)
            except ValidationError as e:
                logging.error(f"Downloaded file validation failed: {e}")
                sys.exit(1)
        else:
            # Regular URL - use directly
            logging.info("Regular URL - using directly")
            tiff_url = args.tiff_url

        # Get output path and convert to COG with options
        logging.info(f"Tiff path: {tiff_url}")
        url_name = Path(tiff_url.split("?")[0]).name
        output_cog = get_output_cog_path(url_name)
        run_gdal_translate(tiff_url, output_cog, gdal_options)

        create_stac_catalog(output_cog)

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
