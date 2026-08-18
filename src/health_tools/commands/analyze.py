"""数据分析与诊断命令。"""

from pathlib import Path
from typing import Optional, Tuple

import click
from rich.console import Console

from health_tools.commands.accuracy_options import accuracy_options

console = Console()


@click.command("analyze")
@accuracy_options
@click.option("-i", "--input", "input_path", required=True, type=click.Path(exists=True))
@click.option("-o", "--output", "output_path", required=True, type=click.Path())
@click.option("--type", "analysis_type", type=click.Choice(["hr", "spo2", "other"]), default="hr")
@click.option("--rule", "rule_file", help="analysis 规则文件；other 类型必填")
@click.option("--chip", "chip_name", help="芯片型号")
@click.option("--scene", type=click.Choice(["auto", "static", "dynamic"]), default="auto")
@click.option("--sample-rate", type=float, help="采样率 Hz")
@click.option("--ref-column", help="参考值列")
@click.option("--pred-column", help="算法结果列")
@click.option("--timestamp-column", help="时间戳列")
@click.option("--focus", multiple=True, help="强制深度分析的带目录 glob，可重复")
@click.option("--report", type=click.Choice(["markdown", "pptx", "all"]), default="all")
@click.option("--offline-version", help="离线算法版本；默认使用已配置默认版本")
@click.option("--no-offline", is_flag=True, help="禁止自动离线 PSD 升级")
@click.option("--workers", type=int, default=4, help="并行工作数（默认 4）")
@click.option("-v", "--verbose", is_flag=True, help="显示文件级结果")
def analyze_cmd(
    input_path: str,
    output_path: str,
    analysis_type: str,
    rule_file: Optional[str],
    chip_name: Optional[str],
    scene: str,
    sample_rate: Optional[float],
    ref_column: Optional[str],
    pred_column: Optional[str],
    timestamp_column: Optional[str],
    focus: Tuple[str, ...],
    report: str,
    offline_version: Optional[str],
    no_offline: bool,
    workers: int,
    accuracy_thresholds: Optional[Tuple[float, ...]],
    accuracy_inclusive: bool,
    verbose: bool,
) -> None:
    """自动分析原始数据或离线 PSD，并生成诊断报告。"""
    from health_tools.api import AnalyzeRequest, run_analyze
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_analyze(
                AnalyzeRequest(
                    input_path=Path(input_path),
                    output_path=Path(output_path),
                    analysis_type=analysis_type,
                    rule_file=rule_file,
                    chip_name=chip_name,
                    scene=scene,
                    sample_rate=sample_rate,
                    ref_column=ref_column,
                    pred_column=pred_column,
                    timestamp_column=timestamp_column,
                    focus=focus,
                    report=report,
                    offline_version=offline_version,
                    allow_offline=not no_offline,
                    workers=workers,
                    accuracy_thresholds=accuracy_thresholds,
                    accuracy_inclusive=accuracy_inclusive,
                ),
                context=context,
            )
        )
    print_batch("分析结果", result.batch, console, verbose)
    console.print("结论汇总:")
    for name, count in result.conclusion_counts.items():
        console.print(f"  {name}: {count}")
    for path in result.reports:
        console.print(f"报告: {path}")
