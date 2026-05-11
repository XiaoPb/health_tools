"""统一列名展开工具"""

import re
from typing import List


def expand_columns(columns: List[str], brace_only: bool = False) -> List[str]:
    """展开列名范围语法。

    brace_only=False: 匹配 name[0-15] 展开为 name0..name15 (chip/parse规则)
    brace_only=True:  仅匹配 name{0-15} 展开，[] 保留为字面量 (convert规则)

    {start-end} 可出现在字符串任意位置，如 rawdata[{0-1}] -> rawdata[0], rawdata[1]
    """
    expanded = []
    for col in columns:
        match = re.search(r"\{(\d+)-(\d+)\}", col)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            prefix = col[: match.start()]
            suffix = col[match.end() :]
            for i in range(start, end + 1):
                expanded.append(f"{prefix}{i}{suffix}")
            continue

        if not brace_only:
            match = re.match(r"^(.+?)\[(\d+)-(\d+)\]$", col)
            if match:
                prefix, s, e = match.groups()
                for i in range(int(s), int(e) + 1):
                    expanded.append(f"{prefix}{i}")
                continue

        expanded.append(col)
    return expanded
