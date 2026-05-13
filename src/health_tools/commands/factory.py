"""产测计算命令（SNR/CTR/Noise）"""

from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from health_tools.core.snr import SNRCalculator
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import read_csv_df

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件")
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

    input_file = Path(input_path)
    if not input_file.exists():
        console.print(f"[red]错误: 文件不存在: {input_path}[/red]")
        raise SystemExit(1)

    df = read_csv_df(input_file, chip_rule)

    if channels:
        channel_list = channels.split(",")
    elif chip_rule and chip_rule.snr_columns:
        channel_list = [c for c in chip_rule.snr_columns if c in df.columns]
    else:
        channel_list = None

    calculator = SNRCalculator(gain=gain, current=current, sample_rate=sample_rate)
    results = calculator.calculate(df, channel_list)

    if not results:
        console.print("[yellow]WARN[/yellow] 无有效数据通道")
        return

    result_df = calculator.to_dataframe(results)

    if output_path:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        result_df.to_csv(out_file, index=False)
        console.print(f"[green]OK[/green] 结果已保存: {out_file}")

    table = Table(title="SNR/CTR/Noise 计算结果")
    for col in result_df.columns:
        table.add_column(col, style="cyan" if col == "Channel" else "green")
    for _, row in result_df.iterrows():
        table.add_row(*[str(v) for v in row.values])

    console.print(table)

    if verbose:
        console.print(f"\n[dim]数据行数: {len(df)}, 计算通道数: {len(results)}[/dim]")
        if gain is not None:
            console.print(f"[dim]增益: {gain}[/dim]")
        if current is not None:
            console.print(f"[dim]灯电流: {current} mA[/dim]")
