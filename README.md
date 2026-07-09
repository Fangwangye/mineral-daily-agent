# mineral-daily-agent — 矿权日报 Agent（MCP 协议）

按 MCP（Model Context Protocol）协议实现的「矿权日报」系统：**3 个 MCP server + 1 个 ReAct Agent client**。

输入一句自然语言：

```
mineral-daily "给我生成一份关于 Pilbara 锂矿的今日简报"
```

输出一份 Markdown 简报：新闻摘要、储量数据、价格走势、风险提示，全部带引用源链接，落盘 `briefings/`。

**5 分钟跑起来 → [RUN.md](RUN.md)**（一条 docker-compose，或本地一条命令）。

## 架构

```mermaid
flowchart LR
    U["用户: 给我生成一份关于\nPilbara 锂矿的今日简报"] --> A

    subgraph Agent["agent（ReAct client）"]
        A["ReAct 循环\nmax 12 步 / 工具并行 / 60s 超时"] <--> L["DeepSeek deepseek-chat\n(任意 OpenAI 兼容端点可插拔)"]
    end

    A <-->|"MCP stdio 或 streamable-http"| N & P & Q

    subgraph MCP servers
        N["mining-news-mcp\nsearch / fetch_article"]
        P["mineral-pdf-mcp\nextract_resources"]
        Q["lme-price-mcp\nget_price / get_trend"]
    end

    N --> N1["mining.com RSS + trafilatura\n↓ 失败降级\n打包 RSS/文章 fixture(真实快照)"]
    P --> P1["pdfplumber 双通道解析\n结构化表格 + 文本行回退"]
    Q --> Q1["westmetall live(LME 官方结算价)\n↓ 失败降级\n打包快照(真实数据,来源入库)"]

    A --> M["Markdown 简报\nbriefings/*.md"]
```

- **stdio 模式（默认）**：agent 用当前解释器把 3 个 server 拉成子进程——本地一条命令即是完整 MCP 部署，也是 Claude Desktop 的接入方式（[mcp-config.json](mcp-config.json)）。
- **streamable-http 模式**：`docker compose` 三容器分布式部署，agent 通过 `MCP_SERVERS` 环境变量寻址，healthcheck 保证启动顺序。

## 三个 MCP server

| server | 工具 | 数据源 | 降级策略 |
| --- | --- | --- | --- |
| mining-news-mcp | `search(query, days, limit)` · `fetch_article(url)` | mining.com RSS（`NEWS_FEEDS` 可扩展）+ trafilatura 正文抽取 | 10min/24h 磁盘缓存 → 过期缓存 → 打包 fixture（真实 RSS + 文章快照，采集脚本可复现） |
| mineral-pdf-mcp | `extract_resources(pdf_url)` | NI 43-101 / JORC 报告 PDF（URL / 本地路径 / `fixture`） | 结构化表格解析失败 → 文本行回退（置信度封顶 0.55）；`confidence < 0.5` = **abstain**，notes 提示人工核对 |
| lme-price-mcp | `get_price(commodity, date)` · `get_trend(commodity, days)` | 铜/锌/镍：westmetall（LME 官方结算价免费镜像）live；碳酸锂/铁矿石：打包快照 | live 失败 → 6h 缓存 → 过期缓存 → 快照；每条结果带 `source` 与 `is_live` 字段 |

### 对「登录墙 / 频控 / 反爬」的工程回应

价格官方源（LME 数据授权、上海钢联、SMM）有登录墙，新闻站有反爬——本项目不伪装绕过，而是：

1. **live 优先**：有免费合规镜像的（westmetall、RSS）实时抓，带 UA/超时/重试/磁盘缓存（频控友好）；
2. **降级透明**：每级降级写进工具返回的 `notes`/`source`/`is_live`，Agent 被系统提示词强制在简报「数据可用性」一节如实汇报；
3. **快照可溯源**：打包快照全部为真实数据（LME 三金属 62 个交易日实抓；碳酸锂来自生意社公开日度价；铁矿石来自 countryeconomy 月度均价），来源与截止日期写入数据文件与 [scripts/curate_manual_prices.py](scripts/curate_manual_prices.py)；
4. **PDF 反爬检测**：下载内容魔数校验，登录墙/重定向页不入缓存并给出可读报错与替代路径。

### PDF 解析的真实验证

对真实 ASX 公告《Pilgangoora Ore Reserve & Mineral Resource Update》(2023-08, 56 页) 实测：
文本行回退通道完整抽出 MRE（Measured 22.1 Mt @ 1.34% Li2O / Indicated 315.2 @ 1.15 / Inferred 76.6 @ 1.07 / Total 413.8 @ 1.15）与 Ore Reserve（Total 214.2 Mt，与公告标题一致），置信度如实标注 0.55 并提示人工核对；对不含储量表的公告正确返回空结果（真阴性）而非硬给。

## Agent 设计（自写 ReAct，不依赖编排框架）

1. **工具自动发现**：连接每个 server 后 `list_tools()`，以 `server__tool` 命名空间转成 OpenAI function schema——新增 server 无需改 agent 代码；
2. **循环守护**：最大 12 步；单工具 60s 超时；同一步多个工具调用 `asyncio.gather` 并行；
3. **错误自适应**：工具失败以 `[tool error] …` 文本回喂模型换路（例如换 URL、换关键词），单 server 连接失败仅降级并记入简报；
4. **保证产出**：步数耗尽时禁用工具、注入强制合成提示，永远给出结构完整的简报；
5. **可溯源硬规则**：系统提示词要求每个事实附链接/来源字段，fixture 与低置信数据必须显著声明，缺数据写进「数据可用性」而非编造。

## 目录结构

```
├── src/mineral_daily/
│   ├── common/          http（重试/缓存/离线）· parsing · logging(stderr) · runner(双传输)
│   ├── servers/news/    server · feeds(RSS) · article(trafilatura) · data/(真实 fixture)
│   ├── servers/pdf/     server · parser(双通道) · models · data/(fixture PDF)
│   ├── servers/price/   server · providers(westmetall+快照) · data/prices_snapshot.json
│   └── agent/           main(CLI) · mcp_client(MCPFleet) · react · llm · briefing
├── tests/               42 用例：三 server 单测 + FakeLLM×真实 MCP stdio 全链路 E2E
├── scripts/             快照刷新 / fixture 采集 / fixture PDF 生成（全部可复现）
├── docker-compose.yml   3×streamable-http server + agent（healthcheck 编排）
├── mcp-config.json      Claude Desktop / Cursor 直接接入（stdio）
└── RUN.md               5 分钟运行手册（Docker / 本地 / Claude Desktop 三条路径）
```

## 工程规范

- **测试**：`pytest` 42 用例全离线可跑（respx 模拟 http、真实 fixture、真实 MCP stdio E2E），`network` 标记的实网用例默认跳过；
- **Lint**：`ruff check` 零告警（E/F/I/UP/B/W）；
- **CI**：GitHub Actions（lint + test）；
- **配置即环境变量**：`.env.example` 全量注释，LLM 端点/模型/数据源均可插拔；
- **日志**：全部走 stderr——stdout 是 MCP stdio 的 JSON-RPC 信道，这是 MCP server 的硬约束；
- **提交历史**：全程由 Claude Code 编写，逐里程碑提交（见 `git log`）。

## 已知局限（诚实声明）

- PDF 解析为启发式（关键词定位 + 表头映射 + 文本行回退），对扫描件（无文本层）与复杂多分区表格覆盖有限——此时按 abstain 语义返回空/低置信而非猜测；
- 碳酸锂/铁矿石无免费可编程 live 源，快照会随时间老化（`as_of` 字段与简报中会体现）；
- 新闻默认单源 mining.com（`NEWS_FEEDS` 可加源）；RSS 仅覆盖近几十条，不做历史回溯；
- 简报质量最终受 LLM 影响；系统通过溯源硬规则 + 步数/超时守护 + 强制合成兜底约束，但不能完全消除模型误读。

## 交付对照（题目要求 → 实现）

| 要求 | 位置 |
| --- | --- |
| mining-news-mcp：`search` / `fetch_article` | [src/mineral_daily/servers/news/](src/mineral_daily/servers/news/) |
| mineral-pdf-mcp：`extract_resources`（NI 43-101 Indicated/Inferred） | [src/mineral_daily/servers/pdf/](src/mineral_daily/servers/pdf/) |
| lme-price-mcp：`get_price` / `get_trend` | [src/mineral_daily/servers/price/](src/mineral_daily/servers/price/) |
| Agent 主流程（Pilbara 锂矿简报 → Markdown + 引用） | [src/mineral_daily/agent/](src/mineral_daily/agent/) |
| client 端 Agent 编排（自写 ReAct） | [src/mineral_daily/agent/react.py](src/mineral_daily/agent/react.py) |
| mcp-config.json（Claude Desktop / Cursor） | [mcp-config.json](mcp-config.json) |
| RUN.md（5 分钟，含一条 docker-compose） | [RUN.md](RUN.md) |
