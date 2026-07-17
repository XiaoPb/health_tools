import re
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from health_tools.utils.reporting import FileResult, ResultCollector

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出图片目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（指定CSV格式）")
@click.option("-r", "--rule", "rule_file", help="转换规则文件（指定CSV格式）")
@click.option(
    "--type", "plot_type", default="both", help="图表类型: time|freq|stft|psd|ac|fft|both"
)
@click.option("--channels", help="指定绘制的通道；AC模式用分号分组（如: CH0,CH2;CH1）")
@click.option("--sample-rate", type=int, default=25, help="采样率（Hz，默认: 25）")
@click.option("--window", type=int, default=25, help="STFT窗口大小（秒，默认: 25）")
@click.option("--overlap", type=float, default=0.96, help="窗口重叠率（0-1，默认: 0.96）")
@click.option("--format", "fmt", default="png", help="图片格式: png|svg|pdf（默认: png）")
@click.option("--dpi", type=int, default=150, help="图片DPI（默认: 150）")
@click.option("--bandpass", default="0.5-4.0", help="带通滤波范围（Hz，默认: 0.5-4.0）")
@click.option("--remove-baseline/--no-remove-baseline", default=True, help="去除基线（默认: 是）")
@click.option("--baseline-method", default="mean", help="基线去除方法: mean|median（默认: mean）")
@click.option("--freq-bpm", is_flag=True, default=True, help="Y轴显示BPM（默认: 是）")
@click.option("--freq-range", default="30-240", help="频率范围（BPM，默认: 30-240）")
@click.option("--ref-column", help="参考曲线列名")
@click.option(
    "--psd-acc",
    type=click.Choice(["axis", "rms"]),
    default="axis",
    help="PSD模式下ACC绘图: axis三轴|rms合成（默认: axis）",
)
@click.option("--no-show", is_flag=True, help="不显示图片，仅保存")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件（目录模式）")
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
    psd_acc: str,
    no_show: bool,
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """绘制PPG数据的时域、频域、AC/PI、FFT和时频图"""
    from health_tools.api import PlotRequest, run_plot
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_plot(
                PlotRequest(
                    Path(input_path),
                    Path(output_path),
                    chip_name=chip_name,
                    rule_file=rule_file,
                    plot_type=plot_type,
                    channels=channels,
                    sample_rate=sample_rate,
                    window=window,
                    overlap=overlap,
                    fmt=fmt,
                    dpi=dpi,
                    bandpass=bandpass,
                    remove_baseline=remove_baseline,
                    baseline_method=baseline_method,
                    freq_bpm=freq_bpm,
                    freq_range=freq_range,
                    ref_column=ref_column,
                    psd_acc=psd_acc,
                    no_show=no_show,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("绘图结果", result, console, verbose)
    return


def _plot_psd_dir(input_dir: Path, output_dir: Path, acc_mode: str = "axis") -> None:
    """绘制离线结果目录中的PSD时频图"""
    if not input_dir.exists():
        console.print(f"[red]错误: 输入路径不存在: {input_dir}[/red]")
        raise SystemExit(1)
    if not input_dir.is_dir():
        console.print("[red]错误: PSD绘图输入必须是离线结果目录[/red]")
        raise SystemExit(1)

    from health_tools.core.psd_plotter import PsdPlotter

    plotter = PsdPlotter()
    saved = plotter.plot(input_dir, save_dir=output_dir, show_progress=True, acc_mode=acc_mode)
    if saved:
        console.print(f"[green]OK[/green] 生成 {len(saved)} 张PSD时频图: {output_dir}")
    else:
        console.print("[yellow]WARN[/yellow] 未找到PSD数据文件")


def _parse_ac_channel_groups(channels: Optional[str]) -> Optional[List[List[str]]]:
    if channels is None:
        return None
    groups = []
    for raw_group in channels.split(";"):
        group = [item.strip() for item in raw_group.split(",") if item.strip()]
        if not group:
            raise ValueError("AC 通道分组不能为空")
        if len(group) > 4:
            raise ValueError(f"AC 每组最多支持 4 个通道，超限分组: {','.join(group)}")
        groups.append(group)
    return groups


def _safe_channel_suffix(channels: List[str]) -> str:
    safe_names = []
    for channel in channels:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", channel).strip("._")
        safe_names.append(safe_name or "channel")
    return "-".join(safe_names)


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
    ac_channel_groups: Optional[List[List[str]]] = None,
) -> FileResult:
    try:
        from health_tools.utils.csv_handler import read_csv_df

        df = read_csv_df(input_file, chip_rule)
        output_files = []

        if plot_type in ("time", "both"):
            output_file = output_dir / f"{input_file.stem}_time.{plotter.fmt}"
            plotter.plot_time(df, output_file, channels)
            output_files.append(str(output_file))
            if verbose:
                console.print(f"[green]OK[/green] 时域图: {output_file}")

        if plot_type in ("freq", "both"):
            output_file = output_dir / f"{input_file.stem}_freq.{plotter.fmt}"
            plotter.plot_freq(df, output_file, channels)
            output_files.append(str(output_file))
            if verbose:
                console.print(f"[green]OK[/green] 频域图: {output_file}")

        if plot_type in ("stft", "both"):
            if chip_rule and not channels:
                out_files = plotter.plot_chip_stft(df, output_dir, input_file.stem)
                output_files.extend(str(f) for f in out_files)
                if verbose:
                    for f in out_files:
                        console.print(f"[green]OK[/green] 时频图: {f}")
            else:
                output_file = output_dir / f"{input_file.stem}_stft.{plotter.fmt}"
                plotter.plot_stft(df, output_file, channels, ref_column)
                output_files.append(str(output_file))
                if verbose:
                    console.print(f"[green]OK[/green] 时频图: {output_file}")

        if plot_type == "ac":
            from health_tools.core.ppg_analysis import (
                SignalAnalysisError,
                resolve_acc_columns,
                resolve_ppg_channels,
            )

            acc_mapping = chip_rule.acc_columns if chip_rule else None
            acc_columns = resolve_acc_columns(df, acc_mapping)
            if len(acc_columns) != 3:
                raise SignalAnalysisError("无法识别完整的 ACC X/Y/Z 三轴")

            groups = ac_channel_groups
            automatic = groups is None
            if automatic:
                chip_name = chip_rule.chip if chip_rule else ""
                detected = resolve_ppg_channels(df, chip_name)
                groups = [detected[:4]]
                if len(detected) > 4:
                    console.print(
                        "[yellow]WARN[/yellow] AC 自动模式最多绘制前 4 个通道；"
                        f"未绘制通道: {', '.join(detected[4:])}"
                    )

            for group in groups or []:
                suffix = "" if automatic else f"_{_safe_channel_suffix(group)}"
                output_file = output_dir / f"{input_file.stem}_ac{suffix}.{plotter.fmt}"
                plotter.plot_ac(df, output_file, group, acc_columns)
                output_files.append(str(output_file))
                if verbose:
                    console.print(f"[green]OK[/green] AC/PI图: {output_file}")

        if plot_type == "fft":
            from health_tools.core.ppg_analysis import resolve_ppg_channels

            fft_channels = channels
            if fft_channels is None:
                chip_name = chip_rule.chip if chip_rule else ""
                fft_channels = resolve_ppg_channels(df, chip_name)
            for channel in fft_channels:
                suffix = _safe_channel_suffix([channel])
                output_file = output_dir / f"{input_file.stem}_fft_{suffix}.{plotter.fmt}"
                plotter.plot_fft(df, output_file, channel)
                output_files.append(str(output_file))
                if verbose:
                    console.print(f"[green]OK[/green] FFT图: {output_file}")

        return FileResult(
            status="OK",
            input=str(input_file),
            output=";".join(output_files),
            rows=len(df),
        )
    except Exception as e:
        collector = ResultCollector()
        return collector.add_exception(input_file, e, output=output_dir)
