"""S3 utilities for downloading files from AWS S3."""

import logging
import os
import time
from typing import Tuple
import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


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

            # Download the file
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


def parse_eodatahub_url(url: str, download_dir: str = None) -> Tuple[str, str, str]:
    """Parse eodatahub-workspaces.org.uk URL to extract S3 bucket and key.

    Args:
        url: URL from eodatahub-workspaces.org.uk pointing to a TIFF file
        download_dir: Directory where the file will be downloaded (defaults to DOWNLOAD_DIR)

    Returns:
        Tuple containing:
            - bucket_name: Name of the S3 bucket
            - key: S3 object key (path within bucket)
            - local_tiff_path: Local path where the file will be downloaded
    """
    if download_dir is None:
        download_dir = os.environ.get("DOWNLOAD_DIR", "/tmp")
    logging.info(f"Parsing EODH URL: {url}")
    url_parts = url.split("/")
    files_idx = url_parts.index("files")
    bucket_name = url_parts[files_idx + 1]
    workspace_name = url_parts[2].split(".")[0]
    key = f"{workspace_name}/" + "/".join(url_parts[files_idx + 2 :])
    file_name = key.split("/")[-1]
    local_tiff_path = f"{download_dir}/{file_name}"
    logging.debug(
        {"bucket_name": bucket_name, "key": key, "local_tiff_path": local_tiff_path}
    )

    return bucket_name, key, local_tiff_path


