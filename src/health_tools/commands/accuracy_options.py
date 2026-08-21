"""准确度命令的公共 Click 参数。"""

import math
from typing import Optional, Tuple

import click

from health_tools.utils.accuracy import normalize_accuracy_thresholds


def _finite_number(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise click.BadParameter(f"{label}必须是有限数字") from exc
    if not math.isfinite(number):
        raise click.BadParameter(f"{label}必须是有限数字")
    return number


def _mark_id(comparison: str, metric: str, index: int) -> str:
    return f"{comparison}_{metric}_{index + 1}"


def parse_accuracy_min(value: str, index: int = 0):
    """解析单条 Online/Comp 最低准确度标定。"""
    from health_tools.models.rules import AccuracyMarkRule

    parts = value.split(":", 4)
    if len(parts) not in {4, 5}:
        raise click.BadParameter("格式应为 COMPARISON:METRIC:MIN:CATEGORY[:LABEL]")
    comparison, metric, minimum, category = parts[:4]
    if comparison not in {"online", "comp"}:
        raise click.BadParameter("COMPARISON 只支持 online 或 comp")
    if not metric or not category:
        raise click.BadParameter("准确度指标和分类不能为空")
    threshold = _finite_number(minimum, "MIN")
    label = parts[4] if len(parts) == 5 and parts[4] else f"{comparison} {metric}准确度低"
    return AccuracyMarkRule(
        id=_mark_id(comparison, metric, index),
        comparison=comparison,
        metric=metric,
        min=threshold,
        category=category,
        label=label,
    )


def parse_online_comp_gap(value: str, index: int = 0):
    """解析单条 Online 落后 Comp 标定。"""
    from health_tools.models.rules import AccuracyMarkRule

    parts = value.split(":", 3)
    if len(parts) not in {3, 4}:
        raise click.BadParameter("格式应为 METRIC:MIN_GAP:CATEGORY[:LABEL]")
    metric, minimum_gap, category = parts[:3]
    if not metric or not category:
        raise click.BadParameter("准确度指标和分类不能为空")
    threshold = _finite_number(minimum_gap, "MIN_GAP")
    label = parts[3] if len(parts) == 4 and parts[3] else f"Online低于Comp {threshold:g}个百分点"
    return AccuracyMarkRule(
        id=_mark_id("online_below_comp", metric, index),
        comparison="online_below_comp",
        metric=metric,
        min_gap=threshold,
        category=category,
        label=label,
    )


def parse_accuracy_thresholds(
    _ctx: click.Context, _param: click.Parameter, value: Optional[str]
) -> Optional[Tuple[float, ...]]:
    """解析逗号分隔的准确度阈值。"""
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",")]
    if not parts or any(not part for part in parts):
        raise click.BadParameter("准确度阈值必须是逗号分隔的有限正数")
    try:
        return normalize_accuracy_thresholds(tuple(float(part) for part in parts))
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


def accuracy_options(command):
    """为命令增加统一准确度阈值选项。"""
    command = click.option(
        "--accuracy-inclusive/--accuracy-strict",
        default=False,
        help="阈值命中使用 <=；默认严格使用 <",
    )(command)
    return click.option(
        "--accuracy-thresholds",
        callback=parse_accuracy_thresholds,
        help="逗号分隔的准确度阈值；默认采用规则或 5,10,15",
    )(command)
