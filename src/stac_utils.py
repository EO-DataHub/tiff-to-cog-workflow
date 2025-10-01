"""STAC catalog creation utilities for GeoTIFF/COG files."""

import pystac
import datetime
import os
from pathlib import Path
import pystac.utils
import logging
import rasterio
from rasterio.warp import transform_geom
from shapely.geometry import box, mapping
from typing import Dict, Any


def extract_geotiff_metadata(cog_path: str) -> Dict[str, Any]:
    """Extract spatial and metadata information from a GeoTIFF file.

    Args:
        cog_path: Path to the GeoTIFF file

    Returns:
        Dictionary containing geometry, bbox, crs, and other metadata including:
            - geometry: GeoJSON geometry in WGS84
            - bbox: Bounding box in WGS84 [minx, miny, maxx, maxy]
            - crs: Coordinate reference system string
            - width: Raster width in pixels
            - height: Raster height in pixels
            - count: Number of bands
            - dtype: Data type of the bands
            - transform: Affine transform parameters (6 values)
            - epsg: EPSG code (if available)
    """
    with rasterio.open(cog_path) as src:
        # Get bounds in the file's CRS
        bounds = src.bounds

        # Create a bounding box polygon in the source CRS
        bbox_geom = box(bounds.left, bounds.bottom, bounds.right, bounds.top)

        # Transform to WGS84 (EPSG:4326) for STAC
        geom_4326 = transform_geom(src.crs, "EPSG:4326", mapping(bbox_geom))

        # Get bbox in WGS84
        bbox_shape = box(
            *rasterio.warp.transform_bounds(
                src.crs,
                "EPSG:4326",
                bounds.left,
                bounds.bottom,
                bounds.right,
                bounds.top,
            )
        )
        bbox_4326 = list(bbox_shape.bounds)

        metadata = {
            "geometry": geom_4326,
            "bbox": bbox_4326,
            "crs": src.crs.to_string() if src.crs else None,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": str(src.dtypes[0]),
            "transform": list(src.transform)[:6],  # Affine transform parameters
        }

        # Add projection information if available
        if src.crs:
            try:
                metadata["epsg"] = src.crs.to_epsg()
            except Exception:
                metadata["epsg"] = None

        logging.info(
            f"Extracted metadata: CRS={metadata['crs']}, "
            f"Dimensions={metadata['width']}x{metadata['height']}, "
            f"Bands={metadata['count']}"
        )

        return metadata


def create_stac_catalog(cog_path: str) -> None:
    """Create a STAC catalog and item with real metadata from the COG file.

    Creates a STAC catalog containing a single item representing the COG file.
    The catalog and item JSON files are saved in the same directory as the COG.
    All metadata is extracted from the actual file including projection, spatial
    resolution, and band information.

    Args:
        cog_path: Path to the Cloud Optimized GeoTIFF file

    Raises:
        Exception: If metadata extraction fails
    """
    output_dir = Path(cog_path).parent  # This will be 'output_cog'
    name = Path(cog_path).stem

    # Extract real metadata from the GeoTIFF
    try:
        metadata = extract_geotiff_metadata(cog_path)
    except Exception as e:
        logging.error(f"Failed to extract GeoTIFF metadata: {e}")
        raise

    # Create catalog
    cat = pystac.Catalog(id="catalog", description="tiff-to-cog-output")
    # Set the self_href for the catalog
    cat_path = output_dir / "catalog.json"
    cat.set_self_href(str(cat_path))

    # Create properties with additional metadata
    properties = {
        "created": pystac.utils.datetime_to_str(datetime.datetime.now()),
        "updated": pystac.utils.datetime_to_str(datetime.datetime.now()),
    }

    # Add projection extension properties if EPSG code is available
    if metadata.get("epsg"):
        properties["proj:epsg"] = metadata["epsg"]
    if metadata.get("crs"):
        properties["proj:wkt2"] = metadata["crs"]

    # Add proj:shape (height, width) and proj:transform
    properties["proj:shape"] = [metadata["height"], metadata["width"]]
    properties["proj:transform"] = metadata["transform"]

    # Calculate spatial resolution from the transform
    # Transform[0] is pixel width, transform[4] is pixel height (usually negative)
    spatial_resolution = abs(metadata["transform"][0])

    # Add raster metadata
    properties["raster:bands"] = [
        {
            "data_type": metadata["dtype"],
            "spatial_resolution": spatial_resolution,
        }
        for _ in range(metadata["count"])
    ]

    # Create STAC item with real geometry and bbox
    item = pystac.Item(
        id=name,
        geometry=metadata["geometry"],
        bbox=metadata["bbox"],
        datetime=datetime.datetime.now(),
        properties=properties,
    )
    item.add_asset(
        name,
        pystac.Asset(
            href=str(Path(cog_path).name),
            media_type=pystac.MediaType.GEOTIFF,
            roles=["data"],
            extra_fields={"file:size": os.path.getsize(cog_path)},
        ),
    )
    # Set the self_href for the item
    item_path = output_dir / f"{name}.json"
    item.set_self_href(str(item_path))
    cat.add_item(item)
    # Save catalog and item flat in output_cog
    cat.save(catalog_type=pystac.CatalogType.SELF_CONTAINED, dest_href=str(output_dir))
