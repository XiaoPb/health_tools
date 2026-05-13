"""产测计算命令（SNR/CTR/Noise）"""

from pathlib import Path
from typing import Optional

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from health_tools.core.snr import SNRCalculator
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import read_csv_df

console = Console()


def _get_channel_list(channels: Optional[str], chip_rule, df: pd.DataFrame):
    if channels:
        return channels.split(",")
    if chip_rule and chip_rule.snr_columns:
        return [c for c in chip_rule.snr_columns if c in df.columns]
    return None


def _process_file(
    file_path: Path, chip_rule, calculator: SNRCalculator, channel_list_override=None
) -> pd.DataFrame:
    df = read_csv_df(file_path, chip_rule)
    ch_list = channel_list_override or _get_channel_list(None, chip_rule, df)
    results = calculator.calculate(df, ch_list)
    if not results:
        return pd.DataFrame()
    return calculator.to_dataframe(results, file_name=file_path.name)


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（指定CSV格式）")
@click.option("-r", "--rule", "rule_file", help="转换规则文件（指定CSV格式）")
@click.option("--gain", type=float, help="增益参数")
@click.option("--current", type=float, help="灯电流（mA）")
@click.option("--sample-rate", type=float, default=100.0, help="采样率（Hz，默认: 100）")
@click.option("--channels", help="指定计算的通道（逗号分隔）")
@click.option("-o", "--output", "output_path", help="输出结果CSV文件")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def factory_cmd(
    ctx: click.Context,
    input_path: str,
    chip_name: Optional[str],
    rule_file: Optional[str],
    gain: Optional[float],
    current: Optional[float],
    sample_rate: float,
    channels: Optional[str],
    output_path: Optional[str],
    verbose: bool,
) -> None:
    """计算SNR/CTR/Noise（产测）"""
    chip_rule = None
    if chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)
    elif rule_file:
        convert_rule = RuleLoader.load_convert_rule(rule_file)
        from health_tools.models.rules import ChipRule as _ChipRule

        chip_rule = _ChipRule(chip="", csv=convert_rule.csv, columns=[])

    input_p = Path(input_path)
    if not input_p.exists():
        console.print(f"[red]错误: 路径不存在: {input_path}[/red]")
        raise SystemExit(1)

    calculator = SNRCalculator(gain=gain, current=current, sample_rate=sample_rate)
    channel_list = channels.split(",") if channels else None

    if input_p.is_dir():
        csv_files = sorted(input_p.glob("*.csv"))
        if not csv_files:
            console.print(f"[yellow]WARN[/yellow] 目录中无CSV文件: {input_path}")
            return

        all_dfs = []
        for f in csv_files:
            try:
                df = read_csv_df(f, chip_rule)
                ch_list = channel_list or _get_channel_list(None, chip_rule, df)
                results = calculator.calculate(df, ch_list)
                if results:
                    file_df = calculator.to_dataframe(results, file_name=f.name)
                    all_dfs.append(file_df)
                    if verbose:
                        console.print(f"  [dim]{f.name}: {len(results)} 通道[/dim]")
            except Exception as e:
                console.print(f"  [yellow]WARN[/yellow] {f.name}: {e}")

        if not all_dfs:
            console.print("[yellow]WARN[/yellow] 无有效数据通道")
            return

        result_df = pd.concat(all_dfs, ignore_index=True)
        console.print(f"[green]OK[/green] 处理 {len(all_dfs)} 个文件, 共 {len(result_df)} 条记录")
    else:
        df = read_csv_df(input_p, chip_rule)
        ch_list = channel_list or _get_channel_list(None, chip_rule, df)
        results = calculator.calculate(df, ch_list)

        if not results:
            console.print("[yellow]WARN[/yellow] 无有效数据通道")
            return

        result_df = calculator.to_dataframe(results, file_name=input_p.name)

    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        result_df.to_csv(out_file, index=False)
        console.print(f"[green]OK[/green] 结果已保存: {out_file}")

    table = Table(title="SNR/CTR/Noise 计算结果")
    for col in result_df.columns:
        table.add_column(col, style="cyan" if col in ("file_name", "ch_num") else "green")
    for _, row in result_df.iterrows():
        table.add_row(*[str(v) for v in row.values])

    console.print(table)

    if verbose:
        console.print(f"\n[dim]计算通道数: {len(result_df)}[/dim]")
        if gain is not None:
            console.print(f"[dim]增益: {gain}[/dim]")
        if current is not None:
            console.print(f"[dim]灯电流: {current} mA[/dim]")
