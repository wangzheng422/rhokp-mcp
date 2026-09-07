# AI-Author: Codex (OpenAI model not exposed by runtime)
ARG BASE_IMAGE=docker.io/library/python:3.12-slim
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TOKEN_FILE=/run/secrets/mcp_token
WORKDIR /opt/rhokp-mcp
COPY mcp/rhokp_mcp_server.py ./rhokp_mcp_server.py
COPY LICENSE /usr/share/licenses/rhokp-mcp/LICENSE
RUN chmod 0555 /opt/rhokp-mcp && chmod 0444 /opt/rhokp-mcp/rhokp_mcp_server.py
USER 10001:0
EXPOSE 18081
HEALTHCHECK --interval=30s --timeout=25s --start-period=15s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18081/healthz', timeout=22).read()"]
ENTRYPOINT ["python3", "/opt/rhokp-mcp/rhokp_mcp_server.py"]
CMD ["--host", "0.0.0.0", "--port", "18081"]
