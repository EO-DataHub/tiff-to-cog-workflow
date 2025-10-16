cwlVersion: v1.2
$namespaces:
  s: https://schema.org/
s:softwareVersion: 0.1.2
schemas:
  - http://schema.org/version/9.0/schemaorg-current-http.rdf
$graph:
  - class: Workflow
    id: tiff-to-cog
    label: TIFF to COG Conversion Workflow
    doc: >
      Workflow to convert STAC item TIFF assets to Cloud Optimized GeoTIFF (COG) format and output a STAC catalog using a custom Python script in a Docker image.
    inputs:
      stac_item_url:
        type: string
        doc: URL to the STAC item JSON file
    requirements:
      ResourceRequirement:
        coresMax: 2
        ramMax: 4096
    outputs:
      - id: output_cog
        type: Directory
        outputSource:
          - tiff-to-cog-tool/output_cog
    steps:
      tiff-to-cog-tool:
        run: "#tiff-to-cog-tool"
        in:
          stac_item_url: stac_item_url
        out:
          - output_cog
  - class: CommandLineTool
    id: tiff-to-cog-tool
    label: TIFF to COG Conversion Tool
    doc: >
      Convert STAC item TIFF assets to Cloud Optimized GeoTIFF (COG) format and output a STAC catalog using a custom Python script in a Docker image.
    requirements:
      DockerRequirement:
        dockerPull: tif2cog:latest
      NetworkAccess:
        networkAccess: true
    baseCommand: [python, /usr/bin/main.py]
    inputs:
      stac_item_url:
        type: string
        inputBinding:
          position: 1
          prefix: --stac_item_url
        doc: URL to the STAC item JSON file
    outputs:
      output_cog:
        type: Directory
        outputBinding:
          glob: output_cog
        doc: Directory containing the output COG and STAC catalog

