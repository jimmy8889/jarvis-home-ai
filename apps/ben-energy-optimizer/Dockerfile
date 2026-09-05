FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 10004 optimizer && useradd --uid 10004 --gid optimizer --no-create-home optimizer
COPY pyproject.toml ./
COPY ben_energy_optimizer ./ben_energy_optimizer
RUN pip install --no-cache-dir .
USER optimizer
EXPOSE 8786
ENTRYPOINT ["ben-energy-optimizer"]
