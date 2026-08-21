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
        if mark.comparison in {"online", "comp"}:
            metrics = getattr(result, mark.comparison)
            value = metrics.get(mark.metric) if metrics is not None else None
            if value is not None and mark.min is not None and value < mark.min:
                return mark
        elif mark.comparison == "online_below_comp":
            if result.online is None or result.comp is None or mark.min_gap is None:
                continue
            online = result.online.get(mark.metric)
            comp = result.comp.get(mark.metric)
            if online is not None and comp is not None and comp - online >= mark.min_gap:
                return mark
    return None


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
