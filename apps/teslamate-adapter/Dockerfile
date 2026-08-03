FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10002 pilot && useradd --uid 10002 --gid pilot --no-create-home pilot
COPY pyproject.toml ./
COPY teslamate_adapter ./teslamate_adapter
RUN pip install --no-cache-dir .
USER pilot
EXPOSE 8781
ENTRYPOINT ["pilot-teslamate-adapter"]
