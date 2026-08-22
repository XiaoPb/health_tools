"""check 命令的 Online/Comp 准确度计算。"""

from typing import Dict, Iterable, Optional

import pandas as pd

from health_tools.api.models import CheckAccuracyResult
from health_tools.models.rules import AccuracyMarkRule, CheckAccuracyRule
from health_tools.utils.accuracy import calculate_accuracy, prepare_accuracy_columns


def match_accuracy_mark(
    result: CheckAccuracyResult, marks: Iterable[AccuracyMarkRule]
) -> Optional[AccuracyMarkRule]:
    """按规则声明顺序匹配首个准确度标定。"""
    for mark in marks:
        if _matches_declarative_mark(result, mark):
            return mark
    return None


def _metric_value(result: CheckAccuracyResult, path: str) -> Optional[float]:
    try:
        source, metric = path.split(".", 1)
    except ValueError:
        return None
    values = getattr(result, source, None)
    if not values:
        return None
    value = values.get(metric)
    return float(value) if isinstance(value, (int, float)) else None


def accuracy_mark_value(result: CheckAccuracyResult, mark: AccuracyMarkRule) -> Optional[float]:
    """返回标定规则实际与 threshold 比较的数值。"""
    left = _metric_value(result, mark.left)
    if left is None:
        return None
    right = _metric_value(result, mark.right) if mark.right else None
    if mark.operator in {"lt", "lte", "gt", "gte"}:
        return left
    if right is None:
        return None
    if mark.operator in {"diff_gte", "diff_gt"}:
        return right - left
    if mark.operator in {"ratio_lt", "ratio_lte"}:
        return None if right == 0 else left / right
    return None


def _matches_declarative_mark(result: CheckAccuracyResult, mark: AccuracyMarkRule) -> bool:
    value = accuracy_mark_value(result, mark)
    if value is None:
        return False
    threshold = mark.threshold
    if mark.operator in {"lt", "ratio_lt"}:
        return value < threshold
    if mark.operator in {"lte", "ratio_lte"}:
        return value <= threshold
    if mark.operator in {"gt", "diff_gt"}:
        return value > threshold
    if mark.operator in {"gte", "diff_gte"}:
        return value >= threshold
    return False


def calculate_check_accuracy(frame: pd.DataFrame, config: CheckAccuracyRule) -> CheckAccuracyResult:
    """按共同有效边界计算 Online/Comp 对 Ref 的准确度。"""
    required = (config.ref_column, config.online_column)
    for column in required:
        if column not in frame.columns:
            raise ValueError(f"缺少准确度列: {column}")

    columns: Dict[str, pd.Series] = {
        "ref": frame[config.ref_column],
        "online": frame[config.online_column],
    }
    if config.comp_column is not None and config.comp_column in frame.columns:
        columns["comp"] = frame[config.comp_column]

    prepared = prepare_accuracy_columns(columns)
    active = set(prepared.active_columns)
    if "ref" not in active:
        return CheckAccuracyResult(online={"samples": 0})

    metric_frame = pd.DataFrame(prepared.columns)
    methods = list(config.methods)
    thresholds = list(config.thresholds)

    online = {"samples": 0}
    if "online" in active:
        online = calculate_accuracy(
            metric_frame,
            "ref",
            "online",
            methods,
            thresholds,
            config.inclusive,
            trim_zero_padding=False,
        )
    comp = None
    if "comp" in active:
        comp = calculate_accuracy(
            metric_frame,
            "ref",
            "comp",
            methods,
            thresholds,
            config.inclusive,
            trim_zero_padding=False,
        )

    result = CheckAccuracyResult(online=online, comp=comp)
    mark = match_accuracy_mark(result, config.marks)
    return CheckAccuracyResult(online=result.online, comp=result.comp, matched_mark=mark)
