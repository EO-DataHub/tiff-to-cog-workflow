#!/usr/bin/env python3
"""
Test script for TIFF to COG CWL workflow.
Runs the workflow and validates generated STAC files.

To adapt this script for a different workflow, update the WORKFLOW_CONFIG dictionary:
- cwl_file: Name of your CWL workflow file
- workflow_id: ID of the workflow in the CWL file (found in the $graph section)
- input_param: Name of the input parameter
- test_input: Test value to pass to the workflow
- output_dir_name: Expected output directory name (optional, for reference)
"""

import sys
import os
import glob
import logging
import shutil
import tempfile
import argparse
from stac_validator import stac_validator
import cwltool.factory
import cwltool.main

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Configuration variables - update these to match your workflow
WORKFLOW_CONFIG = {
    "cwl_file": "tiff_to_cog.cwl",  # Name of the CWL workflow file
    "workflow_id": "tiff-to-cog",  # ID of the workflow in the CWL file
    "input_param": "tiff_url",  # Input parameter name
    "test_input": "https://download.osgeo.org/geotiff/samples/spot/chicago/UTM2GTIF.TIF",  # Test input value
    "gdal_options_param": "gdal_options",  # GDAL options parameter name
    "test_gdal_options": '{"COMPRESS":"ZSTD","BLOCKSIZE":"1024","OVERVIEW_RESAMPLING":"BILINEAR"}',  # Test GDAL options
    "output_dir_name": "output_cog",  # Expected output directory name
}


def run_cwl_workflow(test_input, gdal_options=None):
    """Run the CWL workflow using Python factory and return success status."""
    logger.info(f"🔄 Running CWL workflow with input '{test_input}'")
    if gdal_options:
        logger.info(f"🔄 Using GDAL options: {gdal_options}")

    try:
        # Setup CWL runtime
        runtime_context = cwltool.main.RuntimeContext()
        runtime_context.no_container = True
        fac = cwltool.factory.Factory(runtime_context=runtime_context)

        # Get paths
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cwl_path = os.path.join(script_dir, WORKFLOW_CONFIG["cwl_file"])
        output_dir = os.path.join(script_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Run workflow and capture outputs using temporary directory
        with tempfile.TemporaryDirectory(
            dir=output_dir, prefix="stac_output_"
        ) as temp_dir:
            runtime_context.outdir = temp_dir
            cwl_uri = f"file://{cwl_path}#{WORKFLOW_CONFIG['workflow_id']}"
            logger.debug(f"Using URI: {cwl_uri}")

            # Make and run the workflow
            workflow = fac.make(cwl_uri)

            # Prepare workflow inputs
            workflow_inputs = {WORKFLOW_CONFIG["input_param"]: test_input}
            if gdal_options:
                workflow_inputs[WORKFLOW_CONFIG["gdal_options_param"]] = gdal_options

            workflow(**workflow_inputs)

            # Copy generated files to persistent location
            persistent_dir = os.path.join(output_dir, "latest_run")
            if os.path.exists(persistent_dir):
                shutil.rmtree(persistent_dir)

            shutil.copytree(temp_dir, persistent_dir)

            logger.info("✅ CWL workflow completed successfully")
            logger.info(f"📁 Output location: {persistent_dir}")

            return True, persistent_dir, None

    except Exception as e:
        logger.error(f"❌ CWL workflow failed: {e}")
        logger.debug(f"Error details: {str(e)}")
        return False, None, str(e)


def find_stac_files(output_dir):
    """Find all JSON files in the output directory and subdirectories."""
    logger.debug(f"🔍 Searching for JSON files in: {output_dir}")

    # List all items in the output directory for debugging
    if os.path.exists(output_dir):
        logger.debug(f"📁 Contents of {output_dir}:")
        for item in os.listdir(output_dir):
            item_path = os.path.join(output_dir, item)
            if os.path.isdir(item_path):
                logger.debug(f"  📂 {item}/")
                # List contents of subdirectories
                try:
                    for subitem in os.listdir(item_path):
                        logger.debug(f"    📄 {subitem}")
                except PermissionError:
                    logger.debug("    (permission denied)")
            else:
                logger.debug(f"  📄 {item}")
    else:
        logger.debug(f"❌ Output directory does not exist: {output_dir}")

    # Search for JSON files recursively
    json_files = glob.glob(os.path.join(output_dir, "**", "*.json"), recursive=True)
    logger.debug(f"🔍 Found {len(json_files)} JSON files:")
    for json_file in json_files:
        logger.debug(f"  📄 {json_file}")

    return [f for f in json_files if os.path.isfile(f)]


def validate_stac_file(file_path):
    """Validate a single STAC file using stac-validator Python library."""
    logger.info(f"🔍 Validating {os.path.basename(file_path)}")

    try:
        # Use the Python stac-validator library
        stac = stac_validator.StacValidate(file_path)
        stac.run()

        # Check if validation was successful
        if stac.valid:
            logger.info(f"✅ {os.path.basename(file_path)} is valid STAC")
            return True
        else:
            logger.error(f"❌ {os.path.basename(file_path)} is invalid STAC")

            # Log validation errors if available
            if hasattr(stac, "message") and stac.message:
                logger.error(f"Validation message: {stac.message}")

            # Log detailed errors if available
            if hasattr(stac, "errors") and stac.errors:
                for error in stac.errors:
                    logger.error(f"Error: {error}")

            return False

    except Exception as e:
        logger.error(f"❌ Validation failed for {os.path.basename(file_path)}: {e}")
        return False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=f"Test script for {WORKFLOW_CONFIG['workflow_id']} CWL workflow"
    )
    parser.add_argument(
        "--input",
        type=str,
        default=WORKFLOW_CONFIG["test_input"],
        help=f"Test input value for {WORKFLOW_CONFIG['input_param']} parameter (default: {WORKFLOW_CONFIG['test_input']})",
    )
    parser.add_argument(
        "--gdal_options",
        type=str,
        default=WORKFLOW_CONFIG["test_gdal_options"],
        help=f"GDAL options as JSON string for {WORKFLOW_CONFIG['gdal_options_param']} parameter (default: {WORKFLOW_CONFIG['test_gdal_options']})",
    )
    parser.add_argument(
        "--no_gdal_options",
        action="store_true",
        help="Run without GDAL options (use defaults)",
    )
    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep output directory after test completion (for debugging)",
    )
    return parser.parse_args()


def main():
    """Main test function."""
    args = parse_args()

    logger.info(f"🧪 Testing {WORKFLOW_CONFIG['workflow_id']} CWL workflow")
    logger.info("=" * 50)

    # Check if cwltool Python library is available
    try:
        import importlib.util

        spec = importlib.util.find_spec("cwltool")
        if spec is None:
            raise ImportError("cwltool module not found")
        logger.info("✅ cwltool Python library is available")
    except ImportError:
        logger.error("❌ cwltool Python library not found. Please install it first.")
        sys.exit(1)

    # Check if stac-validator Python library is available
    try:
        import importlib.util

        spec = importlib.util.find_spec("stac_validator")
        if spec is None:
            raise ImportError("stac_validator module not found")
        logger.info("✅ stac-validator Python library is available")
    except ImportError:
        logger.error(
            "❌ stac-validator Python library not found. Please install it first."
        )
        sys.exit(1)

    # Run the CWL workflow
    test_input = args.input
    gdal_options = None if args.no_gdal_options else args.gdal_options

    success, output_dir, error = run_cwl_workflow(test_input, gdal_options)

    if not success:
        logger.error("❌ CWL workflow failed")
        if output_dir and os.path.exists(output_dir) and not args.keep_output:
            shutil.rmtree(output_dir)
        sys.exit(1)

    # Find and validate STAC files
    stac_files = find_stac_files(output_dir)

    if not stac_files:
        logger.warning("⚠️  No JSON files found in output directory")
        if output_dir and os.path.exists(output_dir) and not args.keep_output:
            shutil.rmtree(output_dir)
        sys.exit(1)

    logger.info(f"📋 Found {len(stac_files)} JSON files to validate:")
    for file_path in stac_files:
        logger.info(f"  - {os.path.basename(file_path)}")

    # Validate each STAC file
    logger.info("🔍 Validating STAC files...")
    all_valid = True

    for file_path in stac_files:
        if not validate_stac_file(file_path):
            all_valid = False

    # Summary
    logger.info("=" * 50)
    if all_valid:
        logger.info("🎉 All tests passed! Workflow and STAC validation successful.")
        if output_dir and os.path.exists(output_dir) and not args.keep_output:
            shutil.rmtree(output_dir)
        elif args.keep_output:
            logger.info(f"📁 Output kept at: {output_dir}")
        sys.exit(0)
    else:
        logger.error("❌ Some tests failed. Check the output above for details.")
        if output_dir and os.path.exists(output_dir) and not args.keep_output:
            shutil.rmtree(output_dir)
        elif args.keep_output:
            logger.info(f"📁 Output kept at: {output_dir}")
        sys.exit(1)


if __name__ == "__main__":
    main()
