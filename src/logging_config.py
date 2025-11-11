"""Logging configuration for the TIFF to COG conversion script."""

import logging
import sys


def setup_logging() -> None:
    """Configure logging for the application.

    Sets up basic logging configuration with DEBUG level and suppresses
    verbose logs from third-party libraries (boto3, botocore, s3transfer, urllib3).
    """
    logging.basicConfig(
        level=logging.DEBUG, format="[%(levelname)s] %(message)s", stream=sys.stderr
    )

    # Suppress verbose boto3 and s3transfer logs
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
