"""check 命令的 Online/Comp 准确度计算。"""

from typing import Dict

import pandas as pd

from health_tools.api.models import CheckAccuracyResult
from health_tools.models.rules import CheckAccuracyRule
from health_tools.utils.accuracy import calculate_accuracy, prepare_accuracy_columns


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

    return CheckAccuracyResult(online=online, comp=comp)
