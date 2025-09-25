import pystac
import datetime
import os
import argparse
from pathlib import Path
import pystac.utils
import sys
import logging
import subprocess
import boto3

logging.basicConfig(
    level=logging.DEBUG, format="[%(levelname)s] %(message)s", stream=sys.stderr
)


def download_file_from_s3(bucket_name, key, output_path):
    s3 = boto3.client("s3")
    s3.download_file(bucket_name, key, output_path)


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


def parse_eodatahub_url(url):
    """Parse eodatahub-workspaces.org.uk URL to extract S3 bucket and key"""
    url_parts = url.split("/")
    files_idx = url_parts.index("files")
    bucket_name = url_parts[files_idx + 1]
    workspace_name = url_parts[2].split(".")[0]
    key = f"{workspace_name}/" + "/".join(url_parts[files_idx + 2 :])
    file_name = key.split("/")[-1]
    local_tiff_path = f"/tmp/{file_name}"

    return bucket_name, key, local_tiff_path


def main():
    try:
        args = parse_args()

        if args.tiff_url:
            if "eodatahub-workspaces.org.uk" in args.tiff_url:
                # EODH workspace URL - parse and download from S3
                logging.info("EODH workspace URL - parsing and downloading from S3")
                bucket_name, key, tiff_url = parse_eodatahub_url(args.tiff_url)
                logging.info(f"Bucket: {bucket_name}")
                logging.info(f"Key: {key}")
                logging.info(f"Tiff URL: {tiff_url}")
                download_file_from_s3(bucket_name, key, tiff_url)
            else:
                # Regular URL - use directly
                logging.info("Regular URL - using directly")
                tiff_url = args.tiff_url

            # Get output path and convert to COG
            logging.info(f"Tiff URL: {tiff_url}")
            url_name = Path(tiff_url.split("?")[0]).name
            output_cog = get_output_cog_path(url_name)
            run_gdal_translate(tiff_url, output_cog)
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
