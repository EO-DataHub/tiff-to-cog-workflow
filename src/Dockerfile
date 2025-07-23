FROM ghcr.io/osgeo/gdal:alpine-normal-latest AS builder
LABEL authors="Sparkgeo UK"

RUN apk add --no-cache python3 py3-pip

ADD app/requirements.txt /tmp/requirements.txt


RUN python3 -m venv /venv && \
    . /venv/bin/activate && \
    pip install --no-cache-dir -r /tmp/requirements.txt


COPY . /usr/bin/
RUN chmod +x /usr/bin/*.py

FROM ghcr.io/osgeo/gdal:alpine-normal-latest
COPY --from=builder /venv /venv
COPY --from=builder /usr/bin /usr/bin

ENV PATH="/venv/bin:$PATH"

WORKDIR /usr/bin