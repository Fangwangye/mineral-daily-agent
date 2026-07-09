"""简报质量评测：确定性打分器 + 可选 LLM faithfulness 评审。"""

from .scorecard import CheckResult, Scorecard, score_briefing

__all__ = ["CheckResult", "Scorecard", "score_briefing"]
