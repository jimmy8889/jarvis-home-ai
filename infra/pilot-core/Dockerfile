FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10001 pilot \
    && useradd --system --uid 10001 --gid 10001 --create-home pilot \
    && mkdir -p /data \
    && chown pilot:pilot /data
WORKDIR /app
COPY apps/pilot-core /app/apps/pilot-core
COPY infra/pilot-core/volume_archive.py /opt/pilot-tools/volume_archive.py
RUN python -m pip install --no-cache-dir /app/apps/pilot-core

USER pilot
EXPOSE 8770
CMD ["pilot-core", "--config", "/config/core.toml"]
