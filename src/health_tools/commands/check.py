"""数据检查命令"""

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

console = Console()


@click.command("check")
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
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
    help="检查报告CSV输出路径 (默认: <path>/check_report.csv)",
)
@click.option("-w", "--workers", type=int, default=4, help="并行线程数 (默认4)")
@click.option("-v", "--verbose", is_flag=True, help="显示详细信息")
def check_cmd(
    input_path: str,
    chip_name: Optional[str],
    checks: Optional[str],
    tolerance: int,
    output_path: Optional[str],
    workers: int,
    verbose: bool,
) -> None:
    """检查PPG数据完整性和正确性"""
    from health_tools.core.checker import AccAnomalyReport, DataChecker, FileCheckReport
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import CSVHandler

    target = Path(input_path)
    if not target.exists():
        console.print(f"[red]路径不存在: {target}[/red]")
        return
    if target.is_file():
        files = [target]
    else:
        files = sorted(f for f in target.rglob("*.csv") if f.name != "check_report.csv")
        if not files:
            console.print(f"[yellow]未找到CSV文件: {target}[/yellow]")
            return

    console.print(f"找到 {len(files)} 个CSV文件, {workers} 线程处理中...")

    check_set = set(checks.split(",")) if checks else {"range", "ipd", "frame", "center", "acc"}

    def _process_file(
        csv_file: Path,
    ) -> Tuple[Optional["FileCheckReport"], Optional["AccAnomalyReport"], str]:
        """处理单个文件，返回 (report, acc_report, skip_reason)"""
        chip = chip_name or _detect_chip(csv_file)
        if not chip:
            return None, None, "无法识别芯片"

        try:
            chip_rule = RuleLoader.load_chip_rule(chip)
        except Exception:
            return None, None, f"无法加载规则 {chip}"

        handler = CSVHandler(chip_rule)
        try:
            _, df = handler.read(csv_file)
        except Exception as e:
            return None, None, f"读取失败: {e}"

        if df.empty:
            return None, None, "空文件"

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

        acc_report = None
        if "acc" in check_set:
            acc_report = checker.check_acc_anomaly(df)
            acc_report.file_path = csv_file

        return report, acc_report, ""

    reports: List[FileCheckReport] = []
    acc_reports: Dict[Path, AccAnomalyReport] = {}

    with Progress(console=console) as progress:
        task = progress.add_task("检查中", total=len(files))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_file, f): f for f in files}
            for future in as_completed(futures):
                csv_file = futures[future]
                report, acc_report, skip_reason = future.result()
                if report:
                    reports.append(report)
                    if acc_report:
                        acc_reports[csv_file] = acc_report
                elif verbose and skip_reason:
                    progress.console.print(
                        f"[yellow]跳过（{skip_reason}）: {csv_file.name}[/yellow]"
                    )
                progress.advance(task)

    if not reports:
        console.print("[yellow]无可检查的文件[/yellow]")
        return

    _print_reports(reports, verbose)

    if acc_reports:
        _print_acc_table(list(acc_reports.values()))

    csv_out = Path(output_path) if output_path else _default_output(target)
    _save_report_csv(reports, acc_reports, csv_out)


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
        status = "[green]PASS[/green]" if report.all_passed else "[red]FAIL[/red]"
        console.print(f"\n{status} {report.file_path.name} ({report.chip})")

        table = Table(show_header=True, header_style="bold", padding=(0, 1))
        table.add_column("检查项", min_width=10)
        table.add_column("结果", min_width=4)
        table.add_column("说明", no_wrap=True)

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


def _print_acc_table(acc_reports: list) -> None:
    """打印ACC异常汇总表（拆分为三个子表避免截断）"""
    console.print("\n[bold cyan]ACC异常检测报告[/bold cyan]")

    anomaly_count = sum(1 for r in acc_reports if r.has_anomaly)

    def _fmt(val: int) -> str:
        return str(val) if val >= 0 else "-"

    # 全零检测表
    table = Table(title="全零检测", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("文件名", no_wrap=True)
    table.add_column("总帧数", justify="right")
    table.add_column("次数", justify="right")
    table.add_column("通道")
    table.add_column("首帧", justify="right")
    table.add_column("最长帧", justify="right")
    for r in acc_reports:
        table.add_row(
            r.file_path.name,
            str(r.total_frames),
            str(r.zero_count),
            r.zero_channels if r.zero_count > 0 else "-",
            _fmt(r.zero_first_frame),
            str(r.zero_max_duration) if r.zero_count > 0 else "-",
        )
    console.print(table)

    # 静止检测表
    table = Table(title="静止检测", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("文件名", no_wrap=True)
    table.add_column("次数", justify="right")
    table.add_column("通道")
    table.add_column("首帧", justify="right")
    table.add_column("最长帧", justify="right")
    for r in acc_reports:
        table.add_row(
            r.file_path.name,
            str(r.static_count),
            r.static_channels if r.static_count > 0 else "-",
            _fmt(r.static_first_frame),
            str(r.static_max_duration) if r.static_count > 0 else "-",
        )
    console.print(table)

    # 循环检测表
    table = Table(title="循环检测", show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("文件名", no_wrap=True)
    table.add_column("次数", justify="right")
    table.add_column("通道")
    table.add_column("首帧", justify="right")
    table.add_column("最长帧", justify="right")
    for r in acc_reports:
        table.add_row(
            r.file_path.name,
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


def _save_report_csv(reports: list, acc_reports: dict, output_path: Path) -> None:
    """将全部检查结果保存到统一CSV文件"""
    header = ["文件名", "芯片"]

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
                "ACC全零通道",
                "ACC全零首帧",
                "ACC全零最长帧",
                "ACC静止次数",
                "ACC静止通道",
                "ACC静止首帧",
                "ACC静止最长帧",
                "ACC循环次数",
                "ACC循环通道",
                "ACC循环首帧",
                "ACC循环最长帧",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for report in reports:
            row = [report.file_path.name, report.chip]

            result_map = {r.name: r for r in report.results}
            for name in check_names:
                if name in result_map:
                    r = result_map[name]
                    row.append("PASS" if r.passed else "FAIL")
                    row.append(r.summary)
                else:
                    row.append("-")
                    row.append("-")

            if has_acc:
                acc = acc_reports.get(report.file_path)
                if acc:
                    row.extend(
                        [
                            acc.zero_count,
                            acc.zero_channels if acc.zero_count > 0 else "-",
                            acc.zero_first_frame if acc.zero_first_frame >= 0 else "-",
                            acc.zero_max_duration if acc.zero_count > 0 else "-",
                            acc.static_count,
                            acc.static_channels if acc.static_count > 0 else "-",
                            acc.static_first_frame if acc.static_first_frame >= 0 else "-",
                            acc.static_max_duration if acc.static_count > 0 else "-",
                            acc.cyclic_count,
                            acc.cyclic_channels if acc.cyclic_count > 0 else "-",
                            acc.cyclic_first_frame if acc.cyclic_first_frame >= 0 else "-",
                            acc.cyclic_max_duration if acc.cyclic_count > 0 else "-",
                        ]
                    )
                else:
                    row.extend(["-"] * 12)

            writer.writerow(row)

    console.print(f"[green]检查报告已保存: {output_path}[/green]")
