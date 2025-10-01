"""Input validation utilities for TIFF to COG conversion."""

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


# Constants for validation
ALLOWED_URL_SCHEMES = {"http", "https", "s3"}
ALLOWED_FILE_EXTENSIONS = {".tif", ".tiff", ".gtiff", ".geotiff"}
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB
BLOCKED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "localhost.localdomain",
}


class ValidationError(Exception):
    """Custom exception for validation errors."""

    pass


def validate_url_scheme(url: str) -> None:
    """Validate that the URL uses an allowed scheme.

    Args:
        url: URL to validate

    Raises:
        ValidationError: If URL scheme is not allowed
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValidationError(f"Invalid URL format: {e}")

    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise ValidationError(
            f"URL scheme '{parsed.scheme}' not allowed. "
            f"Allowed schemes: {', '.join(ALLOWED_URL_SCHEMES)}"
        )


def validate_url_ssrf(url: str) -> None:
    """Validate URL to prevent Server-Side Request Forgery (SSRF) attacks.

    Checks for:
    - Localhost access attempts
    - Private IP ranges (10.x.x.x, 172.16.x.x, 192.168.x.x, 169.254.x.x)
    - Suspicious patterns (.., multiple //)

    Args:
        url: URL to validate

    Raises:
        ValidationError: If URL appears to be a SSRF attempt
    """
    parsed = urlparse(url)

    # Check for blocked hostnames
    if parsed.hostname and parsed.hostname.lower() in BLOCKED_HOSTS:
        raise ValidationError(
            f"Access to {parsed.hostname} is not allowed (security: SSRF protection)"
        )

    # Check for private IP ranges (basic check)
    if parsed.hostname and any(
        parsed.hostname.startswith(prefix)
        for prefix in (
            "10.",
            "172.16.",
            "172.17.",
            "172.18.",
            "172.19.",
            "172.20.",
            "172.21.",
            "172.22.",
            "172.23.",
            "172.24.",
            "172.25.",
            "172.26.",
            "172.27.",
            "172.28.",
            "172.29.",
            "172.30.",
            "172.31.",
            "192.168.",
            "169.254.",
        )
    ):
        raise ValidationError(
            "Access to private IP ranges is not allowed (security: SSRF protection)"
        )

    # Check for suspicious patterns
    if ".." in url:
        raise ValidationError(
            "URL contains suspicious pattern '..' (security: path traversal)"
        )

    if url.count("//") > 1:
        raise ValidationError(
            "URL contains suspicious pattern '//' (security: double slash)"
        )


def validate_eodh_url(url: str) -> None:
    """Validate EODH workspace URL format.

    Expected format: https://<workspace>.eodatahub-workspaces.org.uk/files/<bucket>/<path>

    Args:
        url: EODH URL to validate

    Raises:
        ValidationError: If URL doesn't match expected EODH format
    """
    if "eodatahub-workspaces.org.uk" not in url:
        return  # Not an EODH URL, skip validation

    try:
        url_parts = url.split("/")
        if "files" not in url_parts:
            raise ValidationError(
                "EODH URL must contain '/files/' in path. "
                "Expected format: https://<workspace>.eodatahub-workspaces.org.uk/files/<bucket>/<path>"
            )
    except Exception as e:
        raise ValidationError(f"Invalid EODH URL format: {e}")


def validate_url(url: str) -> None:
    """Comprehensive URL validation.

    Performs multiple validation checks:
    - Non-empty string
    - Valid URL format
    - Allowed URL scheme
    - SSRF protection
    - EODH-specific format validation (if applicable)

    Args:
        url: URL to validate

    Raises:
        ValidationError: If any validation check fails
    """
    if not url or not isinstance(url, str):
        raise ValidationError("URL must be a non-empty string")

    # Strip whitespace
    url = url.strip()

    validate_url_scheme(url)
    validate_url_ssrf(url)
    validate_eodh_url(url)

    logging.debug(f"URL validation passed: {url}")


def validate_file_extension(filename: str) -> None:
    """Validate that the file has an allowed TIFF extension.

    Args:
        filename: Name or path of the file

    Raises:
        ValidationError: If file extension is not allowed
    """
    path = Path(filename)
    extension = path.suffix.lower()

    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise ValidationError(
            f"File extension '{extension}' not allowed. "
            f"Allowed extensions: {', '.join(ALLOWED_FILE_EXTENSIONS)}"
        )

    logging.debug(f"File extension validation passed: {extension}")


def validate_file_size(filepath: str, max_size: int = MAX_FILE_SIZE) -> None:
    """Validate that the file size is within limits.

    Args:
        filepath: Path to the file
        max_size: Maximum allowed file size in bytes (default: 10GB)

    Raises:
        ValidationError: If file is too large or not found
    """
    try:
        size = Path(filepath).stat().st_size
        if size > max_size:
            size_mb = size / (1024 * 1024)
            max_mb = max_size / (1024 * 1024)
            raise ValidationError(
                f"File too large: {size_mb:.2f} MB exceeds limit of {max_mb:.2f} MB"
            )
        logging.debug(f"File size validation passed: {size / (1024 * 1024):.2f} MB")
    except FileNotFoundError:
        raise ValidationError(f"File not found: {filepath}")
    except OSError as e:
        raise ValidationError(f"Cannot access file {filepath}: {e}")


def validate_tiff_magic_bytes(filepath: str) -> None:
    """Validate that the file is a valid TIFF by checking magic bytes.

    TIFF files start with either:
    - II (0x4949) for little-endian, followed by 42 (0x002A)
    - MM (0x4D4D) for big-endian, followed by 42 (0x2A00)

    Args:
        filepath: Path to the file to validate

    Raises:
        ValidationError: If file is not a valid TIFF
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(4)

            if len(header) < 4:
                raise ValidationError(
                    f"File too small to be a valid TIFF (only {len(header)} bytes)"
                )

            # Check for TIFF magic bytes
            if header[:2] == b"II" and header[2:4] == b"\x2a\x00":
                logging.debug("Valid TIFF file detected (little-endian)")
                return
            elif header[:2] == b"MM" and header[2:4] == b"\x00\x2a":
                logging.debug("Valid TIFF file detected (big-endian)")
                return
            else:
                raise ValidationError(
                    f"File does not appear to be a valid TIFF. "
                    f"Magic bytes: {header.hex()} (expected: II2A00 or MM002A)"
                )
    except FileNotFoundError:
        raise ValidationError(f"File not found: {filepath}")
    except PermissionError:
        raise ValidationError(f"Permission denied reading file: {filepath}")
    except Exception as e:
        raise ValidationError(f"Error reading file {filepath}: {e}")


def validate_input_url(url: str) -> None:
    """Validate input URL before processing.

    Performs URL validation and file extension check.

    Args:
        url: URL to the TIFF file

    Raises:
        ValidationError: If any validation fails
    """
    validate_url(url)

    # Extract filename from URL (remove query parameters)
    url_path = url.split("?")[0]
    validate_file_extension(url_path)

    logging.info(f"Input URL validation passed: {url}")


def validate_downloaded_file(filepath: str, max_size: Optional[int] = None) -> None:
    """Validate a downloaded file.

    Performs file size check and TIFF magic bytes validation.

    Args:
        filepath: Path to the downloaded file
        max_size: Maximum allowed file size in bytes (default: 10GB)

    Raises:
        ValidationError: If any validation fails
    """
    if max_size is None:
        max_size = MAX_FILE_SIZE

    validate_file_size(filepath, max_size)
    validate_tiff_magic_bytes(filepath)

    logging.info(f"Downloaded file validation passed: {filepath}")
