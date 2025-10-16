"""STAC catalog creation utilities for GeoTIFF/COG files."""

import pystac
import datetime
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


def create_stac_catalog_from_item(
    source_stac_item: Dict[str, any],
    processed_assets: Dict[str, Dict[str, any]],
    output_dir: str,
) -> None:
    """Create a STAC catalog and item from a source STAC item with processed assets.

    Creates a STAC catalog containing an item based on the source STAC item,
    but with updated assets pointing to the processed files (COGs and copied assets).
    All metadata from the source item is preserved, with only asset hrefs and
    file sizes updated.

    Args:
        source_stac_item: Original STAC item dictionary
        processed_assets: Dictionary mapping asset keys to their processed file info
                         Each value should contain: {'href': str, 'size': int, 'type': str}
        output_dir: Directory where the STAC files will be saved

    Raises:
        Exception: If STAC creation fails
    """
    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(exist_ok=True)

    # Use source item ID or generate one
    item_id = source_stac_item.get("id", "processed_item")

    # Create catalog
    cat = pystac.Catalog(id="catalog", description="stac-item-to-cog-output")
    cat_path = output_dir_path / "catalog.json"
    cat.set_self_href(str(cat_path))

    # Copy properties from source item, updating timestamps
    properties = source_stac_item.get("properties", {}).copy()
    properties["created"] = pystac.utils.datetime_to_str(datetime.datetime.now())
    properties["updated"] = pystac.utils.datetime_to_str(datetime.datetime.now())

    # Create STAC item with source geometry, bbox, and datetime
    item = pystac.Item(
        id=item_id,
        geometry=source_stac_item.get("geometry"),
        bbox=source_stac_item.get("bbox"),
        datetime=source_stac_item.get("datetime", datetime.datetime.now()),
        properties=properties,
    )

    # Add STAC extensions from source item
    stac_extensions = source_stac_item.get("stac_extensions", [])
    if stac_extensions:
        item.stac_extensions = stac_extensions

    # Add processed assets
    for asset_key, asset_info in processed_assets.items():
        # Get original asset metadata
        original_asset = source_stac_item.get("assets", {}).get(asset_key, {})

        # Create new asset with updated href and file size
        new_asset = pystac.Asset(
            href=asset_info["href"],
            media_type=asset_info.get(
                "type", original_asset.get("type", "application/octet-stream")
            ),
            roles=original_asset.get("roles", ["data"]),
            title=original_asset.get("title"),
            description=original_asset.get("description"),
            extra_fields={"file:size": asset_info["size"]},
        )

        # Copy any additional fields from original asset
        for key, value in original_asset.items():
            if key not in ["href", "type", "roles", "title", "description"]:
                new_asset.extra_fields[key] = value

        item.add_asset(asset_key, new_asset)

    # Set the self_href for the item
    item_path = output_dir_path / f"{item_id}.json"
    item.set_self_href(str(item_path))

    cat.add_item(item)

    # Save catalog and item
    cat.save(
        catalog_type=pystac.CatalogType.SELF_CONTAINED, dest_href=str(output_dir_path)
    )

    logging.info(
        f"Created STAC catalog with {len(processed_assets)} assets in {output_dir}"
    )
