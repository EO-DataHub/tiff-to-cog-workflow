"""Input validation utilities for TIFF to COG conversion."""

import logging
from pathlib import Path

# Constants for validation
MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB


class ValidationError(Exception):
    """Custom exception for validation errors."""

    pass


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
            raise ValidationError(f"File too large: {size_mb:.2f} MB exceeds limit of {max_mb:.2f} MB")
        logging.debug(f"File size validation passed: {size / (1024 * 1024):.2f} MB")
    except FileNotFoundError as e:
        raise ValidationError(f"File not found: {filepath}") from e
    except OSError as e:
        raise ValidationError(f"Cannot access file {filepath}: {e}") from e


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
                raise ValidationError(f"File too small to be a valid TIFF (only {len(header)} bytes)")

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
    except FileNotFoundError as e:
        raise ValidationError(f"File not found: {filepath}") from e
    except PermissionError as e:
        raise ValidationError(f"Permission denied reading file: {filepath}") from e
    except Exception as e:
        raise ValidationError(f"Error reading file {filepath}: {e}") from e


def validate_downloaded_file(filepath: str, max_size: int | None = None) -> None:
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
