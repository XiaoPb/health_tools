"""offline 命令：离线跑库"""

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from health_tools.core.offline import (
    OfflineRunner,
    find_exe,
    get_offline_config,
    list_versions,
)

console = Console()


@click.command("offline")
@click.option("-i", "--input", "input_path", type=click.Path(), help="输入数据目录")
@click.option("-o", "--output", "output_path", type=click.Path(), help="输出结果目录")
@click.option("-c", "--chip", "chip_name", help="芯片型号 (如 gh3036, gh3220)")
@click.option("--version", "ver", help="算法版本（覆盖默认版本）")
@click.option("--hba-fs", type=int, default=25, help="采样率 (默认25)")
@click.option("--scene-en", type=int, default=0, help="场景适配 0=关 1=开")
@click.option("--ch-num", type=int, default=2, help="有效PPG通道数 (默认2)")
@click.option("--list", "do_list", is_flag=True, help="列出可用芯片和版本")
@click.option("--timeout", type=int, default=300, help="超时时间（秒，默认300）")
@click.option("-v", "--verbose", is_flag=True, help="详细输出")
def offline_cmd(
    input_path: Optional[str],
    output_path: Optional[str],
    chip_name: Optional[str],
    ver: Optional[str],
    hba_fs: int,
    scene_en: int,
    ch_num: int,
    do_list: bool,
    timeout: int,
    verbose: bool,
) -> None:
    """离线跑库（调用TEE_Algorithm.exe）"""
    if do_list:
        _show_versions(chip_name)
        return

    if not chip_name:
        console.print("[red]错误: 需要指定 --chip 参数[/red]")
        raise SystemExit(1)
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

    exe_path = find_exe(chip_name, ver)
    if not exe_path:
        console.print(f"[red]错误: 未找到 {chip_name} 的离线工具[/red]")
        console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
        raise SystemExit(1)

    runner = OfflineRunner(
        chip=chip_name,
        version=ver,
        hba_fs=hba_fs,
        scene_en=scene_en,
        ch_num=ch_num,
    )

    console.print("[bold]离线跑库[/bold]")
    console.print(f"  芯片: {chip_name}")
    console.print(f"  版本: {exe_path.parent.name}")
    console.print(f"  输入: {input_dir}")
    console.print(f"  输出: {output_dir}")
    console.print(f"  参数: hba_fs={hba_fs}, scene_en={scene_en}, ch_num={ch_num}")
    console.print("")

    success = runner.run(input_dir, output_dir, timeout=timeout)
    if success:
        console.print(f"[green]OK[/green] 离线跑库完成: {output_dir}")
    else:
        console.print("[red]FAIL[/red] 离线跑库失败")
        raise SystemExit(1)


def _show_versions(chip: Optional[str]) -> None:
    """显示可用版本列表"""
    versions = list_versions(chip)
    if not versions:
        cfg = get_offline_config()
        console.print("[yellow]未发现已配置的版本[/yellow]")
        console.print(f"工具路径: {cfg.tools_path}")
        console.print("请先配置: ghealth_tool cfg --offline-path <路径>")
        return

    table = Table(title="离线工具版本", show_header=True)
    table.add_column("芯片", style="bold")
    table.add_column("版本")
    table.add_column("默认", style="green")

    for chip_name, info in versions.items():
        default_ver = info.get("default", "")
        for v in info.get("versions", []):
            is_default = "*" if v == default_ver else ""
            table.add_row(chip_name, v, is_default)

    console.print(table)
