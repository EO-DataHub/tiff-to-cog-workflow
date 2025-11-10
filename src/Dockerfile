FROM ghcr.io/osgeo/gdal:ubuntu-small-latest

LABEL authors="Sparkgeo UK"

# AWS credentials as build arguments
ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ARG AWS_SESSION_TOKEN
ARG AWS_DEFAULT_REGION

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-gdal \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
ADD app/requirements.txt /tmp/requirements.txt

RUN python3 -m venv --system-site-packages /venv && \
    . /venv/bin/activate && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Copy application code
COPY . /usr/bin/
RUN chmod +x /usr/bin/*.py

ENV PATH="/venv/bin:$PATH"

# Set AWS credentials as environment variables (available at runtime)
ENV AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
ENV AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
ENV AWS_SESSION_TOKEN=${AWS_SESSION_TOKEN}
ENV AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION}

WORKDIR /
