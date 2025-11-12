"""Chunking utilities for memory-efficient TIFF to COG conversion."""

import logging
import time
import math
from typing import Dict, List, Any
import rasterio
from rasterio.windows import Window

# Type alias for rasterio dataset writer
# Using Any to avoid import issues with rasterio versions that don't expose DatasetWriter
DatasetWriter = Any

# Default chunk size configuration
CHUNK_SIZE_MB = 100
COG_BLOCK_SIZE = 512


def calculate_chunk_size(raster_metadata: Dict) -> Dict:
    """Calculate chunk size based on MB-based configuration.

    Converts CHUNK_SIZE_MB to pixels based on raster metadata and rounds to COG block size boundaries.

    Args:
        raster_metadata: Raster metadata dictionary with keys:
            - width (int): Raster width in pixels
            - height (int): Raster height in pixels
            - bands (int): Number of bands
            - data_type (str): Data type (e.g., "uint8", "float32")
            - bytes_per_pixel (int): Bytes per pixel

    Returns:
        Dictionary with keys:
        - chunk_width (int): Chunk width in pixels
        - chunk_height (int): Chunk height in pixels
        - num_chunks_x (int): Number of chunks in X direction
        - num_chunks_y (int): Number of chunks in Y direction
        - total_chunks (int): Total number of chunks

    Raises:
        ValueError: If chunk size cannot be calculated

    Example:
        >>> metadata = {"width": 10000, "height": 10000, "bands": 3, "data_type": "uint8", "bytes_per_pixel": 1}
        >>> chunk_config = calculate_chunk_size(metadata)
        >>> print(f"Chunk size: {chunk_config['chunk_width']}x{chunk_config['chunk_height']}")
    """
    width = raster_metadata["width"]
    height = raster_metadata["height"]
    bands = raster_metadata["bands"]
    bytes_per_pixel = raster_metadata["bytes_per_pixel"]

    # Hardcoded configuration
    cog_block_size = COG_BLOCK_SIZE
    chunk_size_mb = CHUNK_SIZE_MB

    # Convert MB to pixels
    # Calculate bytes per pixel (all bands)
    bytes_per_pixel_total = bands * bytes_per_pixel

    # Calculate pixels per chunk based on MB size
    chunk_size_bytes = chunk_size_mb * 1024 * 1024
    pixels_per_chunk = chunk_size_bytes / bytes_per_pixel_total

    # Calculate square chunk dimension
    chunk_dimension = int(math.sqrt(pixels_per_chunk))

    # Round down to nearest multiple of COG block size
    chunk_dimension = (chunk_dimension // cog_block_size) * cog_block_size

    # Ensure minimum chunk size (at least one block)
    if chunk_dimension < cog_block_size:
        chunk_dimension = cog_block_size

    # Ensure chunk doesn't exceed raster dimensions
    chunk_width = min(chunk_dimension, width)
    chunk_height = min(chunk_dimension, height)

    # Calculate number of chunks
    num_chunks_x = int(math.ceil(width / chunk_width))
    num_chunks_y = int(math.ceil(height / chunk_height))
    total_chunks = num_chunks_x * num_chunks_y

    logging.info(
        f"Calculated chunk size: {chunk_width}x{chunk_height} pixels, "
        f"{total_chunks} chunks ({num_chunks_x}x{num_chunks_y})"
    )

    return {
        "chunk_width": chunk_width,
        "chunk_height": chunk_height,
        "num_chunks_x": num_chunks_x,
        "num_chunks_y": num_chunks_y,
        "total_chunks": total_chunks,
    }


def create_chunks(raster_metadata: Dict, chunk_size: Dict) -> List[Dict]:
    """Create list of chunk/window objects for processing.

    Creates window objects for each chunk based on chunk size configuration,
    assigning sequential chunk IDs and processing order.

    Args:
        raster_metadata: Raster metadata dictionary with width and height
        chunk_size: Chunk size configuration dictionary from calculate_chunk_size()

    Returns:
        List of chunk dictionaries, each with keys:
        - chunk_id (int): Unique chunk identifier (sequential)
        - window (rasterio.windows.Window): Window object
        - x_offset (int): X offset in pixels
        - y_offset (int): Y offset in pixels
        - width (int): Chunk width
        - height (int): Chunk height
        - processing_order (int): Processing order (sequential, same as chunk_id)

    Raises:
        ValueError: If chunk dimensions are invalid

    Example:
        >>> metadata = {"width": 10000, "height": 10000}
        >>> chunk_config = {"chunk_width": 512, "chunk_height": 512, "num_chunks_x": 20, "num_chunks_y": 20}
        >>> chunks = create_chunks(metadata, chunk_config)
        >>> print(f"Created {len(chunks)} chunks")
    """
    width = raster_metadata["width"]
    height = raster_metadata["height"]
    chunk_width = chunk_size["chunk_width"]
    chunk_height = chunk_size["chunk_height"]
    num_chunks_x = chunk_size["num_chunks_x"]
    num_chunks_y = chunk_size["num_chunks_y"]

    if chunk_width <= 0 or chunk_height <= 0:
        raise ValueError("Chunk dimensions must be positive")

    if chunk_width > width or chunk_height > height:
        raise ValueError(
            f"Chunk dimensions ({chunk_width}x{chunk_height}) exceed raster dimensions ({width}x{height})"
        )

    chunks = []
    chunk_id = 0

    for y_idx in range(num_chunks_y):
        for x_idx in range(num_chunks_x):
            # Calculate chunk boundaries
            x_offset = x_idx * chunk_width
            y_offset = y_idx * chunk_height

            # Calculate actual chunk size (may be smaller at edges)
            actual_width = min(chunk_width, width - x_offset)
            actual_height = min(chunk_height, height - y_offset)

            # Skip empty chunks
            if actual_width <= 0 or actual_height <= 0:
                continue

            # Create window object
            window = Window(x_offset, y_offset, actual_width, actual_height)

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "window": window,
                    "x_offset": x_offset,
                    "y_offset": y_offset,
                    "width": actual_width,
                    "height": actual_height,
                    "processing_order": chunk_id,
                    "total_chunks": num_chunks_x * num_chunks_y,
                }
            )

            chunk_id += 1

    logging.info(f"Created {len(chunks)} chunks for processing")
    return chunks


def create_output_cog_dataset(output_path: str, raster_metadata: Dict) -> DatasetWriter:
    """Create output COG dataset with proper profile.

    Creates a new COG-compatible GeoTIFF file with tiled structure and compression.
    The dataset is returned open and ready for windowed writing. Uses default GDAL options.

    Args:
        output_path: Path to output COG file
        raster_metadata: Raster metadata dictionary with width, height, bands, data_type, crs, transform

    Returns:
        Open rasterio DatasetWriter ready for writing

    Raises:
        RuntimeError: If dataset creation fails

    Example:
        >>> metadata = {"width": 10000, "height": 10000, "bands": 3, "data_type": "uint8", "crs": "EPSG:4326", "transform": [...]}
        >>> dst = create_output_cog_dataset("output.tif", metadata)
        >>> # Write chunks to dst
        >>> dst.close()
    """
    # Use default GDAL options
    block_size = 512  # Default BLOCKSIZE
    compress = "LZW"  # Default COMPRESS

    # Map data type string to numpy dtype
    dtype_map = {
        "uint8": "uint8",
        "int8": "int8",
        "uint16": "uint16",
        "int16": "int16",
        "uint32": "uint32",
        "int32": "int32",
        "float32": "float32",
        "float64": "float64",
    }
    dtype = dtype_map.get(raster_metadata["data_type"], "float32")

    # Create profile for COG-compatible GeoTIFF
    profile = {
        "driver": "GTiff",
        "width": raster_metadata["width"],
        "height": raster_metadata["height"],
        "count": raster_metadata["bands"],
        "dtype": dtype,
        "crs": raster_metadata.get("crs"),
        "transform": raster_metadata.get("transform"),
        "compress": compress,
        "blockxsize": block_size,
        "blockysize": block_size,
        "tiled": True,
        "interleave": "band",
    }

    # Add predictor if using compression that supports it
    if compress in ["LZW", "DEFLATE", "ZSTD"]:
        if dtype in ["float32", "float64"]:
            profile["predictor"] = 3  # Floating point predictor
        else:
            profile["predictor"] = 2  # Horizontal predictor

    try:
        dst = rasterio.open(output_path, "w", **profile)
        logging.info(f"Created output COG dataset: {output_path}")
        return dst
    except Exception as e:
        error_msg = f"Failed to create output COG dataset {output_path}: {e}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def process_chunk(
    source_path: str,
    chunk: Dict,
    output_dataset: DatasetWriter,
) -> Dict:
    """Process a single chunk and write it to the output COG file.

    Reads chunk data from source file using rasterio windowed reading and writes
    to output COG dataset.

    Args:
        source_path: Path to source TIFF file (local or URL)
        chunk: Chunk dictionary with window information
        output_dataset: Open rasterio DatasetWriter for output COG file

    Returns:
        Dictionary with keys:
        - chunk_id (int): Chunk identifier
        - status (str): Processing status ("completed" or "failed")
        - processing_time_seconds (float): Processing time in seconds

    Raises:
        RuntimeError: If chunk processing fails

    Example:
        >>> chunk = {"chunk_id": 0, "window": Window(0, 0, 512, 512), ...}
        >>> result = process_chunk("input.tif", chunk, output_dst)
        >>> print(f"Chunk {result['chunk_id']} status: {result['status']}")
    """
    chunk_id = chunk["chunk_id"]
    window = chunk["window"]
    start_time = time.time()

    try:
        # Read chunk data from source using windowed reading
        with rasterio.open(source_path) as src:
            # Read windowed data (all bands)
            # window parameter limits memory usage to the chunk only
            chunk_data = src.read(window=window)

        # Write chunk data to output dataset using windowed writing
        output_dataset.write(chunk_data, window=window)

        processing_time = time.time() - start_time

        logging.info(
            f"Processed chunk {chunk_id}/{chunk.get('total_chunks', '?')}: "
            f"{chunk['width']}x{chunk['height']} pixels, "
            f"time: {processing_time:.2f}s"
        )

        return {
            "chunk_id": chunk_id,
            "status": "completed",
            "processing_time_seconds": processing_time,
        }

    except Exception as e:
        error_msg = f"Failed to process chunk {chunk_id}: {e}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
