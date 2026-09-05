FROM python:3.13-slim@sha256:6771159cd4fa5d9bba1258caf0b82e6b73458c694d178ad97c5e925c2d0e1a91

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10003 optimizer && useradd --uid 10003 --gid optimizer --no-create-home optimizer
RUN pip install --no-cache-dir uv==0.9.18
COPY pyproject.toml uv.lock ./
COPY energy_optimizer ./energy_optimizer
RUN uv sync --locked --no-dev --no-editable
USER optimizer
EXPOSE 8785
ENTRYPOINT ["pilot-energy-optimizer"]
