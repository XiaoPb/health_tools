"""准确度命令的公共 Click 参数。"""

from typing import Optional, Tuple

import click

from health_tools.utils.accuracy import normalize_accuracy_thresholds


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
