from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出图片目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（指定CSV格式）")
@click.option("-r", "--rule", "rule_file", help="转换规则文件（指定CSV格式）")
@click.option("--type", "plot_type", default="both", help="图表类型: time|freq|stft|both")
@click.option("--channels", help="指定绘制的通道（如: red,ir,green）")
@click.option("--sample-rate", type=int, default=25, help="采样率（Hz，默认: 25）")
@click.option("--window", type=int, default=10, help="时间窗口大小（秒，默认: 10）")
@click.option("--overlap", type=float, default=0.5, help="窗口重叠率（0-1，默认: 0.5）")
@click.option("--format", "fmt", default="png", help="图片格式: png|svg|pdf（默认: png）")
@click.option("--dpi", type=int, default=150, help="图片DPI（默认: 150）")
@click.option("--bandpass", default="0.5-4.0", help="带通滤波范围（Hz，默认: 0.5-4.0）")
@click.option("--remove-baseline/--no-remove-baseline", default=True, help="去除基线（默认: 是）")
@click.option("--baseline-method", default="mean", help="基线去除方法: mean|median（默认: mean）")
@click.option("--freq-bpm", is_flag=True, default=True, help="Y轴显示BPM（默认: 是）")
@click.option("--freq-range", default="30-240", help="频率范围（BPM，默认: 30-240）")
@click.option("--ref-column", help="参考曲线列名")
@click.option("--no-show", is_flag=True, help="不显示图片，仅保存")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def plot_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    chip_name: Optional[str],
    rule_file: Optional[str],
    plot_type: str,
    channels: Optional[str],
    sample_rate: int,
    window: int,
    overlap: float,
    fmt: str,
    dpi: int,
    bandpass: str,
    remove_baseline: bool,
    baseline_method: str,
    freq_bpm: bool,
    freq_range: str,
    ref_column: Optional[str],
    no_show: bool,
    verbose: bool,
) -> None:
    """绘制PPG数据的时域/频域/时频图"""
    from health_tools.core.plotter import DataPlotter
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import read_csv_df

    chip_rule = None
    if chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)
    elif rule_file:
        convert_rule = RuleLoader.load_convert_rule(rule_file)
        csv_config = convert_rule.csv
        from health_tools.models.rules import ChipRule as _ChipRule

        chip_rule = _ChipRule(chip="", csv=csv_config, columns=[])

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)

    channel_list = channels.split(",") if channels else None

    try:
        freq_min, freq_max = map(float, freq_range.split("-"))
    except (ValueError, AttributeError):
        freq_min, freq_max = 30.0, 240.0

    plotter = DataPlotter(
        sample_rate=sample_rate,
        window=window,
        overlap=overlap,
        fmt=fmt,
        dpi=dpi,
        bandpass=bandpass,
        remove_baseline=remove_baseline,
        baseline_method=baseline_method,
        freq_bpm=freq_bpm,
        freq_range=(freq_min, freq_max),
    )

    if input_path_obj.is_file():
        _plot_file(
            input_path_obj,
            output_path_obj,
            plotter,
            plot_type,
            channel_list,
            ref_column,
            no_show,
            verbose,
            chip_rule,
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
                ref_column,
                no_show,
                verbose,
                chip_rule,
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
    ref_column: Optional[str],
    no_show: bool,
    verbose: bool,
    chip_rule=None,
) -> None:
    try:
        from health_tools.utils.csv_handler import read_csv_df

        df = read_csv_df(input_file, chip_rule)

        if plot_type in ("time", "both"):
            output_file = output_dir / f"{input_file.stem}_time.{plotter.fmt}"
            plotter.plot_time(df, output_file, channels)
            if verbose:
                console.print(f"[green]OK[/green] 时域图: {output_file}")

        if plot_type in ("freq", "both"):
            output_file = output_dir / f"{input_file.stem}_freq.{plotter.fmt}"
            plotter.plot_freq(df, output_file, channels)
            if verbose:
                console.print(f"[green]OK[/green] 频域图: {output_file}")

        if plot_type in ("stft", "both"):
            output_file = output_dir / f"{input_file.stem}_stft.{plotter.fmt}"
            plotter.plot_stft(df, output_file, channels, ref_column)
            if verbose:
                console.print(f"[green]OK[/green] 时频图: {output_file}")

    except Exception as e:
        console.print(f"[red]FAIL[/red] {input_file.name}: {e}")
