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
@click.option(
    "--activity",
    type=click.Choice(
        ["auto", "rest", "walk", "run", "cycle", "strength", "interval", "recovery", "other"]
    ),
    default="auto",
    help="活动场景细分标签",
)
@click.option("--sample-rate", type=float, help="采样率 Hz")
@click.option("--ref-column", help="参考值列")
@click.option("--pred-column", help="算法结果列")
@click.option("--timestamp-column", help="时间戳列")
@click.option("--focus", multiple=True, help="强制深度分析的带目录 glob，可重复")
@click.option(
    "--classify-rule", type=click.Path(exists=True, path_type=Path), help="分类 YAML 规则"
)
@click.option("--classify", multiple=True, help="分类覆盖规则 name=regex，可重复")
@click.option("--report", type=click.Choice(["markdown", "pptx", "all"]), default="all")
@click.option("--offline-version", help="离线算法版本；默认使用已配置默认版本")
@click.option("--no-offline", is_flag=True, help="禁止自动离线 PSD 升级")
@click.option(
    "--check-report", type=click.Path(exists=True, path_type=Path), help="复用已有 check 报告"
)
@click.option(
    "--offline-result", type=click.Path(exists=True, path_type=Path), help="复用已有离线跑库目录"
)
@click.option(
    "--figure-dir",
    "figure_dirs",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help="复用已有 PNG 目录，可重复",
)
@click.option("--resume/--no-resume", default=True, help="复用输出目录中已完成阶段")
@click.option("--restart", is_flag=True, help="清理分析状态后重新开始")
@click.option("--fast-report", is_flag=True, help="使用现有 check CSV/PNG 快速生成 PPT")
@click.option("--workers", type=int, default=4, help="并行工作数（默认 4）")
@click.option("-v", "--verbose", is_flag=True, help="显示文件级结果")
def analyze_cmd(
    input_path: str,
    output_path: str,
    analysis_type: str,
    rule_file: Optional[str],
    chip_name: Optional[str],
    scene: str,
    activity: str,
    sample_rate: Optional[float],
    ref_column: Optional[str],
    pred_column: Optional[str],
    timestamp_column: Optional[str],
    focus: Tuple[str, ...],
    classify_rule: Optional[Path],
    classify: Tuple[str, ...],
    report: str,
    offline_version: Optional[str],
    no_offline: bool,
    check_report: Optional[Path],
    offline_result: Optional[Path],
    figure_dirs: Tuple[Path, ...],
    resume: bool,
    restart: bool,
    fast_report: bool,
    workers: int,
    accuracy_thresholds: Optional[Tuple[float, ...]],
    accuracy_inclusive: bool,
    verbose: bool,
) -> None:
    """自动分析原始数据或离线 PSD，并生成诊断报告。"""
    from health_tools.api import AnalyzeRequest, run_analyze
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    if fast_report:
        if check_report is None or not figure_dirs:
            raise click.UsageError("--fast-report 必须同时提供 --check-report 和 --figure-dir")
        from health_tools.core.analysis.reporting import write_fast_ppt

        ppt_path, manifest = write_fast_ppt(
            check_report, figure_dirs, Path(output_path) / "analysis_report.pptx"
        )
        console.print(f"报告: {ppt_path}")
        console.print(f"快速模式清单: {manifest}")
        return

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
                    activity=activity,
                    sample_rate=sample_rate,
                    ref_column=ref_column,
                    pred_column=pred_column,
                    timestamp_column=timestamp_column,
                    focus=focus,
                    classify_rule=str(classify_rule) if classify_rule else None,
                    classify=classify,
                    fast_report=fast_report,
                    report=report,
                    offline_version=offline_version,
                    allow_offline=not no_offline,
                    check_report_path=check_report,
                    offline_result_path=offline_result,
                    figure_paths=figure_dirs,
                    resume=resume,
                    restart=restart,
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
