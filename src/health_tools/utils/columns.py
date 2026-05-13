"""统一列名展开工具"""

import re
from typing import List


def _expand_single(col: str, brace_only: bool) -> List[str]:
    """展开单个列名中的所有范围语法，从右到左逐个展开。

    多个 {} 时先展开最右侧，再展开左侧，最终顺序为左侧外层迭代。
    """
    matches = list(re.finditer(r"\{(\d+)-(\d+)\}", col))
    if matches:
        first = matches[0]
        start, end = int(first.group(1)), int(first.group(2))
        prefix = col[: first.start()]
        suffix = col[first.end() :]
        results = []
        for i in range(start, end + 1):
            results.extend(_expand_single(f"{prefix}{i}{suffix}", brace_only))
        return results

    if not brace_only:
        match = re.match(r"^(.+?)\[(\d+)-(\d+)\]$", col)
        if match:
            prefix, s, e = match.groups()
            return [f"{prefix}{i}" for i in range(int(s), int(e) + 1)]

    return [col]


def expand_columns(columns: List[str], brace_only: bool = False) -> List[str]:
    """展开列名范围语法。

    brace_only=False: 匹配 name[0-15] 展开为 name0..name15 (chip/parse规则)
    brace_only=True:  仅匹配 name{0-15} 展开，[] 保留为字面量 (convert规则)

    支持多个 {start-end}，从右到左依次展开:
      ALGO{0-1}_CH{0-2} -> ALGO0_CH0, ALGO0_CH1, ALGO0_CH2, ALGO1_CH0, ...
    """
    expanded = []
    for col in columns:
        expanded.extend(_expand_single(col, brace_only))
    return expanded
