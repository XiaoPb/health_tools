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
@click.option("--static-min", type=int, default=5, help="ACC静止检测最小连续帧数 (默认5)")
@click.option("--range-ratio", type=float, default=1.0, help="数据范围异常允许比例 (%, 默认1)")
@click.option("--frame-ratio", type=float, default=1.0, help="帧丢失允许比例 (%, 默认1)")
@click.option("--center-ratio", type=float, default=1.0, help="数据居中异常允许比例 (%, 默认1)")
@click.option("--ipd-ratio", type=float, default=1.0, help="Ipd超差允许比例 (%, 默认1)")
@click.option("--acc-ratio", type=float, default=1.0, help="ACC异常帧允许比例 (%, 默认1)")
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
    static_min: int,
    range_ratio: float,
    frame_ratio: float,
    center_ratio: float,
    ipd_ratio: float,
    acc_ratio: float,
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
    ) -> Tuple[Optional["FileCheckReport"], Optional["AccAnomalyReport"], Optional[object], str]:
        """处理单个文件，返回 (report, acc_report, ipd_detail, skip_reason)"""
        chip = chip_name or _detect_chip(csv_file)
        if not chip:
            return None, None, None, "无法识别芯片"

        try:
            chip_rule = RuleLoader.load_chip_rule(chip)
        except Exception:
            return None, None, None, f"无法加载规则 {chip}"

        handler = CSVHandler(chip_rule)
        try:
            _, df = handler.read(csv_file)
        except Exception as e:
            return None, None, None, f"读取失败: {e}"

        if df.empty:
            return None, None, None, "空文件"

        checker = DataChecker(chip_rule, tolerance=tolerance, static_min=static_min)
        report = FileCheckReport(file_path=csv_file, chip=chip)

        if "range" in check_set:
            report.results.append(checker.check_data_range(df, threshold_ratio=range_ratio))
        if "frame" in check_set:
            report.results.append(checker.check_frame_completeness(df, threshold_ratio=frame_ratio))
        if "center" in check_set:
            report.results.append(checker.check_data_centering(df, threshold_ratio=center_ratio))

        ipd_detail = None
        if "ipd" in check_set and chip.startswith("gh3036"):
            ipd_result = checker.check_ipd_conversion(df, threshold_ratio=ipd_ratio)
            report.results.append(ipd_result)
            if ipd_result.failed:
                ipd_detail = checker.build_ipd_detail(df)

        acc_report = None
        if "acc" in check_set:
            acc_report = checker.check_acc_anomaly(df)
            acc_report.file_path = csv_file
            report.results.append(checker.build_acc_result(acc_report, threshold_ratio=acc_ratio))

        return report, acc_report, ipd_detail, ""

    reports: List[FileCheckReport] = []
    acc_reports: Dict[Path, AccAnomalyReport] = {}
    ipd_details: Dict[Path, object] = {}

    with Progress(console=console) as progress:
        task = progress.add_task("检查中", total=len(files))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_file, f): f for f in files}
            for future in as_completed(futures):
                csv_file = futures[future]
                report, acc_report, ipd_detail, skip_reason = future.result()
                if report:
                    reports.append(report)
                    if acc_report:
                        acc_reports[csv_file] = acc_report
                    if ipd_detail is not None and not ipd_detail.empty:
                        ipd_details[csv_file] = ipd_detail
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

    ratios = {
        "range": range_ratio,
        "frame": frame_ratio,
        "center": center_ratio,
        "ipd": ipd_ratio,
        "acc": acc_ratio,
    }
    _print_criteria(check_set, tolerance, static_min, ratios)

    csv_out = Path(output_path) if output_path else _default_output(target)
    _save_report_csv(reports, acc_reports, csv_out)

    if ipd_details:
        out_dir = csv_out.parent
        for csv_file, detail_df in ipd_details.items():
            detail_path = out_dir / f"ipd_detail_{csv_file.stem}.csv"
            detail_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
        console.print(f"[green]Ipd超差详情已保存: {len(ipd_details)} 个文件[/green]")


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


def _print_acc_table(acc_reports: list) -> None:
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
    _print_sub_table("静止检测-X", acc_reports, lambda r: r.static_x)
    _print_sub_table("静止检测-Y", acc_reports, lambda r: r.static_y)
    _print_sub_table("静止检测-Z", acc_reports, lambda r: r.static_z)
    _print_sub_table("循环检测-XYZ", acc_reports, lambda r: r.cyclic_xyz)
    _print_sub_table("循环检测-X", acc_reports, lambda r: r.cyclic_x)
    _print_sub_table("循环检测-Y", acc_reports, lambda r: r.cyclic_y)
    _print_sub_table("循环检测-Z", acc_reports, lambda r: r.cyclic_z)

    console.print(
        f"ACC总计: {len(acc_reports)} 文件, "
        f"{anomaly_count} 异常, {len(acc_reports) - anomaly_count} 正常"
    )


def _print_criteria(check_set: set, tolerance: int, static_min: int, ratios: dict) -> None:
    """打印当前检查项及判断标准"""
    console.print("\n[dim]─── 检查标准 ───[/dim]")
    criteria = {
        "range": (
            "数据范围: Rawdata 在芯片ADC范围内 "
            f"(异常比例≤{ratios.get('range', 1.0):g}% 为Warning)"
        ),
        "frame": (
            "帧完整性: 帧号连续递增无跳帧 " f"(丢包率≤{ratios.get('frame', 1.0):g}% 为Warning)"
        ),
        "center": (
            "数据居中: Rawdata 在 0.3*2^23 ~ 0.85*2^23 范围内 "
            f"(异常比例≤{ratios.get('center', 1.0):g}% 为Warning)"
        ),
        "ipd": (
            f"Ipd转换: Ipd_pA 与 Rawdata 按AGC逐行计算, 误差 ≤ ±{tolerance} pA "
            f"(超差比例≤{ratios.get('ipd', 1.0):g}% 为Warning)"
        ),
        "acc": (
            f"ACC异常: 全零 / 静止(连续不变≥{static_min}帧) / 循环 "
            f"(异常帧比例≤{ratios.get('acc', 1.0):g}% 为Warning)"
        ),
    }
    for key in sorted(check_set):
        if key in criteria:
            console.print(f"  [dim]{criteria[key]}[/dim]")


def _save_report_csv(reports: list, acc_reports: dict, output_path: Path) -> None:
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
                    row.extend(_a(acc.static_x))
                    row.extend(_a(acc.static_y))
                    row.extend(_a(acc.static_z))
                    row.extend(_a(acc.cyclic_x))
                    row.extend(_a(acc.cyclic_y))
                    row.extend(_a(acc.cyclic_z))
                else:
                    row.extend(["-"] * 27)

            writer.writerow(row)

    console.print(f"[green]检查报告已保存: {output_path}[/green]")
