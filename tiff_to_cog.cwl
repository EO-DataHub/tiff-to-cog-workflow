cwlVersion: v1.2
$namespaces:
  s: https://schema.org/
s:softwareVersion: 0.0.2
schemas:
  - http://schema.org/version/9.0/schemaorg-current-http.rdf
$graph:
  - class: Workflow
    id: tiff-to-cog
    label: TIFF to COG Conversion Workflow
    doc: >
      Workflow to convert a remote TIFF file to a Cloud Optimized GeoTIFF (COG) and output a STAC catalog using a custom Python script in a Docker image.
    inputs:
      tiff_url:
        type: string
        doc: URL to the remote TIFF file
    outputs:
      - id: output_cog
        type: Directory
        outputSource:
          - tiff-to-cog-tool/output_cog
    steps:
      tiff-to-cog-tool:
        run: "#tiff-to-cog-tool"
        in:
          tiff_url: tiff_url
        out:
          - output_cog
  - class: CommandLineTool
    id: tiff-to-cog-tool
    label: TIFF to COG Conversion Tool
    doc: >
      Convert a remote TIFF file to a Cloud Optimized GeoTIFF (COG) and output a STAC catalog using a custom Python script in a Docker image.
    requirements:
      DockerRequirement:
        dockerPull: tif2cog:latest
      NetworkAccess:
        networkAccess: true
    baseCommand: [python, /usr/bin/main.py]
    inputs:
      tiff_url:
        type: string
        inputBinding:
          position: 1
          prefix: --tiff_url
        doc: URL to the remote TIFF file
    outputs:
      output_cog:
        type: Directory
        outputBinding:
          glob: output_cog
        doc: Directory containing the output COG and STAC catalog

