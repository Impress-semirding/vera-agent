FROM alibaba-cloud-linux-3-registry.cn-hangzhou.cr.aliyuncs.com/alinux3/python:3.11.1

RUN yum install -y git curl ca-certificates \
 && yum clean all

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir claude-agent-sdk mcp

RUN useradd -m -s /bin/bash agent && \
    mkdir -p /workspace /home/agent/.claude && \
    chown -R agent:agent /workspace /home/agent

# Copy agent runtime + scheduler MCP server
COPY runner.py stream_emitter.py vera_scheduler_mcp.py /app/

ENV PYTHONPATH=/app
WORKDIR /workspace
USER agent

ENTRYPOINT ["python3", "/app/runner.py"]
