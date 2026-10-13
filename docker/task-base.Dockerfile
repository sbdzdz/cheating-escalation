FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy sympy mpmath matplotlib pillow==12.3.0 requests==2.34.2 pyyaml==6.0.3
RUN useradd -m -u 1000 agent
