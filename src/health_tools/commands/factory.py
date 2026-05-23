"""产测计算命令（SNR/CTR/Noise）"""

from pathlib import Path
from typing import Optional

import click
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from health_tools.core.factory import ChipInfoExtractor, FactoryCalculator
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import read_csv_df

console = Console()


def _get_channel_list(channels: Optional[str], chip_rule, df: pd.DataFrame):
    if channels:
        return channels.split(",")
    if chip_rule and chip_rule.factory_columns:
        return [c for c in chip_rule.factory_columns if c in df.columns]
    return None


def _parse_metric_cfg(value: Optional[str]) -> Optional[dict]:
    """解析 'skip_head,skip_tail,min_duration' 格式为配置字典"""
    if not value:
        return None
    parts = [float(x.strip()) for x in value.split(",")]
    if len(parts) != 3:
        raise click.BadParameter("格式: skip_head,skip_tail,min_duration (如 10,10,90)")
    return {
        "skip_head_seconds": parts[0],
        "skip_tail_seconds": parts[1],
        "min_duration_seconds": parts[2],
    }


def _build_calculator(
    chip_rule,
    gain,
    current,
    sample_rate,
    snr_override,
    ctr_override,
    noise_override,
    adc_offset_override=None,
) -> FactoryCalculator:
    """从 chip_rule 构建 FactoryCalculator"""
    fc = chip_rule.factory_config if chip_rule else {}
    calc_sample_rate = sample_rate or fc.get("sample_rate", 100.0)

    adc_full_scale = 8388608.0
    adc_offset = 0.0
    adc_vref = 1.8
    tia_ratio = 2.0
    if chip_rule and chip_rule.chip_info:
        adc_full_scale = float(chip_rule.chip_info.get("adc_full_scale", 8388608))
        adc_offset = float(chip_rule.chip_info.get("adc_offset", 0))
        adc_vref = float(chip_rule.chip_info.get("adc_vref", 1.8))
        tia_ratio = float(chip_rule.chip_info.get("tia_ratio", 2.0))

    if adc_offset_override is not None:
        adc_offset = adc_offset_override

    return FactoryCalculator(
        gain=gain,
        current=current,
        sample_rate=calc_sample_rate,
        adc_full_scale=adc_full_scale,
        adc_offset=adc_offset,
        adc_vref=adc_vref,
        tia_ratio=tia_ratio,
        snr_config=snr_override or fc.get("snr"),
        ctr_config=ctr_override or fc.get("ctr"),
        noise_config=noise_override or fc.get("noise"),
    )


def _print_adc_info(calculator: FactoryCalculator):
    """输出 ADC 参数和计算公式"""
    console.print(
        f"[green]adc_full_scale: {calculator.adc_full_scale:.0f}  "
        f"adc_offset: {calculator.adc_offset:.0f}  "
        f"adc_vref: {calculator.adc_vref}  "
        f"tia_ratio: {calculator.tia_ratio}[/green]"
    )
    console.print("[green]SNR(dB) = 20 * log10((Mean - adc_offset) / Std_filtered)[/green]")
    console.print("[green]Noise(uV) = 6 * Std_filtered * adc_vref * 1e6 / adc_full_scale[/green]")
    console.print(
        "[green]rawdata_uv = (value - adc_offset) / adc_full_scale * adc_vref * 1e6[/green]"
    )
    console.print("[green]ipd_pA = rawdata_uv / (tia_ratio * RF) * 1000[/green]")
    console.print("[green]CTR(nA/mA) = ipd_pA / 1000 / iled[/green]")


def _print_chip_info(results, file_name: str):
    """输出文件的通道级 chip_info（gain、current）"""
    info_rows = [(m.channel, m.gain, m.current) for m in results if m.gain or m.current]
    if not info_rows:
        return
    tbl = Table(show_header=True, header_style="bold")
    tbl.add_column("CH")
    tbl.add_column("Gain(KΩ)")
    tbl.add_column("Current(mA)")
    for ch, g, c in info_rows:
        tbl.add_row(
            ch,
            f"{g:.1f}" if g is not None else "-",
            f"{c:.1f}" if c is not None else "-",
        )
    console.print(Panel(tbl, title=f"chip_info: {file_name}", border_style="dim"))


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（指定CSV格式）")
@click.option("-r", "--rule", "rule_file", help="转换规则文件（指定CSV格式）")
@click.option("--gain", type=float, help="增益参数")
@click.option("--current", type=float, help="灯电流（mA）")
@click.option("--sample-rate", type=float, default=None, help="采样率（Hz，默认使用芯片配置）")
@click.option("--snr-cfg", help="SNR配置: skip_head,skip_tail,min_duration (如 10,10,90)")
@click.option("--ctr-cfg", help="CTR配置: skip_head,skip_tail,min_duration (如 1,0,2)")
@click.option("--noise-cfg", help="Noise配置: skip_head,skip_tail,min_duration (如 2,0,4)")
@click.option("--adc-offset", type=float, help="ADC偏移量（覆盖芯片配置）")
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
    sample_rate: Optional[float],
    snr_cfg: Optional[str],
    ctr_cfg: Optional[str],
    noise_cfg: Optional[str],
    adc_offset: Optional[float],
    channels: Optional[str],
    output_path: Optional[str],
    verbose: bool,
) -> None:
    """计算SNR/CTR/Noise（产测）"""
    snr_override = _parse_metric_cfg(snr_cfg)
    ctr_override = _parse_metric_cfg(ctr_cfg)
    noise_override = _parse_metric_cfg(noise_cfg)

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

    calculator = _build_calculator(
        chip_rule,
        gain,
        current,
        sample_rate,
        snr_override,
        ctr_override,
        noise_override,
        adc_offset_override=adc_offset,
    )

    extractor = None
    if chip_rule and chip_rule.chip_info:
        extractor = ChipInfoExtractor(chip_rule.chip_info, chip_rule.gain_tia_map)

    channel_list = channels.split(",") if channels else None

    if input_p.is_dir():
        csv_files = sorted(input_p.rglob("*.csv"))
        if not csv_files:
            console.print(f"[yellow]WARN[/yellow] 目录中无CSV文件: {input_path}")
            return

        all_dfs = []
        for f in csv_files:
            try:
                df = read_csv_df(f, chip_rule)
            except Exception:
                continue
            ch_list = channel_list or _get_channel_list(None, chip_rule, df)
            results = calculator.calculate(df, ch_list, extractor=extractor)
            if results:
                rel_name = str(f.relative_to(input_p))
                _print_chip_info(results, rel_name)
                file_df = calculator.to_dataframe(results, file_name=rel_name)
                all_dfs.append(file_df)
                if verbose:
                    console.print(f"  [dim]{rel_name}: {len(results)} 通道[/dim]")

        if not all_dfs:
            console.print("[yellow]WARN[/yellow] 无有效数据通道")
            return

        result_df = pd.concat(all_dfs, ignore_index=True)
        console.print(f"[green]OK[/green] 处理 {len(all_dfs)} 个文件, 共 {len(result_df)} 条记录")
    else:
        try:
            df = read_csv_df(input_p, chip_rule)
        except Exception as e:
            console.print(f"[red]错误[/red] 读取失败: {input_p}: {e}")
            raise SystemExit(1)
        ch_list = channel_list or _get_channel_list(None, chip_rule, df)
        results = calculator.calculate(df, ch_list, extractor=extractor)

        if not results:
            console.print("[yellow]WARN[/yellow] 无有效数据通道")
            return

        _print_chip_info(results, input_p.name)
        result_df = calculator.to_dataframe(results, file_name=input_p.name)

    if output_path:
        out_p = Path(output_path)
        if out_p.is_dir() or (not out_p.suffix and not out_p.exists()):
            out_p.mkdir(parents=True, exist_ok=True)
            name = input_p.name if input_p.is_file() else input_p.resolve().name
            out_file = out_p / f"factory_{name}.csv"
        else:
            out_file = out_p
            out_file.parent.mkdir(parents=True, exist_ok=True)
    else:
        if input_p.is_dir():
            dir_name = input_p.resolve().name
            out_file = input_p / f"factory_{dir_name}.csv"
        else:
            out_file = input_p.parent / f"factory_{input_p.stem}.csv"

    result_df.to_csv(out_file, index=False)
    console.print(f"[green]OK[/green] 结果已保存: {out_file}")

    table = Table(title="SNR/CTR/Noise 计算结果")
    for col in result_df.columns:
        table.add_column(col, style="cyan" if col in ("file_name", "ch_num") else "green")
    for _, row in result_df.iterrows():
        table.add_row(*[str(v) for v in row.values])

    console.print(table)
    _print_adc_info(calculator)
