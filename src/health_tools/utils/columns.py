"""统一列名展开工具"""

import re
from typing import List


def _expand_single(col: str) -> List[str]:
    """展开单个列名中的 {start-end} 范围语法。

    多个 {} 时先展开最左侧，再递归展开右侧，最终顺序为左侧外层迭代。
    [] 保留为字面量（用于引用含方括号的实际列名）。
    """
    matches = list(re.finditer(r"\{(\d+)-(\d+)\}", col))
    if matches:
        first = matches[0]
        start, end = int(first.group(1)), int(first.group(2))
        prefix = col[: first.start()]
        suffix = col[first.end() :]
        results = []
        for i in range(start, end + 1):
            results.extend(_expand_single(f"{prefix}{i}{suffix}"))
        return results

    return [col]


def expand_columns(columns: List[str]) -> List[str]:
    """展开列名中的 {start-end} 范围语法。

    支持多个 {start-end}，从左到右依次展开:
      ALGO{0-1}_CH{0-2} -> ALGO0_CH0, ALGO0_CH1, ALGO0_CH2, ALGO1_CH0, ...
    [] 保留为字面量，不做展开。
    """
    expanded = []
    for col in columns:
        expanded.extend(_expand_single(col))
    return expanded
