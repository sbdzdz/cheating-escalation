FROM node:22.23.3-bookworm-slim AS node
# npm is build-only; the final image gets Node and the installed harness.
FROM node AS harness-build
WORKDIR /tmp/factorization-dsh-runtime
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM ghcr.io/astral-sh/uv:0.7.11 AS uv
# TASK_BASE
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=uv /uv /opt/harbor-acp-tools/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/harbor-acp-python
RUN /opt/harbor-acp-tools/uv python install 3.12 && /opt/harbor-acp-tools/uv venv --python 3.12 /opt/harbor-acp-venv && /opt/harbor-acp-tools/uv pip install --python /opt/harbor-acp-venv/bin/python agent-client-protocol==0.12.1 && chmod -R a+rX /opt/harbor-acp-python /opt/harbor-acp-venv
COPY --from=harness-build --chown=agent:agent /tmp/factorization-dsh-runtime /tmp/factorization-dsh-runtime
RUN node --version && test -x /tmp/factorization-dsh-runtime/node_modules/.bin/dsh && ! command -v npm && ! command -v npx
COPY runtime.json /opt/factorization-runtime.json
WORKDIR /workspace
