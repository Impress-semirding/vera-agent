FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir claude-agent-sdk

RUN useradd -m -s /bin/bash agent && \
    mkdir -p /workspace /home/agent/.claude && \
    chown -R agent:agent /workspace /home/agent

# Copy agent runtime (flat layout — PYTHONPATH handles imports)
COPY runner.py stream_emitter.py /app/

ENV PYTHONPATH=/app
WORKDIR /workspace
USER agent

ENTRYPOINT ["python3", "/app/runner.py"]
