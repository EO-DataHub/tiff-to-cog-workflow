import pystac
import datetime
import os
import argparse
from pathlib import Path
import pystac.utils
import sys
import logging
import subprocess

logging.basicConfig(
    level=logging.DEBUG, format="[%(levelname)s] %(message)s", stream=sys.stderr
)


def run_gdal_translate(tiff_url, output_path):
    cmd = [
        "gdal_translate",
        f"/vsicurl/{tiff_url}",
        output_path,
        "-of",
        "COG",
        "-co",
        "COMPRESS=LZW",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"GDAL conversion failed: {e}")
        sys.exit(1)


def create_stac_catalog(cog_path):
    output_dir = Path(cog_path).parent  # This will be 'output_cog'
    name = Path(cog_path).stem
    cat = pystac.Catalog(id="catalog", description="tiff-to-cog-output")
    # Set the self_href for the catalog
    cat_path = output_dir / "catalog.json"
    cat.set_self_href(str(cat_path))
    item = pystac.Item(
        id=name,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[-180, -90], [-180, 90], [180, 90], [180, -90], [-180, -90]]
            ],
        },
        bbox=None,
        datetime=datetime.datetime.now(),
        properties={
            "created": pystac.utils.datetime_to_str(datetime.datetime.now()),
            "updated": pystac.utils.datetime_to_str(datetime.datetime.now()),
        },
        extra_fields={"bbox": [-180, -90, 180, 90]},
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


def get_output_cog_path(input_path):
    input_path = Path(input_path)
    output_dir = Path("output_cog")
    output_dir.mkdir(exist_ok=True)
    new_name = input_path.stem + "_cog" + input_path.suffix
    return str(output_dir / new_name)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiff_url", type=str, help="URL to remote TIFF file")
    return parser.parse_args()


def main():
    try:
        args = parse_args()

        if args.tiff_url:
            # Derive output path from URL
            url_name = Path(args.tiff_url.split("?")[0]).name
            output_cog = get_output_cog_path(url_name)
            run_gdal_translate(args.tiff_url, output_cog)
        else:
            logging.error("You must provide a --tiff_url")
            sys.exit(1)

        create_stac_catalog(output_cog)
    except Exception as e:
        logging.error(f"Exception occurred: {e}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
