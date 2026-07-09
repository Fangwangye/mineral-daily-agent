# 单镜像承载 3 个 MCP server 与 agent（compose 用不同 command 启动）
FROM python:3.11-slim

# 国内网络可加速：docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MINERAL_CACHE_DIR=/data/cache

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" . && mkdir -p /data/cache /app/briefings

# stdio 模式无需端口；http 模式由 compose 指定 --host/--port
CMD ["mineral-daily", "--help"]
