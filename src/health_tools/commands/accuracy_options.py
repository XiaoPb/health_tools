"""准确度命令的公共 Click 参数。"""

import math
import re
from typing import Optional, Tuple

import click

from health_tools.utils.accuracy import normalize_accuracy_thresholds

SAFE_MARK_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


class OrderedAccuracyMarksCommand(click.Command):
    """在 Click 转换参数前保留两类标定选项的真实出现顺序。"""

    _MARK_OPTIONS = {
        "--accuracy-min": "accuracy_min",
        "--online-comp-gap": "online_comp_gap",
    }

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ordered = []
        index = 0
        while index < len(args):
            argument = args[index]
            if argument == "--":
                break
            matched = False
            for option, name in self._MARK_OPTIONS.items():
                if argument == option:
                    if index + 1 < len(args):
                        ordered.append((name, args[index + 1]))
                    index += 2
                    matched = True
                    break
                if argument.startswith(f"{option}="):
                    ordered.append((name, argument.split("=", 1)[1]))
                    index += 1
                    matched = True
                    break
            if not matched:
                index += 1
        ctx.meta["accuracy_mark_arguments"] = tuple(ordered)
        return super().parse_args(ctx, args)


def _finite_number(value: str, label: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise click.BadParameter(f"{label}必须是有限数字") from exc
    if not math.isfinite(number) or number < 0:
        raise click.BadParameter(f"{label}必须是有限非负数字")
    return number


def _mark_id(index: int) -> str:
    return f"accuracy_mark_{index + 1}"


def _validate_mark_category(category: str) -> None:
    if not SAFE_MARK_NAME.fullmatch(category):
        raise click.BadParameter("CATEGORY 必须是安全的单段目录名")


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
    _validate_mark_category(category)
    threshold = _finite_number(minimum, "MIN")
    label = parts[4] if len(parts) == 5 and parts[4] else f"{comparison} {metric}准确度低"
    return AccuracyMarkRule(
        id=_mark_id(index),
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
    _validate_mark_category(category)
    threshold = _finite_number(minimum_gap, "MIN_GAP")
    label = parts[3] if len(parts) == 4 and parts[3] else f"Online低于Comp {threshold:g}个百分点"
    return AccuracyMarkRule(
        id=_mark_id(index),
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
