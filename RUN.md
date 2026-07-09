# RUN — 5 分钟跑起来

> 唯一的外部前置：一个 LLM API key（默认 DeepSeek；任何 OpenAI 兼容端点均可，见 `.env.example`）。
> 数据源不需要任何 key：live 抓取失败或完全断网时自动降级到打包快照/fixture（简报的「数据可用性」一节会如实标注）。

## 路径 A：Docker（推荐，一条 compose 命令）

```bash
git clone https://github.com/Fangwangye/mineral-daily-agent.git && cd mineral-daily-agent
cp .env.example .env          # 编辑 .env，填入 DEEPSEEK_API_KEY
docker compose run --rm --build agent "给我生成一份关于 Pilbara 锂矿的今日简报"
```

- 该命令自动构建镜像、按 healthcheck 顺序拉起 3 个 MCP server（streamable-http），
  再运行 agent 完成 ReAct 编排；简报打印到终端并写入宿主机 `./briefings/`。
- 国内网络构建加速：
  `docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`
- 完全离线运行（数据侧不出网，用打包真实快照）：
  - PowerShell：`$env:MINERAL_OFFLINE="1"; docker compose run --rm agent`
  - bash：`MINERAL_OFFLINE=1 docker compose run --rm agent`
- 收尾：`docker compose down`

## 路径 B：本地 Python（无 Docker）

```bash
python -m venv .venv
.venv\Scripts\pip install -e .          # Windows；Linux/macOS 用 .venv/bin/pip
copy .env.example .env                  # 填 DEEPSEEK_API_KEY
.venv\Scripts\mineral-daily "给我生成一份关于 Pilbara 锂矿的今日简报"
```

- 默认 **stdio 模式**：agent 自动把 3 个 server 拉成子进程，无需先起服务。
- 常用参数：`--offline`（全离线）、`--http`（连 compose 起的服务）、`--max-steps N`。

## 路径 C：接入 Claude Desktop / Cursor 验证 MCP server

1. 先完成路径 B 的安装（server 以包形式安装进 venv）。
2. 把 `mcp-config.json` 三个条目合并进 Claude Desktop 配置
   （Windows：`%APPDATA%\Claude\claude_desktop_config.json`），并把 `"command": "python"`
   替换为 venv 的绝对路径，例如：
   ```json
   "command": "D:/path/to/mineral-daily-agent/.venv/Scripts/python.exe"
   ```
3. 重启 Claude Desktop，即可直接提问验证工具：
   - “用 mining-news 搜一下近 7 天 Pilbara lithium 的新闻”
   - “用 lme-price 查 lithium_carbonate 近 30 天走势”
   - “用 mineral-pdf 解析 fixture 报告的储量表”

## 验证与测试

```bash
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q      # 45 个用例：三 server 单测 + 真实 MCP stdio 全链路 E2E（离线、无需 key）
.venv\Scripts\python -m ruff check src tests scripts
.venv\Scripts\python -m mypy src
```

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `[配置错误] 缺少 LLM API key` | `.env` 里填 `DEEPSEEK_API_KEY`；或 `LLM_API_KEY`+`LLM_BASE_URL` 指向任意 OpenAI 兼容端点 |
| 新闻/价格 live 抓取失败 | 自动降级（缓存→快照/fixture），简报「数据可用性」会说明；也可 `--offline` 主动全离线 |
| PDF URL 返回登录墙/反爬页 | 工具会报「不是 PDF」并建议换镜像 URL 或用 `fixture`；已知可用真实公告见系统提示词内置的 ASX 链接 |
| Windows 控制台中文乱码 | 程序已强制 UTF-8 输出；若仍乱码先执行 `chcp 65001` |
