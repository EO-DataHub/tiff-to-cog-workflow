FROM ghcr.io/osgeo/gdal:ubuntu-small-latest

LABEL authors="Sparkgeo UK"

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

WORKDIR /usr/bin
