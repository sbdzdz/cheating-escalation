FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.7.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/*
RUN uv pip install --system --no-cache numpy sympy mpmath matplotlib pillow==12.3.0 requests==2.34.2 pyyaml==6.0.3
RUN useradd -m -u 1000 agent
