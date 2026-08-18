"""evaluate 命令：批量准确度评估"""

from pathlib import Path

import click
from rich.console import Console

from health_tools.commands.accuracy_options import accuracy_options

console = Console()


@click.command("evaluate")
@accuracy_options
@click.option(
    "-i", "--input", "input_path", required=True, type=click.Path(exists=True), help="输入目录"
)
@click.option("-o", "--output", "output_path", required=True, type=click.Path(), help="输出目录")
@click.option(
    "--type",
    "eval_type",
    type=click.Choice(["hr", "spo2"]),
    default="hr",
    help="评估类型 (默认: hr)",
)
@click.option("--ref-column", help="参考列名（覆盖规则配置）")
@click.option("--pred-column", help="预测列名（覆盖规则配置）")
@click.option("--ref-column-col", type=int, help="参考列索引 1-based（优先于列名）")
@click.option("--pred-column-col", type=int, help="预测列索引 1-based（优先于列名）")
@click.option("--chip", help="芯片型号")
@click.option("--rule", "rule_file", help="评估规则文件")
@click.option("--diff-threshold", type=float, help="差分异常阈值")
@click.option("--stale-minutes", type=float, help="静止异常时间(分钟)")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件")
@click.option("-v", "--verbose", is_flag=True, help="详细输出")
def evaluate_cmd(
    input_path,
    output_path,
    eval_type,
    ref_column,
    pred_column,
    ref_column_col,
    pred_column_col,
    chip,
    rule_file,
    diff_threshold,
    stale_minutes,
    filter_name,
    accuracy_thresholds,
    accuracy_inclusive,
    verbose,
):
    """批量准确度评估（心率/血氧）"""
    from health_tools.api import EvaluateRequest, run_evaluate
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_evaluate(
                EvaluateRequest(
                    Path(input_path),
                    Path(output_path),
                    eval_type=eval_type,
                    ref_column=ref_column,
                    pred_column=pred_column,
                    ref_column_col=ref_column_col,
                    pred_column_col=pred_column_col,
                    chip=chip,
                    rule_file=rule_file,
                    diff_threshold=diff_threshold,
                    stale_minutes=stale_minutes,
                    filter_name=filter_name,
                    accuracy_thresholds=accuracy_thresholds,
                    accuracy_inclusive=accuracy_inclusive,
                ),
                context=context,
            )
        )
    print_batch("评估结果", result, console, verbose)
    if result.artifacts:
        console.print("输出文件:")
        for path in result.artifacts:
            console.print(f"  {path}")
    return
