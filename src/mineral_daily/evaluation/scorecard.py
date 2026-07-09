"""简报质量评分器（确定性，不依赖 LLM，可在 CI 离线运行）。

四项检查，每项 0–1：
- structure   : 必需章节是否齐全（摘要/新闻动态/储量数据/价格走势/风险提示）
- citations   : 新闻动态一节是否带来源链接
- grounding   : 数据表格里的数字是否都能在工具返回中找到（反幻觉核心项）
- honesty     : 工具若返回了降级信号（快照/低置信/离线），简报是否如实声明

grounding 是重点：LLM 最危险的失败是"编一个看起来合理的数字"。我们把简报数据
表格里的每个数字，拿去和工具实际返回的数字比对（1% 容差），对不上的记为疑似幻觉。
只查表格单元格、不查摘要散文——摘要允许做求和/换算等派生，表格必须逐个可溯源。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 必需章节（标题里包含这些关键词即算命中）
REQUIRED_SECTIONS = ["摘要", "新闻", "储量", "价格", "风险"]
# 需要做数字溯源的数据章节
DATA_SECTIONS = ["储量", "价格"]
# 工具返回里代表"数据降级"的信号
DEGRADE_MARKERS = ["快照", "fixture", "离线", '"is_live": false', '"is_live":false', "abstain"]
# 简报里代表"已声明降级"的措辞
ACK_MARKERS = ["快照", "fixture", "离线", "置信度", "confidence", "降级", "人工核对", "非实时"]

_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
# 独立数字：前后不紧贴字母/数字，用于表格取数——排除化学式里的数字（Li2O 的 2、Ta2O5 的 5）
_DATA_NUM = re.compile(r"(?<![0-9A-Za-z])-?\d[\d,]*(?:\.\d+)?(?![0-9A-Za-z])")
_HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)
_URL = re.compile(r"https?://[^\s)\]]+")


@dataclass
class CheckResult:
    name: str
    score: float
    passed: bool
    detail: str


@dataclass
class Scorecard:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall(self) -> float:
        if not self.checks:
            return 0.0
        return round(sum(c.score for c in self.checks) / len(self.checks), 3)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "passed": self.passed,
            "checks": [vars(c) for c in self.checks],
        }


def _to_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text):
        v = _to_float(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _sections(markdown: str) -> dict[str, str]:
    """按标题切分：返回 {标题: 该节正文}。"""
    parts: dict[str, str] = {}
    matches = list(_HEADING.finditer(markdown))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        parts[m.group(1)] = markdown[start:end]
    return parts


def _find_section(sections: dict[str, str], keyword: str) -> str | None:
    for title, body in sections.items():
        if keyword in title:
            return body
    return None


def _table_numbers(section_body: str) -> list[float]:
    """只取 Markdown 表格行（含 | 的行）里的独立数字，跳过分隔行、日期、化学式内数字。"""
    nums: list[float] = []
    for line in section_body.splitlines():
        if "|" not in line or set(line.strip()) <= set("|-: "):
            continue
        # 去掉 YYYY-MM-DD 形式的日期，避免把年月日当数据
        cleaned = re.sub(r"\d{4}-\d{2}-\d{2}", " ", line)
        for m in _DATA_NUM.finditer(cleaned):
            v = _to_float(m.group(0))
            if v is not None:
                nums.append(v)
    return nums


def _is_grounded(value: float, pool: list[float], tol: float = 0.01) -> bool:
    """value 是否能在 pool 中找到（相对误差 ≤ tol，兼容四舍五入/改格式）。"""
    for m in pool:
        denom = max(abs(m), 1.0)
        if abs(value - m) / denom <= tol:
            return True
    return False


def check_structure(sections: dict[str, str]) -> CheckResult:
    present = [s for s in REQUIRED_SECTIONS if _find_section(sections, s) is not None]
    score = len(present) / len(REQUIRED_SECTIONS)
    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    return CheckResult(
        "structure", round(score, 3), not missing,
        "章节齐全" if not missing else f"缺失章节: {missing}",
    )


def check_citations(sections: dict[str, str]) -> CheckResult:
    news = _find_section(sections, "新闻")
    if news is None:
        return CheckResult("citations", 0.0, False, "无新闻章节")
    urls = _URL.findall(news)
    score = min(len(urls) / 2, 1.0)  # ≥2 条来源即满分
    return CheckResult(
        "citations", round(score, 3), len(urls) >= 1,
        f"新闻章节含 {len(urls)} 个来源链接",
    )


def check_grounding(sections: dict[str, str], tool_numbers: list[float]) -> CheckResult:
    briefing_nums: list[float] = []
    for kw in DATA_SECTIONS:
        body = _find_section(sections, kw)
        if body:
            briefing_nums.extend(_table_numbers(body))
    # 只核对有意义的量级数字（跳过 0~1 之外无所谓的小整数噪声由容差吸收）
    checkable = [n for n in briefing_nums if abs(n) >= 0.01]
    if not checkable:
        return CheckResult("grounding", 1.0, True, "数据表格无可核对数字（跳过）")
    ungrounded = [n for n in checkable if not _is_grounded(n, tool_numbers)]
    score = 1 - len(ungrounded) / len(checkable)
    passed = not ungrounded
    detail = (
        f"{len(checkable)} 个表格数字全部溯源到工具返回"
        if passed
        else f"{len(ungrounded)}/{len(checkable)} 个数字无法溯源（疑似幻觉）: "
        f"{sorted(set(ungrounded))[:8]}"
    )
    return CheckResult("grounding", round(score, 3), passed, detail)


def check_honesty(markdown: str, tool_results: list[str]) -> CheckResult:
    blob = "\n".join(tool_results).lower()
    degraded = [m for m in DEGRADE_MARKERS if m.lower() in blob]
    if not degraded:
        return CheckResult("honesty", 1.0, True, "工具无降级信号，无需声明")
    acknowledged = any(a.lower() in markdown.lower() for a in ACK_MARKERS)
    return CheckResult(
        "honesty", 1.0 if acknowledged else 0.0, acknowledged,
        "已如实声明数据降级" if acknowledged
        else f"工具返回降级信号({degraded})但简报未声明",
    )


def check_keywords(markdown: str, keywords: list[str]) -> CheckResult:
    """主题相关性：简报是否覆盖了本次请求应涉及的关键词（大小写不敏感）。"""
    low = markdown.lower()
    hit = [k for k in keywords if k.lower() in low]
    score = len(hit) / len(keywords) if keywords else 1.0
    missing = [k for k in keywords if k not in hit]
    return CheckResult(
        "topicality", round(score, 3), not missing,
        "主题关键词全覆盖" if not missing else f"缺少关键词: {missing}",
    )


def score_briefing(
    markdown: str, tool_calls: list[dict], expect_keywords: list[str] | None = None
) -> Scorecard:
    """对一份简报打分。

    Args:
        markdown: 简报正文
        tool_calls: run_agent 产出的 tool_calls（需含 'result' 字段，见 react.py）
        expect_keywords: 该请求应覆盖的主题关键词（可选，来自 eval 用例）
    """
    sections = _sections(markdown)
    tool_results = [str(c.get("result", "")) for c in tool_calls]
    tool_numbers = _numbers("\n".join(tool_results))
    checks = [
        check_structure(sections),
        check_citations(sections),
        check_grounding(sections, tool_numbers),
        check_honesty(markdown, tool_results),
    ]
    if expect_keywords:
        checks.append(check_keywords(markdown, expect_keywords))
    return Scorecard(checks=checks)
