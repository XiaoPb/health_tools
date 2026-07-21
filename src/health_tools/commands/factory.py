"""产测计算命令（SNR/CTR/Noise）"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import click
from rich.console import Console

if TYPE_CHECKING:

    pass

console = Console()


def _parse_metric_cfg(value: Optional[str]) -> Optional[dict]:
    """解析 skip_head,skip_tail,min_duration 格式为配置字典"""
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


def _print_adc_params(chip_rule, adc_offset_override: Optional[float] = None) -> None:
    """输出 ADC 参数和计算公式"""
    ci = chip_rule.chip_info if chip_rule else {}
    adc_full_scale = float(ci.get("adc_full_scale", 8388608))
    adc_offset = (
        adc_offset_override if adc_offset_override is not None else float(ci.get("adc_offset", 0))
    )
    adc_vref = float(ci.get("adc_vref", 1.8))
    tia_ratio = float(ci.get("tia_ratio", 2.0))
    console.print(
        f"[green]adc_full_scale: {adc_full_scale:.0f}  "
        f"adc_offset: {adc_offset:.0f}  "
        f"adc_vref: {adc_vref}  "
        f"tia_ratio: {tia_ratio}[/green]"
    )
    console.print("[green]SNR(dB) = 20 * log10((Mean - adc_offset) / Std_filtered)[/green]")
    console.print("[green]Noise(uV) = 6 * Std_filtered * adc_vref * 1e6 / adc_full_scale[/green]")
    console.print(
        "[green]rawdata_uv = (value - adc_offset) / adc_full_scale * adc_vref * 1e6[/green]"
    )
    console.print("[green]ipd_pA = rawdata_uv / (tia_ratio * RF) * 1000[/green]")
    console.print("[green]CTR(nA/mA) = ipd_pA / 1000 / iled[/green]")


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
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件")
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
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """计算SNR/CTR/Noise（产测）"""
    from health_tools.api import FactoryRequest, run_factory
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    # 加载芯片配置以显示 ADC 参数和计算公式
    if chip_name:
        from health_tools.rules.loader import RuleLoader

        chip_rule = RuleLoader.load_chip_rule(chip_name)
        _print_adc_params(chip_rule, adc_offset)

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_factory(
                FactoryRequest(
                    Path(input_path),
                    chip_name=chip_name,
                    rule_file=rule_file,
                    gain=gain,
                    current=current,
                    sample_rate=sample_rate,
                    snr_cfg=snr_cfg,
                    ctr_cfg=ctr_cfg,
                    noise_cfg=noise_cfg,
                    adc_offset=adc_offset,
                    channels=channels,
                    output_path=Path(output_path) if output_path else None,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("产测结果", result, console, verbose)
    if result.artifacts:
        console.print(f"[green]OK[/green] 结果已保存: {result.artifacts[-1]}")
    return
