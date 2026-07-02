"""evaluate 命令：批量准确度评估"""

from pathlib import Path

import click
from rich.console import Console
from health_tools.utils.reporting import print_summary

console = Console()


@click.command("evaluate")
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
    verbose,
):
    """批量准确度评估（心率/血氧）"""
    from health_tools.core.evaluator import BatchEvaluator
    from health_tools.rules.loader import RuleLoader

    if not rule_file:
        rule_file = f"evaluate_{eval_type}.yaml"

    rule = RuleLoader.load_evaluate_rule(rule_file)

    if ref_column:
        rule.ref_column = ref_column
    if pred_column:
        rule.pred_column = pred_column
    if diff_threshold is not None:
        rule.anomaly["diff_threshold"] = diff_threshold
    if stale_minutes is not None:
        rule.anomaly["stale_minutes"] = stale_minutes

    chip_rule = None
    if chip:
        chip_rule = RuleLoader.load_chip_rule(chip)

    evaluator = BatchEvaluator(
        rule, chip_rule, ref_column_col=ref_column_col, pred_column_col=pred_column_col
    )

    input_dir = Path(input_path)
    output_dir = Path(output_path)

    console.print(f"评估类型: {eval_type.upper()}")
    if ref_column_col:
        console.print(f"参考列索引: {ref_column_col} (1-based)")
    elif rule.ref_column:
        console.print(f"参考列: {rule.ref_column}")
    if pred_column_col:
        console.print(f"预测列索引: {pred_column_col} (1-based)")
    elif rule.pred_column:
        console.print(f"预测列: {rule.pred_column}")
    console.print(f"异常检测: diff>{rule.diff_threshold}, stale>{rule.stale_minutes}min")
    console.print(f"输入: {input_dir}")
    console.print(f"输出: {output_dir}")
    console.print("")

    output_paths = evaluator.evaluate_directory(
        input_dir,
        output_dir,
        filter_name=filter_name,
        verbose=verbose,
        show_progress=True,
    )

    if hasattr(evaluator, "last_collector"):
        print_summary("评估结果", evaluator.last_collector, console=console, verbose=verbose)

    if output_paths:
        console.print("")
        console.print("输出文件:")
        for name, path in output_paths.items():
            console.print(f"  {name}: {path}")
    else:
        console.print("[yellow]未找到有效数据文件[/yellow]")
