# syntax=docker/dockerfile:1@sha256:572cebbc2b15e6f84c077742952674889cb63cd5e9b80abdffcbe587b6f19183
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.6.3@sha256:bfa7915a3ef942b4f6f61223ee57eadbb469d6fb4a5fbf562286d1473f15eaab

LABEL authors="Sparkgeo UK"

# Get uv from the official image
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /uvx /bin/

# AWS credentials as build arguments
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_SESSION_TOKEN
ARG AWS_DEFAULT_REGION

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies globally into system Python
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv pip install --system --requirement pyproject.toml

WORKDIR /app

# Copy application code
COPY . /app

# Set AWS credentials as environment variables (available at runtime)
ENV AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
ENV AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
ENV AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN}
ENV AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}

CMD ["python", "-m", "tiff_to_cog_workflow.main"]