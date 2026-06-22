"""数据检查命令"""

from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("check")
@click.argument("path", type=click.Path(exists=True))
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)，不指定则自动识别")
@click.option(
    "--checks",
    help="指定检查项 (逗号分隔: range,ipd,frame,center,acc)，默认全部",
)
@click.option("--tolerance", type=int, default=50, help="Ipd转换误差容忍度 (pA, 默认50)")
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(),
    default=None,
    help="ACC异常报告CSV输出路径 (默认: <path>/acc_anomaly_report.csv)",
)
@click.option("-v", "--verbose", is_flag=True, help="显示详细信息")
def check_cmd(
    path: str,
    chip_name: Optional[str],
    checks: Optional[str],
    tolerance: int,
    output_path: Optional[str],
    verbose: bool,
) -> None:
    """检查PPG数据完整性和正确性"""
    from health_tools.core.checker import AccAnomalyReport, DataChecker, FileCheckReport
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import CSVHandler

    target = Path(path)
    if target.is_file():
        files = [target]
    else:
        files = sorted(target.rglob("*.csv"))
        if not files:
            console.print(f"[yellow]未找到CSV文件: {target}[/yellow]")
            return

    check_set = set(checks.split(",")) if checks else {"range", "ipd", "frame", "center", "acc"}
    reports = []
    acc_reports: List[AccAnomalyReport] = []

    for csv_file in files:
        chip = chip_name or _detect_chip(csv_file)
        if not chip:
            if verbose:
                console.print(f"[yellow]跳过（无法识别芯片）: {csv_file.name}[/yellow]")
            continue

        try:
            chip_rule = RuleLoader.load_chip_rule(chip)
        except Exception:
            if verbose:
                console.print(f"[yellow]跳过（无法加载规则 {chip}）: {csv_file.name}[/yellow]")
            continue

        handler = CSVHandler(chip_rule)
        try:
            _, df = handler.read(csv_file)
        except Exception as e:
            if verbose:
                console.print(f"[red]读取失败: {csv_file.name} ({e})[/red]")
            continue

        if df.empty:
            if verbose:
                console.print(f"[yellow]跳过（空文件）: {csv_file.name}[/yellow]")
            continue

        checker = DataChecker(chip_rule, tolerance=tolerance)
        report = FileCheckReport(file_path=csv_file, chip=chip)

        if "range" in check_set:
            report.results.append(checker.check_data_range(df))
        if "frame" in check_set:
            report.results.append(checker.check_frame_completeness(df))
        if "center" in check_set:
            report.results.append(checker.check_data_centering(df))
        if "ipd" in check_set and chip.startswith("gh3036"):
            report.results.append(checker.check_ipd_conversion(df))

        if "acc" in check_set:
            acc_report = checker.check_acc_anomaly(df)
            acc_report.file_path = csv_file
            acc_reports.append(acc_report)

        reports.append(report)

    if not reports and not acc_reports:
        console.print("[yellow]无可检查的文件[/yellow]")
        return

    if reports:
        _print_reports(reports, verbose)

    if acc_reports:
        _print_acc_table(acc_reports)
        csv_out = Path(output_path) if output_path else _default_acc_output(target)
        _save_acc_csv(acc_reports, csv_out)


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


def _print_reports(reports: list, verbose: bool) -> None:
    """打印检查报告"""
    passed_count = sum(1 for r in reports if r.all_passed)
    failed_count = len(reports) - passed_count

    for report in reports:
        status = "[green]PASS[/green]" if report.all_passed else "[red]FAIL[/red]"
        console.print(f"\n{status} {report.file_path.name} ({report.chip})")

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("检查项", min_width=10)
        table.add_column("结果", min_width=4)
        table.add_column("说明")

        for result in report.results:
            mark = "[green]✓[/green]" if result.passed else "[red]✗[/red]"
            table.add_row(result.name, mark, result.summary)

        console.print(table)

        if verbose:
            for result in report.results:
                if result.details:
                    console.print(f"  [dim]{result.name} 详情:[/dim]")
                    for detail in result.details:
                        console.print(f"    {detail}")

    console.print(f"\n总计: {len(reports)} 文件, {passed_count} 通过, {failed_count} 异常")


def _default_acc_output(target: Path) -> Path:
    """生成默认的ACC报告输出路径"""
    if target.is_file():
        return target.parent / "acc_anomaly_report.csv"
    return target / "acc_anomaly_report.csv"


def _print_acc_table(acc_reports: list) -> None:
    """打印ACC异常汇总表"""
    console.print("\n[bold cyan]ACC异常检测报告[/bold cyan]")

    table = Table(show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("文件名", min_width=12)
    table.add_column("总帧数", justify="right")
    table.add_column("全零次", justify="right")
    table.add_column("全零道")
    table.add_column("全零首帧", justify="right")
    table.add_column("全零最长帧", justify="right")
    table.add_column("静止次", justify="right")
    table.add_column("静止道")
    table.add_column("静止首帧", justify="right")
    table.add_column("静止最长帧", justify="right")
    table.add_column("循环次", justify="right")
    table.add_column("循环道")
    table.add_column("循环首帧", justify="right")
    table.add_column("循环最长帧", justify="right")

    anomaly_count = 0
    for r in acc_reports:
        if r.has_anomaly:
            anomaly_count += 1

        def _fmt(val: int) -> str:
            return str(val) if val >= 0 else "-"

        table.add_row(
            r.file_path.name,
            str(r.total_frames),
            str(r.zero_count),
            r.zero_channels if r.zero_count > 0 else "-",
            _fmt(r.zero_first_frame),
            str(r.zero_max_duration) if r.zero_count > 0 else "-",
            str(r.static_count),
            r.static_channels if r.static_count > 0 else "-",
            _fmt(r.static_first_frame),
            str(r.static_max_duration) if r.static_count > 0 else "-",
            str(r.cyclic_count),
            r.cyclic_channels if r.cyclic_count > 0 else "-",
            _fmt(r.cyclic_first_frame),
            str(r.cyclic_max_duration) if r.cyclic_count > 0 else "-",
        )

    console.print(table)
    console.print(
        f"ACC总计: {len(acc_reports)} 文件, "
        f"{anomaly_count} 异常, {len(acc_reports) - anomaly_count} 正常"
    )


def _save_acc_csv(acc_reports: list, output_path: Path) -> None:
    """将ACC异常报告保存为CSV"""
    import csv

    header = [
        "文件名",
        "总帧数",
        "全零次数",
        "全零通道",
        "全零首帧",
        "全零最长帧",
        "静止次数",
        "静止通道",
        "静止首帧",
        "静止最长帧",
        "循环次数",
        "循环通道",
        "循环首帧",
        "循环最长帧",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in acc_reports:
            writer.writerow(
                [
                    r.file_path.name,
                    r.total_frames,
                    r.zero_count,
                    r.zero_channels if r.zero_count > 0 else "-",
                    r.zero_first_frame if r.zero_first_frame >= 0 else "-",
                    r.zero_max_duration if r.zero_count > 0 else "-",
                    r.static_count,
                    r.static_channels if r.static_count > 0 else "-",
                    r.static_first_frame if r.static_first_frame >= 0 else "-",
                    r.static_max_duration if r.static_count > 0 else "-",
                    r.cyclic_count,
                    r.cyclic_channels if r.cyclic_count > 0 else "-",
                    r.cyclic_first_frame if r.cyclic_first_frame >= 0 else "-",
                    r.cyclic_max_duration if r.cyclic_count > 0 else "-",
                ]
            )

    console.print(f"[green]ACC异常报告已保存: {output_path}[/green]")
