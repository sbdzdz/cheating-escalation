# TASK_BASE
COPY pyproject.toml uv.lock /opt/controlled/
RUN uv export --project /opt/controlled --locked --no-dev --no-emit-project --output-file /tmp/controlled-deps.txt && uv pip install --system --no-cache --require-hashes -r /tmp/controlled-deps.txt && rm /tmp/controlled-deps.txt
COPY controlled_runner.py model_log.py /opt/controlled/
COPY runtime.json /opt/experiment-runtime.json
