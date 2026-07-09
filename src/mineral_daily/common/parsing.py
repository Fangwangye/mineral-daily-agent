"""通用数字解析：兼容欧式/美式千分位、小数点混排与带单位后缀的单元格。"""

from __future__ import annotations

import re


def parse_number(raw: str | None) -> float | None:
    """从字符串解析数值；无法解析返回 None。

    兼容："9 456,00" / "9.456,00" / "9,456.00" / "13090" / "1,845 koz"（取数值部分）。
    """
    if raw is None:
        return None
    s = raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    m = re.search(r"-?\d[\d.,\s]*", s)
    if not m:
        return None
    s = re.sub(r"\s+", "", m.group(0)).rstrip(".,")
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        # 最后出现的分隔符视为小数点
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if len(tail) == 3 and head:  # 千分位
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
