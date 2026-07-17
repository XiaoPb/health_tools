"""offline 命令：离线跑库"""

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from health_tools.core.offline import OfflineRunner

console = Console()
DEFAULT_TIMEOUT = 300
TIMEOUT_FILE_THRESHOLD = 50
TIMEOUT_SECONDS_PER_EXTRA_FILE = 20


@click.command("offline")
@click.option("-i", "--input", "input_path", type=click.Path(), help="输入数据目录")
@click.option("-o", "--output", "output_path", type=click.Path(), help="输出结果目录")
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)")
@click.option("--version", "ver", help="算法版本（覆盖默认版本）")
@click.option("--versions", help="多个算法版本，逗号分隔")
@click.option("--all-versions", is_flag=True, help="运行当前芯片已配置的全部版本")
@click.option("--hba-fs", type=int, help="采样率 (默认25)")
@click.option("--scene-en", type=int, help="场景适配 0=关 1=开")
@click.option("--ch-num", type=int, help="有效PPG通道数 (默认2)")
@click.option("--ref-col", type=int, help="源CSV中金标列索引(1-based，覆盖芯片配置)")
@click.option(
    "--ppg-offset",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="PPG自动识别通道的固定偏移",
)
@click.option(
    "--ppg-map",
    "ppg_maps",
    multiple=True,
    help="覆盖已声明PPG通道，格式 ppg_chN=列名或0-based索引",
)
@click.option("--no-accuracy", is_flag=True, help="跳过准确度统计")
@click.option("--no-plot", is_flag=True, help="跳过PSD时频图绘制")
@click.option("--no-run", is_flag=True, help="跳过跑库，直接整理/统计/绘图")
@click.option("--list", "do_list", is_flag=True, help="列出可用芯片和版本")
@click.option("--timeout", type=int, default=DEFAULT_TIMEOUT, help="超时时间（秒，默认300）")
@click.option(
    "--settle-timeout", type=int, default=10, help="异常返回后等待输出稳定的时间（秒，默认10）"
)
@click.option("-v", "--verbose", is_flag=True, help="详细输出")
def offline_cmd(
    input_path: Optional[str],
    output_path: Optional[str],
    chip_name: Optional[str],
    ver: Optional[str],
    versions: Optional[str],
    all_versions: bool,
    hba_fs: Optional[int],
    scene_en: Optional[int],
    ch_num: Optional[int],
    ref_col: Optional[int],
    ppg_offset: int,
    ppg_maps: Tuple[str, ...],
    no_accuracy: bool,
    no_plot: bool,
    no_run: bool,
    do_list: bool,
    timeout: int,
    settle_timeout: int,
    verbose: bool,
) -> None:
    """离线跑库（调用TEE_Algorithm.exe）"""
    from health_tools.api import OfflineRequest, run_offline
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_offline(
                OfflineRequest(
                    input_path=Path(input_path) if input_path else None,
                    output_path=Path(output_path) if output_path else None,
                    chip_name=chip_name,
                    ver=ver,
                    versions=versions,
                    all_versions=all_versions,
                    hba_fs=hba_fs,
                    scene_en=scene_en,
                    ch_num=ch_num,
                    ref_col=ref_col,
                    ppg_offset=ppg_offset,
                    ppg_maps=ppg_maps,
                    no_accuracy=no_accuracy,
                    no_plot=no_plot,
                    no_run=no_run,
                    do_list=do_list,
                    timeout=timeout,
                    settle_timeout=settle_timeout,
                ),
                context=context,
            )
        )
    if do_list:
        for version in result.versions:
            console.print(version)
    else:
        print_batch("离线跑库", result.batch, console, verbose)
        for item in result.batch.items:
            for line in item.detail.splitlines():
                if line.startswith("PPG列映射"):
                    console.print(line)
    return


def _version_output_dir(output_dir: Path, version: Optional[str], exe_path: Optional[Path]) -> Path:
    """根据已解析版本返回离线结果目录。"""
    version_name = str(version) if version else (exe_path.parent.name if exe_path else None)
    return output_dir / version_name if version_name else output_dir


def _discover_no_run_versions(output_dir: Path) -> List[Optional[str]]:
    """--no-run 指向版本父目录时，自动发现已有版本目录。"""
    if not output_dir.exists() or (output_dir / "数据整理").exists():
        return []
    versions: List[Optional[str]] = [
        path.name
        for path in sorted(output_dir.iterdir())
        if path.is_dir() and (path / "数据整理").exists()
    ]
    return versions


def _resolve_timeout(input_dir: Path, timeout: int) -> int:
    """按输入CSV数量计算默认超时时间。"""
    ctx = click.get_current_context(silent=True)
    source = ctx.get_parameter_source("timeout") if ctx else None
    if source == click.core.ParameterSource.COMMANDLINE:
        return timeout

    from health_tools.core.offline import count_supported_csv_files

    file_count = count_supported_csv_files(input_dir)
    extra_count = max(0, file_count - TIMEOUT_FILE_THRESHOLD)
    return DEFAULT_TIMEOUT + extra_count * TIMEOUT_SECONDS_PER_EXTRA_FILE


def _resolve_versions(
    chip_name: Optional[str],
    ver: Optional[str],
    versions: Optional[str],
    all_versions: bool,
) -> List[Optional[str]]:
    """解析 offline 目标版本列表。"""
    if all_versions and (ver or versions):
        console.print("[red]错误: --all-versions 不能与 --version/--versions 同时使用[/red]")
        raise SystemExit(1)
    if ver and versions:
        console.print("[red]错误: --version 不能与 --versions 同时使用[/red]")
        raise SystemExit(1)
    if all_versions:
        if not chip_name:
            console.print("[red]错误: --all-versions 需要指定 --chip[/red]")
            raise SystemExit(1)
        resolved = _iter_config_versions(chip_name)
        if not resolved:
            console.print(f"[red]错误: 未找到 {chip_name} 的已配置版本[/red]")
            raise SystemExit(1)
        return resolved
    if versions:
        if not chip_name:
            console.print("[red]错误: --versions 需要指定 --chip[/red]")
            raise SystemExit(1)
        selected_versions: List[Optional[str]] = []
        seen = set()
        for item in versions.split(","):
            version = item.strip()
            if version and version not in seen:
                selected_versions.append(version)
                seen.add(version)
        if not selected_versions:
            console.print("[red]错误: --versions 未提供有效版本[/red]")
            raise SystemExit(1)
        return selected_versions
    return [ver]


def _iter_config_versions(chip_name: str) -> List[Optional[str]]:
    """展开当前芯片配置中的全部版本。"""
    from health_tools.core.offline import get_offline_config

    cfg = get_offline_config()
    chip_cfg = cfg.versions.get(chip_name, {})
    versions_data = chip_cfg.get("versions", {}) if isinstance(chip_cfg, dict) else {}
    if isinstance(versions_data, dict):
        return [version for ver_list in versions_data.values() for version in ver_list]
    if isinstance(versions_data, list):
        return versions_data
    return []


def _validate_version_exes(
    chip_name: str, versions: List[Optional[str]]
) -> Dict[Optional[str], Optional[Path]]:
    """校验目标版本是否存在，返回版本对应的exe路径。"""
    from health_tools.core.offline import find_exe

    result: Dict[Optional[str], Optional[Path]] = {}
    for version in versions:
        exe_path = find_exe(chip_name, version)
        if not exe_path:
            version_label = version or "默认版本"
            console.print(f"[red]错误: 未找到 {chip_name} 的离线工具: {version_label}[/red]")
            console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
            raise SystemExit(1)
        result[version] = exe_path
    return result


def _validate_local_cmd_configs(
    version_exes: Dict[Optional[str], Optional[Path]],
) -> None:
    """在移动输入文件前校验所有目标版本的本地参数配置。"""
    from health_tools.core.offline import OfflineConfigError, load_local_cmd_config

    try:
        for exe_path in version_exes.values():
            if exe_path is not None:
                load_local_cmd_config(exe_path.parent)
    except OfflineConfigError as exc:
        console.print(f"[red]错误: 离线工具参数配置无效: {exc}[/red]")
        raise SystemExit(1) from exc


def _prepare_offline_runners(
    version_exes: Dict[Optional[str], Optional[Path]],
    chip_name: Optional[str],
    hba_fs: Optional[int],
    scene_en: Optional[int],
    ch_num: Optional[int],
    ref_col: Optional[int],
    ppg_offset: int,
    ppg_maps: Tuple[str, ...],
) -> Dict[Optional[str], "OfflineRunner"]:
    """在输入预检前解析各版本参数模板和PPG映射。"""
    from health_tools.core.offline import OfflineConfigError, OfflineRunner

    if not chip_name:
        return {}

    prepared: Dict[Optional[str], OfflineRunner] = {}
    try:
        for version, exe_path in version_exes.items():
            column_indices = {"polar": ref_col} if ref_col is not None else None
            runner = OfflineRunner(
                chip=chip_name,
                version=version,
                hba_fs=hba_fs,
                scene_en=scene_en,
                ch_num=ch_num,
                column_indices=column_indices,
                ppg_offset=ppg_offset,
                ppg_maps=ppg_maps,
            )
            mapping = runner.resolve_ppg_mapping()
            version_label = (
                runner.resolved_version
                or (exe_path.parent.name if exe_path is not None else None)
                or version
                or "默认版本"
            )
            if mapping:
                mapping_text = ", ".join(f"{key}={value}" for key, value in mapping.items())
                console.print(f"  PPG列映射 ({version_label}): {mapping_text}")
            for warning in runner.ppg_warnings:
                console.print(f"[yellow]WARN[/yellow] {version_label}: {warning}")
            prepared[version] = runner
    except OfflineConfigError as exc:
        console.print(f"[red]错误: 离线工具PPG映射无效: {exc}[/red]")
        raise SystemExit(1) from exc
    return prepared


def _filter_input_files(input_dir: Path, chip_name: Optional[str]) -> None:
    """跑库前严格过滤不符合芯片表头规则的CSV。"""
    from health_tools.core.offline_input_filter import (
        OfflineInputFilterError,
        filter_offline_inputs,
    )
    from health_tools.rules.loader import RuleLoader

    if not chip_name:
        return
    chip_rule = RuleLoader.load_chip_rule(chip_name)
    console.print("[bold]输入预检[/bold]")
    try:
        result = filter_offline_inputs(input_dir, chip_rule)
    except OfflineInputFilterError as exc:
        console.print(f"[red]错误: {exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"  扫描CSV: {result.scanned_count}")
    console.print(f"  符合规则: {result.accepted_count}")
    console.print(f"  已移动: {result.moved_count}")
    if result.moved_count:
        console.print(f"  备份目录: {result.backup_dir}")
        for item in result.moved_files:
            console.print(f"  [yellow]MOVE[/yellow] {item.source}: {item.reason}")
    if result.accepted_count == 0:
        console.print("[red]错误: 没有符合芯片规则的CSV文件，已停止跑库[/red]")
        raise SystemExit(1)
    console.print("")


def _run_single_offline_version(
    input_dir: Path,
    output_dir: Path,
    chip_name: Optional[str],
    version: Optional[str],
    exe_path: Optional[Path],
    hba_fs: Optional[int],
    scene_en: Optional[int],
    ch_num: Optional[int],
    ref_col: Optional[int],
    ppg_offset: int,
    ppg_maps: Tuple[str, ...],
    prepared_runner: Optional["OfflineRunner"],
    no_run: bool,
    no_plot: bool,
    no_accuracy: bool,
    timeout: int,
    settle_timeout: int,
    verbose: bool,
) -> Optional[pd.DataFrame]:
    """执行单个版本的跑库、整理、PSD和准确度统计。"""
    from health_tools.core.offline import OfflineRunner, find_exe

    psd_acc_mode = _default_psd_acc_mode(exe_path)
    if not no_run:
        if not chip_name:
            console.print("[red]错误: 需要指定 --chip 参数[/red]")
            raise SystemExit(1)
        if exe_path is None:
            exe_path = find_exe(chip_name, version)
        if not exe_path:
            console.print(f"[red]错误: 未找到 {chip_name} 的离线工具[/red]")
            console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
            raise SystemExit(1)
        psd_acc_mode = _default_psd_acc_mode(exe_path)

        runner = prepared_runner
        if runner is None:
            column_indices = {"polar": ref_col} if ref_col is not None else None
            runner = OfflineRunner(
                chip=chip_name,
                version=version,
                hba_fs=hba_fs,
                scene_en=scene_en,
                ch_num=ch_num,
                column_indices=column_indices,
                ppg_offset=ppg_offset,
                ppg_maps=ppg_maps,
            )

        console.print("[bold]离线跑库[/bold]")
        console.print(f"  芯片: {chip_name}")
        console.print(f"  版本: {exe_path.parent.name}")
        console.print(f"  输入: {input_dir}")
        console.print(f"  输出: {output_dir}")
        console.print(
            "  参数: "
            f"hba_fs={hba_fs if hba_fs is not None else '默认'}, "
            f"scene_en={scene_en if scene_en is not None else '默认'}, "
            f"ch_num={ch_num if ch_num is not None else '默认'}"
        )
        if ref_col is not None:
            console.print(f"  金标列: {ref_col}")
        console.print("")

        result = runner.run(input_dir, output_dir, timeout=timeout, settle_timeout=settle_timeout)
        if verbose:
            _print_run_diagnostics(result)
        if result.success:
            if result.warning:
                console.print(f"[yellow]WARN[/yellow] {result.warning}")
            console.print(f"[green]OK[/green] 离线跑库完成: {output_dir}")
        else:
            console.print("[red]FAIL[/red] 离线跑库失败")
            _print_run_failure(result)
            raise SystemExit(1)
    elif chip_name:
        if exe_path is None:
            exe_path = find_exe(chip_name, version)
        psd_acc_mode = _default_psd_acc_mode(exe_path)

    reorg_dir = _prepare_reorganized_output(input_dir, output_dir, no_run=no_run)

    if not no_plot:
        psd_save_dir = output_dir / "psd_bmpfile"
        _run_psd_plot(reorg_dir, psd_save_dir, acc_mode=psd_acc_mode)

    if no_accuracy:
        return None
    return _run_accuracy(reorg_dir)


def _prepare_reorganized_output(input_dir: Path, output_dir: Path, no_run: bool) -> Path:
    """准备数据整理目录；--no-run 时优先复用已有整理结果。"""
    reorg_dir = output_dir / "数据整理"
    if no_run and reorg_dir.exists():
        console.print("\n[bold]数据整理[/bold]")
        console.print(f"[green]OK[/green] 使用已有整理目录: {reorg_dir}")
        return reorg_dir

    from health_tools.core.offline import reorganize_output

    console.print("\n[bold]数据整理[/bold]")
    reorg_dir = reorganize_output(input_dir, output_dir, show_progress=True)
    console.print(f"[green]OK[/green] 已整理到: {reorg_dir}")
    return reorg_dir


def _format_mtime(timestamp: Optional[float]) -> str:
    """格式化文件更新时间。"""
    if timestamp is None:
        return "无"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _print_run_diagnostics(result) -> None:
    """打印离线工具执行诊断信息。"""
    console.print("  诊断:")
    console.print(f"    命令: {result.command}")
    console.print(f"    返回码: {result.returncode if result.returncode is not None else '无'}")
    console.print(f"    超时: {'是' if result.timed_out else '否'}")
    console.print(f"    耗时: {result.duration:.1f}s")
    console.print(f"    输入CSV: {result.input_count}")
    console.print(f"    结果VSHB: {result.result_count}")
    console.print(f"    输出文件: {result.output_file_count}")
    console.print(f"    最后输出时间: {_format_mtime(result.last_output_mtime)}")


def _print_run_failure(result) -> None:
    """打印离线工具失败原因和建议。"""
    if result.error:
        console.print(f"  原因: {result.error}")
    console.print(f"  返回码: {result.returncode if result.returncode is not None else '无'}")
    console.print(f"  超时: {'是' if result.timed_out else '否'}")
    console.print(f"  输入CSV: {result.input_count}")
    console.print(f"  结果VSHB: {result.result_count}")
    if result.missing_count:
        console.print(f"  缺少结果: {result.missing_count}")
    console.print(f"  最后输出时间: {_format_mtime(result.last_output_mtime)}")
    console.print("  建议: 可增大 --timeout，或检查算法工具日志和失败文件。")


def _default_psd_acc_mode(exe_path: Optional[Path]) -> str:
    """根据离线工具等级选择PSD ACC绘图模式。"""
    if exe_path is None:
        return "axis"

    from health_tools.core.offline import get_category_label

    category = get_category_label(exe_path.parent.parent.name.lower())
    if category in {"medium", "basic"}:
        return "rms"
    return "axis"


def _run_psd_plot(result_dir: Path, save_dir: Path, acc_mode: str = "axis") -> None:
    """生成PSD时频图"""
    console.print("\n[bold]PSD时频图[/bold]")
    from health_tools.core.psd_plotter import PsdPlotter

    plotter = PsdPlotter()
    saved = plotter.plot(
        result_dir,
        save_dir=save_dir,
        show_progress=True,
        acc_mode=acc_mode,
        save_to_source=True,
    )
    if saved:
        console.print(
            f"[green]OK[/green] 生成 {len(saved)} 张时频图: {save_dir}，并同步保存到VSHB目录"
        )
    else:
        console.print("[yellow]WARN[/yellow] 未找到PSD数据文件")


def _run_accuracy(output_dir: Path) -> Optional[pd.DataFrame]:
    """执行准确度统计"""
    from health_tools.core.offline import calculate_offline_accuracy

    console.print("\n[bold]准确度统计[/bold]")

    report_df = calculate_offline_accuracy(output_dir, show_progress=True)
    if report_df is None or report_df.empty:
        console.print("[yellow]WARN[/yellow] 未找到有效的 .vshb 结果文件")
        return None

    report_path = output_dir / "accuracy_report.csv"
    report_df.to_csv(report_path, index=False, encoding="utf-8-sig")
    console.print(f"[green]OK[/green] 报告已保存: {report_path}")

    for table in _build_accuracy_tables(report_df):
        console.print(table)
    return report_df


def _build_accuracy_tables(report_df: pd.DataFrame) -> List[Table]:
    """将polar准确度和 online vs offline 拆成两个表打印。"""
    base_cols = ["file", "category", "reference", "samples"]
    compare_cols = [col for col in report_df.columns if "(online_vs_offline)" in col]
    polar_cols = [
        col
        for col in report_df.columns
        if col in base_cols or "(offline)" in col or "(online)" in col or "(comp)" in col
    ]

    tables: List[Table] = []
    for title, cols, reference in [
        ("在线/离线准确度", polar_cols, "polar"),
        ("Online vs Offline 准确度", base_cols + compare_cols, "offline"),
    ]:
        visible_cols = [col for col in cols if col in report_df.columns]
        metric_cols = [col for col in visible_cols if col not in base_cols]
        if not metric_cols:
            continue
        table_df = report_df[
            (report_df["reference"] == reference)
            | ((report_df["reference"] == "") & report_df[metric_cols].notna().any(axis=1))
        ]
        if table_df.empty:
            continue

        table = Table(title=title)
        for col in visible_cols:
            table.add_column(col)
        for _, row in table_df.iterrows():
            table.add_row(*[str(row[col]) for col in visible_cols])
        tables.append(table)
    return tables


def _save_combined_accuracy(output_dir: Path, version_reports: List[tuple]) -> None:
    """保存多版本准确度汇总报告。"""
    frames = []
    for version, report_df in version_reports:
        if report_df is None or report_df.empty:
            continue
        frame = report_df.copy()
        frame.insert(0, "version", version)
        frames.append(frame)
    if not frames:
        console.print("[yellow]WARN[/yellow] 未生成多版本准确度汇总")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    combined = pd.concat(frames, ignore_index=True)
    report_path = output_dir / "accuracy_report_all_versions.csv"
    combined.to_csv(report_path, index=False, encoding="utf-8-sig")
    console.print(f"\n[green]OK[/green] 多版本准确度汇总已保存: {report_path}")


def _show_versions(chip: Optional[str]) -> None:
    """显示可用版本列表"""
    from health_tools.core.offline import get_category_label, get_offline_config, list_versions

    versions = list_versions(chip)
    if not versions:
        cfg = get_offline_config()
        console.print("[yellow]未发现已配置的版本[/yellow]")
        console.print(f"工具路径: {cfg.tools_path}")
        console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
        return

    table = Table(title="离线工具版本", show_header=True)
    table.add_column("芯片", style="bold")
    table.add_column("类别")
    table.add_column("版本")
    table.add_column("默认", style="green")

    for chip_name, info in versions.items():
        default_ver = info.get("default", "")
        categories = info.get("versions", {})
        if isinstance(categories, dict):
            for cat, ver_list in categories.items():
                cat_label = get_category_label(cat)
                for v in ver_list:
                    is_default = "*" if v == default_ver else ""
                    table.add_row(chip_name, cat_label, v, is_default)
        else:
            for v in categories:
                is_default = "*" if v == default_ver else ""
                table.add_row(chip_name, "", v, is_default)

    console.print(table)
