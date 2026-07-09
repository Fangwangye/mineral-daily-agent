# 单镜像承载 3 个 MCP server 与 agent（compose 用不同 command 启动）
FROM python:3.11-slim

# 国内网络可加速：docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MINERAL_CACHE_DIR=/data/cache

WORKDIR /app

# 依赖按锁文件安装（可复现构建），项目本体 --no-deps 安装
COPY requirements.lock pyproject.toml README.md ./
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" --no-deps .

# 非 root 运行（HTTP 服务安全基线）；缓存与简报目录归属运行用户
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/cache /app/briefings \
    && chown -R app:app /data /app/briefings
USER app

# stdio 模式无需端口；http 模式由 compose 指定 --host/--port
CMD ["mineral-daily", "--help"]
