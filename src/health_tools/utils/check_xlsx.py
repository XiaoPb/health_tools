"""check 报告 XLSX 分类聚合的纯数据接口。

本模块只负责分类聚合与统计，不涉及 Excel 写出；工作簿写出由后续任务在
``write_check_workbook`` 中实现。分类语义与 ``check_operation`` 的主要异常
匹配保持一致，但为独立实现：必须按状态列匹配，不能从 主要异常项 文本反推。
"""

from collections import Counter
from typing import Dict, List, Sequence, Tuple

# 稳定异常组标识到 (状态列, 期望值, 目录分类) 的映射；匹配顺序由调用方传入的
# issue_priority 决定。reference 组的两个状态列按 OR 语义匹配。
_ROW_RULES: Dict[str, Tuple[Tuple[str, ...], str, str]] = {
    "frame_fail": (("帧完整性(结果)",), "FAIL", "frame"),
    "range_fail": (("数据范围(结果)",), "FAIL", "range"),
    "acc_fail": (("ACC异常(结果)",), "FAIL", "acc_fail"),
    "timestamp_fail": (("时间戳间隔(结果)",), "FAIL", "timestamp"),
    "frame_warning": (("帧完整性(结果)",), "WARNING", "frame_warning"),
    "reference_fail": (("心率金标(结果)", "血氧金标(结果)"), "FAIL", "reference"),
    "acc_warning": (("ACC异常(结果)",), "WARNING", "acc_warning"),
    "center_fail": (("数据居中(结果)",), "FAIL", "center"),
}

# 稳定异常组标识到目录分类的映射；与 _ROW_RULES 中的 category 保持一致，
# 供 expand_issue_category_order 按优先级展开分类顺序使用。
_ISSUE_CATEGORY: Dict[str, str] = {rule_id: rule[2] for rule_id, rule in _ROW_RULES.items()}


def expand_issue_category_order(
    issue_priority: Sequence[str],
    rows: Sequence[Dict[str, str]],
    accuracy_categories: Sequence[str] = (),
) -> Tuple[str, ...]:
    """按 issue_priority 展开为实际出现在 rows 中的分类顺序。

    稳定异常组映射为对应目录分类；``accuracy`` 在外层位置展开为实际出现在
    rows 中且按 ``accuracy_categories`` 声明顺序排列的准确度分类。未出现在
    rows 中的分类不输出，未知标识按原样映射但同样需要实际出现。
    """
    present = {
        category
        for row in rows
        for category in (_row_category(row, issue_priority, accuracy_categories),)
        if category
    }
    categories: List[str] = []
    for rule_id in issue_priority:
        if rule_id == "accuracy":
            categories.extend(
                value
                for value in accuracy_categories
                if value in present and value not in categories
            )
            continue
        category = _ISSUE_CATEGORY.get(rule_id, rule_id)
        if category in present and category not in categories:
            categories.append(category)
    return tuple(categories)


def build_category_summary(
    rows: Sequence[Dict[str, str]],
    category: str,
    condition: str,
    explanation: str,
    total_count: int,
) -> Dict[str, object]:
    """统计单个分类命中行的聚合结果。

    返回分类说明表所需字段：count（命中行数，整数）、ratio（count/total_count
    数值）、scene_distribution（按 场景分类 计数）、person_distribution（按 姓名
    计数）、condition/explanation 原样保留，以及 category 供后续工作表使用。
    占比的分母是总表行数；场景与人员占比的分母是该分类命中行数；空姓名/场景
    统一为 default。
    """
    count = len(rows)
    scene_counter = _count_field(rows, "场景分类")
    person_counter = _count_field(rows, "姓名")
    return {
        "category": category,
        "count": count,
        "ratio": count / total_count if total_count else 0.0,
        "scene_distribution": _format_distribution(scene_counter, count),
        "person_distribution": _format_distribution(person_counter, count),
        "condition": condition,
        "explanation": explanation,
    }


def _row_category(
    row: Dict[str, str],
    issue_priority: Sequence[str],
    accuracy_categories: Sequence[str] = (),
) -> str:
    """按状态列匹配行的目录分类；未命中返回空字符串。

    必须按状态列（如 帧完整性(结果)==FAIL）匹配，不能从 主要异常项 文本反推；
    reference 组命中任一金标列即返回 reference。``accuracy`` 在 准确度标定分类
    非空时返回该值本身。返回 "" 表示未命中。
    """
    for rule_id in issue_priority:
        if rule_id == "accuracy":
            value = str(row.get("准确度标定分类", "") or "").strip()
            if value:
                return value
            continue
        rule = _ROW_RULES.get(rule_id)
        if rule is None:
            continue
        columns, expected, category = rule
        if any(str(row.get(column, "") or "").strip().upper() == expected for column in columns):
            return category
    return ""


def _format_distribution(counter: Counter, total: int) -> str:
    """把分类计数格式化为 "name: count (pct.00%)"，条目间以 ", " 连接。

    空名统一归一为 default；total 为 0 时占比按 0.00% 处理，避免除零崩溃。
    """
    items = []
    for name, count in counter.items():
        display = name if name else "default"
        percent = count / total * 100 if total else 0.0
        items.append(f"{display}: {count} ({percent:.2f}%)")
    return ", ".join(items)


def _count_field(rows: Sequence[Dict[str, str]], column: str) -> Counter:
    """按列统计字段出现次数，空值统一归一为 default。"""
    counter: Counter = Counter()
    for row in rows:
        value = row.get(column)
        counter[value if value else "default"] += 1
    return counter
