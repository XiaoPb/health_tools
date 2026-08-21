"""数据检查命令"""

import csv
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import click
from click.core import ParameterSource
from rich.console import Console
from rich.table import Table

from health_tools.commands.accuracy_options import (
    OrderedAccuracyMarksCommand,
    parse_accuracy_min,
    parse_accuracy_thresholds,
    parse_online_comp_gap,
)

console = Console()

if TYPE_CHECKING:
    pass


@click.command("check", cls=OrderedAccuracyMarksCommand)
@click.option("-i", "--input", "input_path", help="输入CSV文件或目录")
@click.option("-r", "--rule", "rule_file", help="check 规则文件路径或内置规则名")
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)，不指定则自动识别")
@click.option(
    "--checks",
    help="指定检查项 (逗号分隔: range,ipd,frame,center,acc,agc,ref)，默认全部",
)
@click.option("--tolerance", type=int, default=50, help="Ipd转换误差容忍度 (pA, 默认50)")
@click.option("--static-min", type=int, default=5, help="ACC静止检测最小连续帧数 (默认5)")
@click.option("--range-ratio", type=float, default=1.0, help="数据范围异常允许比例 (%, 默认1)")
@click.option("--frame-ratio", type=float, default=1.0, help="帧丢失允许比例 (%, 默认1)")
@click.option("--center-ratio", type=float, default=5.0, help="数据居中异常允许比例 (%, 默认5)")
@click.option("--ipd-ratio", type=float, default=1.0, help="Ipd超差允许比例 (%, 默认1)")
@click.option("--acc-ratio", type=float, default=1.0, help="ACC异常帧允许比例 (%, 默认1)")
@click.option("--acc-axis/--no-acc-axis", default=False, help="ACC单轴异常也计入结果")
@click.option("--check-timestamp", "timestamp_column", help="指定时间戳列并检查间隔稳定性")
@click.option(
    "--timestamp-ratio", type=float, default=20.0, help="时间戳间隔百分比容差 (%, 默认20)"
)
@click.option("--timestamp-ms", type=float, default=None, help="时间戳间隔固定毫秒容差")
@click.option(
    "--timestamp-fail-ratio", type=float, default=1.0, help="时间戳异常间隔允许比例 (%, 默认1)"
)
@click.option(
    "--timestamp-base-ms",
    type=float,
    default=None,
    help="指定期望时间戳间隔基准 (毫秒)，偏差超过20%则FAIL",
)
@click.option("--ref-hr-column", help="心率金标列名；指定后启用心率金标检查")
@click.option("--ref-spo2-column", help="血氧金标列名；指定后启用血氧金标检查")
@click.option(
    "--ref-sample-rate",
    type=click.FloatRange(min=0.0, min_open=True),
    default=25.0,
    show_default=True,
    help="金标采样率（Hz）",
)
@click.option(
    "--ref-stale-seconds",
    type=click.FloatRange(min=0.0, min_open=True),
    default=5.0,
    show_default=True,
    help="金标连续不变判定时长（秒）",
)
@click.option(
    "--ref-step-threshold",
    type=click.FloatRange(min=0.0),
    default=8.0,
    show_default=True,
    help="金标阶跃相邻变化阈值",
)
@click.option(
    "--scene-regex",
    type=str,
    default=None,
    help="按文件相对路径提取场景的正则（需包含命名组 scene）",
)
@click.option("--accuracy/--no-accuracy", "accuracy_enabled", default=False, help="统计准确度")
@click.option("--accuracy-ref-column", help="准确度金标列名")
@click.option("--accuracy-online-column", help="Online 结果列名")
@click.option("--accuracy-comp-column", help="Comp 结果列名")
@click.option(
    "--accuracy-thresholds",
    callback=parse_accuracy_thresholds,
    help="逗号分隔的准确度阈值；默认采用规则或 5,10,15",
)
@click.option(
    "--accuracy-inclusive/--accuracy-strict",
    default=False,
    help="阈值命中使用 <=；默认严格使用 <",
)
@click.option(
    "--accuracy-min",
    multiple=True,
    metavar="COMPARISON:METRIC:MIN:CATEGORY[:LABEL]",
    help="标定 Online/Comp 准确度低于阈值的文件",
)
@click.option(
    "--online-comp-gap",
    multiple=True,
    metavar="METRIC:MIN_GAP:CATEGORY[:LABEL]",
    help="标定 Online 准确度低于 Comp 的文件",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="检查报告CSV输出路径 (默认: <path>/check_report.csv)",
)
@click.option("--sort", "sort_report", is_flag=True, help="读取检查报告并分拣正常/异常文件")
@click.option(
    "--report", "report_path", type=click.Path(), default=None, help="分拣使用的检查报告路径"
)
@click.option("--sort-output", "sort_output", type=click.Path(), default=None, help="分拣输出目录")
@click.option("-w", "--workers", type=int, default=4, help="并行线程数 (默认4)")
@click.option("-v", "--verbose", is_flag=True, help="显示详细信息")
@click.pass_context
def check_cmd(
    ctx: click.Context,
    input_path: Optional[str],
    rule_file: Optional[str],
    chip_name: Optional[str],
    checks: Optional[str],
    tolerance: int,
    static_min: int,
    range_ratio: float,
    frame_ratio: float,
    center_ratio: float,
    ipd_ratio: float,
    acc_ratio: float,
    acc_axis: bool,
    timestamp_column: Optional[str],
    timestamp_ratio: float,
    timestamp_ms: Optional[float],
    timestamp_fail_ratio: float,
    timestamp_base_ms: Optional[float],
    ref_hr_column: Optional[str],
    ref_spo2_column: Optional[str],
    ref_sample_rate: float,
    ref_stale_seconds: float,
    ref_step_threshold: float,
    scene_regex: Optional[str],
    accuracy_enabled: bool,
    accuracy_ref_column: Optional[str],
    accuracy_online_column: Optional[str],
    accuracy_comp_column: Optional[str],
    accuracy_thresholds: Optional[Tuple[float, ...]],
    accuracy_inclusive: bool,
    accuracy_min: Tuple[str, ...],
    online_comp_gap: Tuple[str, ...],
    output_path: Optional[str],
    sort_report: bool,
    report_path: Optional[str],
    sort_output: Optional[str],
    workers: int,
    verbose: bool,
) -> None:
    """检查PPG数据完整性和正确性"""
    from health_tools.api import CheckRequest, run_check
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch
    from health_tools.models.rules import CheckAccuracyRule, CheckRule
    from health_tools.rules.loader import RuleLoader

    try:
        rule = RuleLoader.load_check_rule(rule_file) if rule_file else CheckRule()
    except Exception as exc:
        raise click.ClickException(f"无法加载 check 规则 {rule_file}: {exc}") from exc

    def effective(name: str, cli_value: Any, rule_value: Any, default: Any) -> Any:
        if ctx.get_parameter_source(name) == ParameterSource.COMMANDLINE:
            return cli_value
        return rule_value if rule_file else default

    ratios = rule.ratios
    timestamp = rule.timestamp
    reference = rule.reference
    accuracy = rule.accuracy if rule_file else CheckAccuracyRule()
    checks = effective("checks", checks, ",".join(rule.checks), None)
    chip_name = effective("chip_name", chip_name, rule.chip, None)
    tolerance = effective("tolerance", tolerance, rule.tolerance, 50)
    static_min = effective("static_min", static_min, rule.static_min, 5)
    range_ratio = effective("range_ratio", range_ratio, ratios.range, 1.0)
    frame_ratio = effective("frame_ratio", frame_ratio, ratios.frame, 1.0)
    center_ratio = effective("center_ratio", center_ratio, ratios.center, 5.0)
    ipd_ratio = effective("ipd_ratio", ipd_ratio, ratios.ipd, 1.0)
    acc_ratio = effective("acc_ratio", acc_ratio, ratios.acc, 1.0)
    acc_axis = effective("acc_axis", acc_axis, rule.acc_axis, False)
    timestamp_column = effective("timestamp_column", timestamp_column, timestamp.column, None)
    timestamp_ratio = effective("timestamp_ratio", timestamp_ratio, timestamp.ratio, 20.0)
    timestamp_ms = effective("timestamp_ms", timestamp_ms, timestamp.ms, None)
    timestamp_fail_ratio = effective(
        "timestamp_fail_ratio", timestamp_fail_ratio, timestamp.fail_ratio, 1.0
    )
    timestamp_base_ms = effective("timestamp_base_ms", timestamp_base_ms, timestamp.base_ms, None)
    ref_hr_column = effective("ref_hr_column", ref_hr_column, reference.hr_column, None)
    ref_spo2_column = effective("ref_spo2_column", ref_spo2_column, reference.spo2_column, None)
    ref_sample_rate = effective("ref_sample_rate", ref_sample_rate, reference.sample_rate, 25.0)
    ref_stale_seconds = effective(
        "ref_stale_seconds", ref_stale_seconds, reference.stale_seconds, 5.0
    )
    ref_step_threshold = effective(
        "ref_step_threshold", ref_step_threshold, reference.step_threshold, 8.0
    )
    scene_regex = effective("scene_regex", scene_regex, rule.scene_regex, None)
    accuracy_enabled = effective("accuracy_enabled", accuracy_enabled, accuracy.enabled, False)
    accuracy_ref_column = effective(
        "accuracy_ref_column", accuracy_ref_column, accuracy.ref_column, "REF_RESULT0"
    )
    accuracy_online_column = effective(
        "accuracy_online_column", accuracy_online_column, accuracy.online_column, "ALGO_RESULT0"
    )
    accuracy_comp_column = effective(
        "accuracy_comp_column", accuracy_comp_column, accuracy.comp_column, "COMP_RESULT0"
    )
    accuracy_inclusive = effective(
        "accuracy_inclusive", accuracy_inclusive, accuracy.inclusive, False
    )

    try:
        ordered_mark_arguments = ctx.meta.get("accuracy_mark_arguments", ())
        cli_marks = tuple(
            (
                parse_accuracy_min(value, index)
                if name == "accuracy_min"
                else parse_online_comp_gap(value, index)
            )
            for index, (name, value) in enumerate(ordered_mark_arguments)
        )
        categories = [mark.category for mark in cli_marks]
        if len(categories) != len(set(categories)):
            duplicate = next(category for category in categories if categories.count(category) > 1)
            raise click.BadParameter(f"accuracy mark category 重复: {duplicate}")
        mark_ids = [mark.id for mark in cli_marks]
        if len(mark_ids) != len(set(mark_ids)) or any(
            not mark_id.replace("_", "").replace("-", "").isalnum() for mark_id in mark_ids
        ):
            raise click.BadParameter("accuracy mark id 必须唯一且为安全的单段名称")
    except click.BadParameter as exc:
        raise click.UsageError(str(exc)) from exc
    accuracy_marks = cli_marks if accuracy_min or online_comp_gap else accuracy.marks

    inferred_report_path = report_path
    if sort_report and inferred_report_path is None:
        if output_path:
            inferred_report_path = output_path
        elif input_path:
            input_target = Path(input_path)
            inferred_report_path = str(
                input_target.parent / "check_report.csv"
                if input_target.exists() and input_target.is_file()
                else input_target / "check_report.csv"
            )

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_check(
                CheckRequest(
                    input_path=Path(input_path) if input_path else None,
                    rule_file=rule_file,
                    chip_name=chip_name,
                    checks=checks,
                    tolerance=tolerance,
                    static_min=static_min,
                    range_ratio=range_ratio,
                    frame_ratio=frame_ratio,
                    center_ratio=center_ratio,
                    ipd_ratio=ipd_ratio,
                    acc_ratio=acc_ratio,
                    acc_axis=acc_axis,
                    timestamp_column=timestamp_column,
                    timestamp_ratio=timestamp_ratio,
                    timestamp_ms=timestamp_ms,
                    timestamp_fail_ratio=timestamp_fail_ratio,
                    timestamp_base_ms=timestamp_base_ms,
                    ref_hr_column=ref_hr_column,
                    ref_spo2_column=ref_spo2_column,
                    ref_sample_rate=ref_sample_rate,
                    ref_stale_seconds=ref_stale_seconds,
                    ref_step_threshold=ref_step_threshold,
                    scene_regex=scene_regex,
                    accuracy_enabled=accuracy_enabled,
                    accuracy_ref_column=accuracy_ref_column,
                    accuracy_online_column=accuracy_online_column,
                    accuracy_comp_column=accuracy_comp_column,
                    accuracy_methods=accuracy.methods,
                    accuracy_thresholds=accuracy_thresholds,
                    accuracy_custom_thresholds=accuracy.thresholds,
                    accuracy_inclusive=accuracy_inclusive,
                    accuracy_marks=accuracy_marks,
                    output_path=Path(output_path) if output_path else None,
                    sort_report=sort_report,
                    report_path=Path(inferred_report_path) if inferred_report_path else None,
                    sort_output=Path(sort_output) if sort_output else None,
                    workers=workers,
                ),
                context=context,
            )
        )
    print_batch("检查处理结果", result.batch, console, verbose)
    if verbose:
        for item in result.batch.items:
            if item.status.value == "SKIP":
                console.print(f"[yellow]跳过（{item.reason}）: {Path(item.input).name}[/yellow]")
    if result.sort_counts:
        category_order = (
            "frame",
            "range",
            "acc_fail",
            "acc_warning",
            "timestamp",
            "center",
            "reference",
            "frame_warning",
            "agc",
            "ipd",
            "total_fail",
            "normal",
        )
        extra_categories = sorted(set(result.sort_counts) - set(category_order) - {"skipped"})
        distribution = ", ".join(
            f"{category}={result.sort_counts.get(category, 0)}"
            for category in (*category_order, *extra_categories)
        )
        console.print(
            "[green]分拣完成[/green]: "
            f"{distribution}, 跳过={result.sort_counts.get('skipped', 0)}"
        )
    if result.report_path:
        console.print(f"[green]检查报告已保存: {result.report_path}[/green]")
        if result.compact_report_path:
            console.print(f"[green]精简报告已保存: {result.compact_report_path}[/green]")
    elif not result.sort_counts:
        console.print("[yellow]无可检查的文件[/yellow]")
    return


def _detect_chip(csv_file: Path) -> Optional[str]:
    """从CSV文件info行自动识别芯片型号"""
    try:
        with open(csv_file, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
    except Exception:
        return None

    first_lower = first_line.lower()
    if "gh3036" in first_lower:
        return "gh3036"
    elif "gh3220" in first_lower:
        return "gh3220"
    elif "gh3300" in first_lower:
        return "gh3300"
    return None


def _check_rule_mismatch(
    checker,
    df,
    check_set: set,
    timestamp_column: Optional[str] = None,
    chip: str = "",
    require_acc_columns: bool = False,
    ref_hr_column: Optional[str] = None,
    ref_spo2_column: Optional[str] = None,
) -> str:
    """检查CSV列结构是否满足本次启用的检查项，不匹配则返回跳过原因。"""
    missing: List[str] = []

    data_cols = [c for c in checker._get_data_columns() if c in df.columns]
    frame_col = checker._resolve_frame_column(df)

    if "range" in check_set and not data_cols:
        missing.append("数据列")
    if "center" in check_set and not data_cols:
        missing.append("数据列")
    if "frame" in check_set and not frame_col:
        missing.append("帧号列")
    if "ipd" in check_set and chip.startswith("gh3036"):
        ipd_cols = [c for c in checker._get_ipd_columns() if c in df.columns]
        if not ipd_cols or not data_cols:
            missing.append("Ipd/Rawdata列")
    if require_acc_columns and not checker._resolve_acc_columns(df):
        missing.append("ACC列")
    if timestamp_column and timestamp_column not in df.columns:
        missing.append(f"时间戳列 {timestamp_column}")
    if "ref" in check_set:
        if ref_hr_column and ref_hr_column not in df.columns:
            missing.append(f"心率金标列 {ref_hr_column}")
        if ref_spo2_column and ref_spo2_column not in df.columns:
            missing.append(f"血氧金标列 {ref_spo2_column}")

    if not missing:
        return ""

    missing_text = "、".join(dict.fromkeys(missing))
    return f"列结构不符合规则，缺少 {missing_text}"


def _default_output(target: Path) -> Path:
    """生成默认的报告输出路径"""
    if target.is_file():
        return target.parent / "check_report.csv"
    return target / "check_report.csv"


def _print_reports(reports: list, verbose: bool) -> None:
    """打印检查报告"""
    passed_count = sum(1 for r in reports if r.all_passed)
    failed_count = len(reports) - passed_count

    for report in reports:
        if not report.results:
            continue
        status = "[green]PASS[/green]" if report.all_passed else "[red]FAIL[/red]"
        console.print(f"\n{status} {report.file_path.name} ({report.chip})")

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("检查项", min_width=10)
        table.add_column("结果", min_width=4)
        table.add_column("说明", no_wrap=True)

        for result in report.results:
            mark = _format_result_status(result.status)
            table.add_row(result.name, mark, result.summary)

        console.print(table)

        if verbose:
            for result in report.results:
                if result.details:
                    console.print(f"  [dim]{result.name} 详情:[/dim]")
                    for detail in result.details:
                        console.print(f"    {detail}")

    console.print(f"\n总计: {len(reports)} 文件, {passed_count} 通过, {failed_count} 异常")


def _format_result_status(status: str) -> str:
    """格式化单项检查状态"""
    if status == "PASS":
        return "[green]Pass[/green]"
    if status == "WARNING":
        return "[yellow]Warning[/yellow]"
    return "[red]Fail[/red]"


def _print_acc_table(acc_reports: list, include_single_axis: bool = False) -> None:
    """打印ACC异常汇总表（按通道拆表，仅展示有异常的）"""
    console.print("\n[bold cyan]ACC异常检测报告[/bold cyan]")

    anomaly_count = sum(1 for r in acc_reports if r.has_anomaly)

    def _fmt(val: int) -> str:
        return str(val) if val >= 0 else "-"

    def _print_sub_table(
        title: str, reports: list, get_anomaly, show_total_frames: bool = False
    ) -> None:
        items = [(r, get_anomaly(r)) for r in reports if get_anomaly(r).count > 0]
        if not items:
            return
        table = Table(title=title, show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("文件名", no_wrap=True)
        if show_total_frames:
            table.add_column("总帧数", justify="right")
        table.add_column("次数", justify="right")
        table.add_column("最长帧", justify="right")
        table.add_column("前10次帧号")
        for r, a in items:
            row = [r.file_path.name]
            if show_total_frames:
                row.append(str(r.total_frames))
            frames_str = ",".join(str(f) for f in a.frames[:10])
            row.extend([str(a.count), str(a.max_duration), frames_str])
            table.add_row(*row)
        console.print(table)

    _print_sub_table("全零检测", acc_reports, lambda r: r.zero, show_total_frames=True)
    _print_sub_table("静止检测-XYZ", acc_reports, lambda r: r.static_xyz)
    _print_sub_table("循环检测-XYZ", acc_reports, lambda r: r.cyclic_xyz)
    if include_single_axis:
        _print_sub_table("静止检测-X", acc_reports, lambda r: r.static_x)
        _print_sub_table("静止检测-Y", acc_reports, lambda r: r.static_y)
        _print_sub_table("静止检测-Z", acc_reports, lambda r: r.static_z)
        _print_sub_table("循环检测-X", acc_reports, lambda r: r.cyclic_x)
        _print_sub_table("循环检测-Y", acc_reports, lambda r: r.cyclic_y)
        _print_sub_table("循环检测-Z", acc_reports, lambda r: r.cyclic_z)

    console.print(
        f"ACC总计: {len(acc_reports)} 文件, "
        f"{anomaly_count} 异常, {len(acc_reports) - anomaly_count} 正常"
    )


def _print_criteria(
    check_set: set,
    tolerance: int,
    static_min: int,
    ratios: dict,
    timestamp_column: Optional[str] = None,
    timestamp_ratio: float = 20.0,
    timestamp_ms: Optional[float] = None,
    timestamp_base_ms: Optional[float] = None,
    acc_axis: bool = False,
) -> None:
    """打印当前检查项及判断标准"""
    console.print("\n[dim]─── 检查标准 ───[/dim]")
    criteria = {
        "range": (
            "数据范围: Rawdata 在规则ADC范围内 "
            "(优先 adc_offset ~ adc_offset+adc_full_scale) "
            f"(异常比例≤{ratios.get('range', 1.0):g}% 为Warning)"
        ),
        "frame": (
            "帧完整性: 帧号连续递增无跳帧 " f"(丢包率≤{ratios.get('frame', 1.0):g}% 为Warning)"
        ),
        "center": (
            "数据居中: 判断时使用 Rawdata-adc_offset，展示范围为 "
            "0.3*2^23+adc_offset ~ 0.85*2^23+adc_offset "
            f"(异常比例≤{ratios.get('center', 1.0):g}% 为Warning)"
        ),
        "ipd": (
            f"Ipd转换: Ipd_pA 与 Rawdata 按AGC逐行计算, 误差 ≤ ±{tolerance} pA "
            f"(超差比例≤{ratios.get('ipd', 1.0):g}% 为Warning)"
        ),
        "acc": (
            f"ACC异常: 默认仅XYZ同时异常，{'包含' if acc_axis else '不包含'}单轴异常；"
            f"全零 / 静止(连续不变≥{static_min}帧) / 循环 "
            f"(异常帧比例≤{ratios.get('acc', 1.0):g}% 为Warning)"
        ),
    }
    for key in sorted(check_set):
        if key in criteria:
            console.print(f"  [dim]{criteria[key]}[/dim]")
    if timestamp_column:
        ms_text = f", 固定容差±{timestamp_ms:g}ms" if timestamp_ms is not None else ""
        base_text = (
            f", 指定基准 {timestamp_base_ms:g}ms，偏差超过20%为FAIL"
            if timestamp_base_ms is not None
            else ""
        )
        console.print(
            f"  [dim]时间戳间隔: 列 {timestamp_column}, "
            f"相邻间隔偏差≤±{timestamp_ratio:g}%{ms_text}{base_text} "
            f"(异常比例≤{ratios.get('timestamp', 1.0):g}% 为Warning)[/dim]"
        )


def _save_report_csv(
    reports: list,
    acc_reports: dict,
    output_path: Path,
    base_dir: Optional[Path] = None,
    include_acc_axis: bool = False,
) -> None:
    """兼容旧命令层入口，委托 API 层生成唯一报告。"""
    from health_tools.api.check_operation import _save_report

    _save_report(reports, acc_reports, output_path, base_dir or output_path.parent, include_acc_axis)
    return

    """将全部检查结果保存到统一CSV文件"""
    header = ["文件名", "芯片", "总异常(结果)"]

    check_names = []
    for report in reports:
        for result in report.results:
            if result.name not in check_names:
                check_names.append(result.name)

    for name in check_names:
        header.append(f"{name}(结果)")
        header.append(f"{name}(说明)")

    has_acc = bool(acc_reports)
    if has_acc:
        header.extend(
            [
                "ACC全零次数",
                "ACC全零最长帧",
                "ACC全零前10帧",
                "ACC静止XYZ次数",
                "ACC静止XYZ最长帧",
                "ACC静止XYZ前10帧",
                "ACC循环XYZ次数",
                "ACC循环XYZ最长帧",
                "ACC循环XYZ前10帧",
            ]
        )
        if include_acc_axis:
            header.extend(
                [
                    "ACC静止X次数",
                    "ACC静止X最长帧",
                    "ACC静止X前10帧",
                    "ACC静止Y次数",
                    "ACC静止Y最长帧",
                    "ACC静止Y前10帧",
                    "ACC静止Z次数",
                    "ACC静止Z最长帧",
                    "ACC静止Z前10帧",
                    "ACC循环X次数",
                    "ACC循环X最长帧",
                    "ACC循环X前10帧",
                    "ACC循环Y次数",
                    "ACC循环Y最长帧",
                    "ACC循环Y前10帧",
                    "ACC循环Z次数",
                    "ACC循环Z最长帧",
                    "ACC循环Z前10帧",
                ]
            )

    header.extend(["场景分类", "文件相对路径"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for report in reports:
            row = [report.file_path.name, report.chip, report.total_status]

            result_map = {r.name: r for r in report.results}
            for name in check_names:
                if name in result_map:
                    r = result_map[name]
                    row.append(r.status)
                    row.append(r.summary)
                else:
                    row.append("-")
                    row.append("-")

            if has_acc:
                acc = acc_reports.get(report.file_path)
                if acc:

                    def _a(a):
                        """输出单个AccChannelAnomaly的三列: 次数,最长帧,前10帧"""
                        if a.count > 0:
                            frames_str = ",".join(str(f) for f in a.frames[:10])
                            return [a.count, a.max_duration, frames_str]
                        return [0, "-", "-"]

                    row.extend(_a(acc.zero))
                    row.extend(_a(acc.static_xyz))
                    row.extend(_a(acc.cyclic_xyz))
                    if include_acc_axis:
                        row.extend(_a(acc.static_x))
                        row.extend(_a(acc.static_y))
                        row.extend(_a(acc.static_z))
                        row.extend(_a(acc.cyclic_x))
                        row.extend(_a(acc.cyclic_y))
                        row.extend(_a(acc.cyclic_z))
                else:
                    acc_column_count = 27 if include_acc_axis else 9
                    row.extend(["-"] * acc_column_count)

            row.extend(
                [
                    getattr(report, "scene", "default"),
                    _relative_report_path(report.file_path, base_dir),
                ]
            )
            writer.writerow(row)

    console.print(f"[green]检查报告已保存: {output_path}[/green]")


def _relative_report_path(file_path: Path, base_dir: Optional[Path]) -> str:
    """生成写入报告的相对文件路径。"""
    if base_dir is None:
        return file_path.name
    try:
        return file_path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return file_path.name


def _sort_report_files(report_path: Path, output_dir: Path) -> Dict[str, int]:
    """根据检查报告按异常优先级移动文件，并生成分类列表CSV。"""
    from health_tools.api.check_operation import _sort_category

    rows = _read_report_rows(report_path)
    if not rows:
        raise click.ClickException(f"检查报告为空: {report_path}")

    fieldnames = rows[0].keys()
    required = {"文件名", "总异常(结果)", "文件相对路径"}
    missing = required - set(fieldnames)
    if missing:
        raise click.ClickException(
            "检查报告缺少必要列: "
            + ", ".join(sorted(missing))
            + "，请重新运行 check 生成带文件相对路径的新报告"
        )

    records: Dict[str, List[List[str]]] = {"normal": [], "abnormal": []}
    stats: Dict[str, int] = {"skipped": 0}
    report_dir = report_path.parent

    for row in rows:
        rel_path_text = row.get("文件相对路径", "").strip()
        file_name = row.get("文件名", "").strip()
        scene = row.get("场景分类", "default") or "default"
        category = _sort_category(row)
        bucket = "normal" if category == "normal" else "abnormal"
        category_records = records[bucket]
        if not rel_path_text:
            category_records.append(
                [file_name, rel_path_text, "", "跳过", "文件相对路径为空", category, scene]
            )
            stats["skipped"] += 1
            continue

        rel_path = Path(rel_path_text)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            category_records.append(
                [file_name, rel_path_text, "", "跳过", "文件相对路径非法", category, scene]
            )
            stats["skipped"] += 1
            continue

        target_dir = (
            output_dir / "normal" if category == "normal" else output_dir / "abnormal" / category
        )
        src_path = report_dir / rel_path
        dst_path = target_dir / rel_path

        if not src_path.exists():
            category_records.append(
                [file_name, rel_path_text, str(dst_path), "跳过", "源文件不存在", category, scene]
            )
            stats["skipped"] += 1
            continue
        if dst_path.exists():
            category_records.append(
                [file_name, rel_path_text, str(dst_path), "跳过", "目标文件已存在", category, scene]
            )
            stats["skipped"] += 1
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        category_records.append(
            [file_name, rel_path_text, str(dst_path), "已移动", "", category, scene]
        )
        stats[category] = stats.get(category, 0) + 1

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_sort_list(output_dir / "normal_files.csv", records["normal"])
    _write_sort_list(output_dir / "abnormal_files.csv", records["abnormal"])
    return stats


def _read_report_rows(report_path: Path) -> List[Dict[str, str]]:
    with open(report_path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _append_sort_record(
    status: str,
    normal_records: List[List[str]],
    abnormal_records: List[List[str]],
    record: List[str],
) -> None:
    if status == "PASS":
        normal_records.append(record)
    else:
        abnormal_records.append(record)


def _write_sort_list(path: Path, records: List[List[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["文件名", "文件相对路径", "目标路径", "状态", "原因", "分类", "场景分类"])
        writer.writerows(records)
