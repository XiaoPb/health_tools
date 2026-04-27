from pathlib import Path
from typing import List, Optional

import click
import pandas as pd
from rich.console import Console

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出图片目录")
@click.option("--type", "plot_type", default="both", help="图表类型: time|freq|both")
@click.option("--channels", help="指定绘制的通道（如: red,ir,green）")
@click.option("--sample-rate", type=int, help="采样率（Hz）")
@click.option("--window", type=int, default=10, help="时间窗口大小（秒）")
@click.option("--overlap", type=float, default=0.5, help="窗口重叠率（0-1）")
@click.option("--format", "fmt", default="png", help="图片格式: png|svg|pdf")
@click.option("--dpi", type=int, default=150, help="图片DPI")
@click.option("--no-show", is_flag=True, help="不显示图片，仅保存")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def plot_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    plot_type: str,
    channels: Optional[str],
    sample_rate: Optional[int],
    window: int,
    overlap: float,
    fmt: str,
    dpi: int,
    no_show: bool,
    verbose: bool,
) -> None:
    """绘制PPG数据的时域/频域图"""
    from health_tools.core.plotter import DataPlotter

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)

    channel_list = channels.split(",") if channels else None

    plotter = DataPlotter(
        sample_rate=sample_rate,
        window=window,
        overlap=overlap,
        fmt=fmt,
        dpi=dpi,
    )

    if input_path_obj.is_file():
        _plot_file(
            input_path_obj,
            output_path_obj,
            plotter,
            plot_type,
            channel_list,
            no_show,
            verbose,
        )
    elif input_path_obj.is_dir():
        files = list(input_path_obj.glob("*.csv"))
        for file in files:
            _plot_file(
                file,
                output_path_obj,
                plotter,
                plot_type,
                channel_list,
                no_show,
                verbose,
            )
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)


def _plot_file(
    input_file: Path,
    output_dir: Path,
    plotter,
    plot_type: str,
    channels: Optional[List[str]],
    no_show: bool,
    verbose: bool,
) -> None:
    try:
        df = pd.read_csv(input_file)
        output_file = output_dir / f"{input_file.stem}_{plot_type}.{plotter.fmt}"

        if plot_type in ("time", "both"):
            plotter.plot_time(df, output_file, channels)
            if verbose:
                console.print(f"[green]✓[/green] 时域图: {output_file}")

        if plot_type in ("freq", "both"):
            freq_file = output_dir / f"{input_file.stem}_freq.{plotter.fmt}"
            plotter.plot_freq(df, freq_file, channels)
            if verbose:
                console.print(f"[green]✓[/green] 频域图: {freq_file}")

    except Exception as e:
        console.print(f"[red]✗[/red] {input_file.name}: {e}")
