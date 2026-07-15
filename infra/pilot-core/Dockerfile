FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --create-home pilot \
    && mkdir -p /data \
    && chown pilot:pilot /data
WORKDIR /app
COPY apps/pilot-core /app/apps/pilot-core
RUN python -m pip install --no-cache-dir /app/apps/pilot-core

USER pilot
EXPOSE 8770
CMD ["pilot-core", "--config", "/config/core.toml"]
