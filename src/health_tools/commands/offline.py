"""offline 命令：离线跑库"""

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("offline")
@click.option("-i", "--input", "input_path", type=click.Path(), help="输入数据目录")
@click.option("-o", "--output", "output_path", type=click.Path(), help="输出结果目录")
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)")
@click.option("--version", "ver", help="算法版本（覆盖默认版本）")
@click.option("--hba-fs", type=int, help="采样率 (默认25)")
@click.option("--scene-en", type=int, help="场景适配 0=关 1=开")
@click.option("--ch-num", type=int, help="有效PPG通道数 (默认2)")
@click.option("--ref-col", type=int, help="源CSV中金标列索引(1-based，覆盖芯片配置)")
@click.option("--no-accuracy", is_flag=True, help="跳过准确度统计")
@click.option("--no-plot", is_flag=True, help="跳过PSD时频图绘制")
@click.option("--no-run", is_flag=True, help="跳过跑库，直接整理/统计/绘图")
@click.option("--list", "do_list", is_flag=True, help="列出可用芯片和版本")
@click.option("--timeout", type=int, default=300, help="超时时间（秒，默认300）")
@click.option("-v", "--verbose", is_flag=True, help="详细输出")
def offline_cmd(
    input_path: Optional[str],
    output_path: Optional[str],
    chip_name: Optional[str],
    ver: Optional[str],
    hba_fs: Optional[int],
    scene_en: Optional[int],
    ch_num: Optional[int],
    ref_col: Optional[int],
    no_accuracy: bool,
    no_plot: bool,
    no_run: bool,
    do_list: bool,
    timeout: int,
    verbose: bool,
) -> None:
    """离线跑库（调用TEE_Algorithm.exe）"""
    from health_tools.core.offline import OfflineRunner, find_exe, reorganize_output

    if do_list:
        _show_versions(chip_name)
        return

    if not input_path:
        console.print("[red]错误: 需要指定 --input 参数[/red]")
        raise SystemExit(1)

    input_dir = Path(input_path)
    if not input_dir.exists():
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)

    if not output_path:
        output_path = str(input_dir.parent / f"{input_dir.name}_offline_result")
    output_dir = Path(output_path)
    psd_acc_mode = "axis"

    if not no_run:
        if not chip_name:
            console.print("[red]错误: 需要指定 --chip 参数[/red]")
            raise SystemExit(1)

        exe_path = find_exe(chip_name, ver)
        if not exe_path:
            console.print(f"[red]错误: 未找到 {chip_name} 的离线工具[/red]")
            console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
            raise SystemExit(1)
        psd_acc_mode = _default_psd_acc_mode(exe_path)

        column_indices = None
        if ref_col is not None:
            column_indices = {"polar": ref_col}

        runner = OfflineRunner(
            chip=chip_name,
            version=ver,
            hba_fs=hba_fs,
            scene_en=scene_en,
            ch_num=ch_num,
            column_indices=column_indices,
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

        success = runner.run(input_dir, output_dir, timeout=timeout)
        if success:
            console.print(f"[green]OK[/green] 离线跑库完成: {output_dir}")
        else:
            console.print("[red]FAIL[/red] 离线跑库失败")
            raise SystemExit(1)
    elif chip_name:
        exe_path = find_exe(chip_name, ver)
        psd_acc_mode = _default_psd_acc_mode(exe_path)

    console.print("\n[bold]数据整理[/bold]")
    reorg_dir = reorganize_output(input_dir, output_dir, show_progress=True)
    console.print(f"[green]OK[/green] 已整理到: {reorg_dir}")

    if not no_plot:
        psd_save_dir = output_dir / "psd_bmpfile"
        _run_psd_plot(reorg_dir, psd_save_dir, acc_mode=psd_acc_mode)

    if not no_accuracy:
        _run_accuracy(reorg_dir)


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
    saved = plotter.plot(result_dir, save_dir=save_dir, show_progress=True, acc_mode=acc_mode)
    if saved:
        console.print(f"[green]OK[/green] 生成 {len(saved)} 张时频图: {save_dir}")
    else:
        console.print("[yellow]WARN[/yellow] 未找到PSD数据文件")


def _run_accuracy(output_dir: Path) -> None:
    """执行准确度统计"""
    from health_tools.core.offline import calculate_offline_accuracy

    console.print("\n[bold]准确度统计[/bold]")

    report_df = calculate_offline_accuracy(output_dir, show_progress=True)
    if report_df is None or report_df.empty:
        console.print("[yellow]WARN[/yellow] 未找到有效的 .vshb 结果文件")
        return

    report_path = output_dir / "accuracy_report.csv"
    report_df.to_csv(report_path, index=False, encoding="utf-8-sig")
    console.print(f"[green]OK[/green] 报告已保存: {report_path}")

    table = Table(title="在线/离线准确度")
    for col in report_df.columns:
        table.add_column(col)
    for _, row in report_df.iterrows():
        table.add_row(*[str(v) for v in row.values])
    console.print(table)


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
