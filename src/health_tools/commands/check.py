"""数据检查命令"""

import csv
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table
from health_tools.utils.reporting import ResultCollector, print_summary

console = Console()

if TYPE_CHECKING:
    import pandas as pd


@click.command("check")
@click.option("-i", "--input", "input_path", help="输入CSV文件或目录")
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)，不指定则自动识别")
@click.option(
    "--checks",
    help="指定检查项 (逗号分隔: range,ipd,frame,center,acc)，默认全部",
)
@click.option("--tolerance", type=int, default=50, help="Ipd转换误差容忍度 (pA, 默认50)")
@click.option("--static-min", type=int, default=5, help="ACC静止检测最小连续帧数 (默认5)")
@click.option("--range-ratio", type=float, default=1.0, help="数据范围异常允许比例 (%, 默认1)")
@click.option("--frame-ratio", type=float, default=1.0, help="帧丢失允许比例 (%, 默认1)")
@click.option("--center-ratio", type=float, default=5.0, help="数据居中异常允许比例 (%, 默认5)")
@click.option("--ipd-ratio", type=float, default=1.0, help="Ipd超差允许比例 (%, 默认1)")
@click.option("--acc-ratio", type=float, default=1.0, help="ACC异常帧允许比例 (%, 默认1)")
@click.option("--check-timestamp", "timestamp_column", help="指定时间戳列并检查间隔稳定性")
@click.option(
    "--timestamp-ratio", type=float, default=20.0, help="时间戳间隔百分比容差 (%, 默认20)"
)
@click.option("--timestamp-ms", type=float, default=None, help="时间戳间隔固定毫秒容差")
@click.option(
    "--timestamp-fail-ratio", type=float, default=1.0, help="时间戳异常间隔允许比例 (%, 默认1)"
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
def check_cmd(
    input_path: Optional[str],
    chip_name: Optional[str],
    checks: Optional[str],
    tolerance: int,
    static_min: int,
    range_ratio: float,
    frame_ratio: float,
    center_ratio: float,
    ipd_ratio: float,
    acc_ratio: float,
    timestamp_column: Optional[str],
    timestamp_ratio: float,
    timestamp_ms: Optional[float],
    timestamp_fail_ratio: float,
    output_path: Optional[str],
    sort_report: bool,
    report_path: Optional[str],
    sort_output: Optional[str],
    workers: int,
    verbose: bool,
) -> None:
    """检查PPG数据完整性和正确性"""
    from health_tools.core.checker import AccAnomalyReport, DataChecker, FileCheckReport
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import CSVHandler

    if sort_report:
        if not sort_output:
            raise click.ClickException("使用 --sort 时必须指定 --sort-output")
        report = Path(report_path) if report_path else Path.cwd() / "check_report.csv"
        if not report.exists():
            raise click.ClickException(f"检查报告不存在: {report}，请指定 --report 或先运行 check")
        stats = _sort_report_files(report, Path(sort_output))
        console.print(
            "[green]分拣完成[/green]: "
            f"{stats['normal']} 正常, {stats['abnormal']} 异常, {stats['skipped']} 跳过"
        )
        return

    if not input_path:
        raise click.ClickException("普通检查模式必须指定 -i/--input")

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
    ) -> Tuple[
        Optional["FileCheckReport"],
        Optional["AccAnomalyReport"],
        Optional["pd.DataFrame"],
        str,
    ]:
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
        mismatch_reason = _check_rule_mismatch(
            checker,
            df,
            check_set,
            timestamp_column=timestamp_column,
            chip=chip,
            require_acc_columns=checks is not None and "acc" in check_set,
        )
        if mismatch_reason:
            return None, None, None, mismatch_reason

        report = FileCheckReport(file_path=csv_file, chip=chip)

        if "range" in check_set:
            report.results.append(checker.check_data_range(df, threshold_ratio=range_ratio))
        if "frame" in check_set:
            report.results.append(checker.check_frame_completeness(df, threshold_ratio=frame_ratio))
        if "center" in check_set:
            report.results.append(checker.check_data_centering(df, threshold_ratio=center_ratio))
        if timestamp_column:
            report.results.append(
                checker.check_timestamp_interval(
                    df,
                    timestamp_column,
                    ratio_tolerance=timestamp_ratio,
                    ms_tolerance=timestamp_ms,
                    threshold_ratio=timestamp_fail_ratio,
                )
            )

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
    ipd_details: Dict[Path, "pd.DataFrame"] = {}
    collector = ResultCollector()

    with Progress(console=console) as progress:
        task = progress.add_task("检查中", total=len(files))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_process_file, f): f for f in files}
            for future in as_completed(futures):
                csv_file = futures[future]
                try:
                    file_report, acc_report, ipd_detail, skip_reason = future.result()
                except Exception as e:
                    collector.add_exception(csv_file, e)
                    progress.advance(task)
                    continue
                if file_report:
                    reports.append(file_report)
                    collector.add_ok(csv_file)
                    if acc_report:
                        acc_reports[csv_file] = acc_report
                    if ipd_detail is not None and not ipd_detail.empty:
                        ipd_details[csv_file] = ipd_detail
                elif skip_reason:
                    collector.add_skip(csv_file, reason=skip_reason)
                    if verbose:
                        progress.console.print(
                            f"[yellow]跳过（{skip_reason}）: {csv_file.name}[/yellow]"
                        )
                progress.advance(task)

    print_summary("检查处理结果", collector, console=console, verbose=verbose)

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
    if timestamp_column:
        ratios["timestamp"] = timestamp_fail_ratio
    _print_criteria(
        check_set, tolerance, static_min, ratios, timestamp_column, timestamp_ratio, timestamp_ms
    )

    csv_out = Path(output_path) if output_path else _default_output(target)
    base_dir = target.parent if target.is_file() else target
    _save_report_csv(reports, acc_reports, csv_out, base_dir=base_dir)

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


def _check_rule_mismatch(
    checker,
    df,
    check_set: set,
    timestamp_column: Optional[str] = None,
    chip: str = "",
    require_acc_columns: bool = False,
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


def _print_criteria(
    check_set: set,
    tolerance: int,
    static_min: int,
    ratios: dict,
    timestamp_column: Optional[str] = None,
    timestamp_ratio: float = 20.0,
    timestamp_ms: Optional[float] = None,
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
    if timestamp_column:
        ms_text = f", 固定容差±{timestamp_ms:g}ms" if timestamp_ms is not None else ""
        console.print(
            f"  [dim]时间戳间隔: 列 {timestamp_column}, "
            f"相邻间隔偏差≤±{timestamp_ratio:g}%{ms_text} "
            f"(异常比例≤{ratios.get('timestamp', 1.0):g}% 为Warning)[/dim]"
        )


def _save_report_csv(
    reports: list,
    acc_reports: dict,
    output_path: Path,
    base_dir: Optional[Path] = None,
) -> None:
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

    header.append("文件相对路径")
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

            row.append(_relative_report_path(report.file_path, base_dir))
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
    """根据检查报告移动文件到正常/异常目录，并生成列表CSV。"""
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

    normal_records: List[List[str]] = []
    abnormal_records: List[List[str]] = []
    stats = {"normal": 0, "abnormal": 0, "skipped": 0}
    report_dir = report_path.parent

    for row in rows:
        status = row.get("总异常(结果)", "").strip().upper()
        rel_path_text = row.get("文件相对路径", "").strip()
        file_name = row.get("文件名", "").strip()
        if not rel_path_text:
            record = [file_name, rel_path_text, "", "跳过", "文件相对路径为空"]
            _append_sort_record(status, normal_records, abnormal_records, record)
            stats["skipped"] += 1
            continue

        rel_path = Path(rel_path_text)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            record = [file_name, rel_path_text, "", "跳过", "文件相对路径非法"]
            _append_sort_record(status, normal_records, abnormal_records, record)
            stats["skipped"] += 1
            continue

        category = "normal" if status == "PASS" else "abnormal"
        target_dir = output_dir / category
        src_path = report_dir / rel_path
        dst_path = target_dir / rel_path
        records = normal_records if category == "normal" else abnormal_records

        if not src_path.exists():
            records.append([file_name, rel_path_text, str(dst_path), "跳过", "源文件不存在"])
            stats["skipped"] += 1
            continue
        if dst_path.exists():
            records.append([file_name, rel_path_text, str(dst_path), "跳过", "目标文件已存在"])
            stats["skipped"] += 1
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        records.append([file_name, rel_path_text, str(dst_path), "已移动", ""])
        stats[category] += 1

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_sort_list(output_dir / "normal_files.csv", normal_records)
    _write_sort_list(output_dir / "abnormal_files.csv", abnormal_records)
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
        writer.writerow(["文件名", "文件相对路径", "目标路径", "状态", "原因"])
        writer.writerows(records)
