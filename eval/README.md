# eval — 简报质量评测

回答一个问题:**这个 Agent 生成的简报,可信吗?** 尤其是——**有没有编数字?**

LLM 最危险的失败不是报错,而是"一本正经地编一个看起来合理的数字"。本评测用**确定性**
方法(不依赖另一个 LLM,可离线在 CI 跑)对每份简报打分,核心是反幻觉的数字溯源。

## 五项检查

| 检查 | 查什么 | 怎么判 |
| --- | --- | --- |
| **structure** | 五个必需章节(摘要/新闻/储量/价格/风险)是否齐全 | 缺一即扣分 |
| **citations** | 新闻章节是否带来源链接 | ≥1 达标,≥2 满分 |
| **grounding** ⭐ | 数据表格里**每个数字**是否都能在工具返回中找到 | 1% 容差匹配;对不上=疑似幻觉 |
| **honesty** | 工具若返回降级信号(快照/低置信/离线),简报是否如实声明 | 有降级但不声明=不及格 |
| **topicality** | 简报是否覆盖了该请求应涉及的关键词 | 来自 `cases.jsonl` |

`grounding` 是重点:它只核对**表格单元格**里的数字(不查摘要散文,因为摘要允许做求和、
换算等派生),把每个数字拿去和工具实际返回的数字比对。这直接量化"幻觉率"——真实运行
一份 Pilbara 简报,评测报告 "33 个表格数字全部溯源到工具返回",就是在说这份简报零编造。

## 用法

```bash
# 1) 评一份已有的运行痕迹(离线,无需任何 key)
mineral-daily "..." --trace run.json      # 先跑 agent 转储痕迹
python eval/run_eval.py --trace run.json  # 再评分

# 2) 跑整个用例集并评测(需要 LLM key)
python eval/run_eval.py                    # 跑 cases.jsonl 全部用例
python eval/run_eval.py --offline          # 数据侧离线(fixture/快照)
python eval/run_eval.py --llm-judge        # 额外做 LLM faithfulness 评审(1-5 分)

# 退出码:全部达标→0,否则→1(可接 CI 门禁)
```

## 文件

- `cases.jsonl` — ground truth 用例:请求 + 期望覆盖的关键词
- `run_eval.py` — 评测 CLI(跑用例 或 评已有 trace)
- 评分逻辑:[`src/mineral_daily/evaluation/scorecard.py`](../src/mineral_daily/evaluation/scorecard.py)(确定性)
  + [`llm_judge.py`](../src/mineral_daily/evaluation/llm_judge.py)(可选 LLM faithfulness)

## 两层评测的分工

- **确定性 scorecard**(默认):查得了"数字是否溯源、章节是否齐全、降级是否声明",
  快、可复现、CI 友好,是防幻觉的主力。
- **LLM-judge**(`--llm-judge`,可选):查确定性方法查不了的"论断是否被证据支撑"
  (faithfulness),用另一个 LLM 当裁判打 1–5 分。需 key、非确定,故不进 CI 默认门禁。
