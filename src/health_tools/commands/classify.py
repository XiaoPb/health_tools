from pathlib import Path
from typing import Dict, Optional, Tuple

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option(
    "-r",
    "--rule",
    "rule_file",
    default="spo2_posture.yaml",
    help="分类规则文件（默认: spo2_posture.yaml）",
)
@click.option("--extend", "extend_files", multiple=True, help="扩展patterns文件（可多次使用）")
@click.option("--accuracy", "enable_accuracy", is_flag=True, help="启用准确度计算")
@click.option("--ref-column", help="参考列名/列索引（覆盖规则配置）")
@click.option("--pred-column", help="预测列名/列索引（覆盖规则配置）")
@click.option("--copy", "mode", flag_value="copy", default=True, help="复制文件到分类目录")
@click.option("--move", "mode", flag_value="move", help="移动文件到分类目录")
@click.option("--symlink", "mode", flag_value="symlink", help="创建符号链接")
@click.option("--report", is_flag=True, help="生成分类报告")
@click.option("--unknown", "unknown_dir", help="未匹配文件的存放目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（决定CSV格式）")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def classify_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    rule_file: str,
    extend_files: Tuple[str, ...],
    enable_accuracy: bool,
    ref_column: Optional[str],
    pred_column: Optional[str],
    mode: str,
    report: bool,
    unknown_dir: Optional[str],
    chip_name: Optional[str],
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """根据规则对数据进行分类保存"""
    from health_tools.api import ClassifyRequest, run_classify
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_classify(
                ClassifyRequest(
                    Path(input_path),
                    Path(output_path),
                    rule_file=rule_file,
                    extend_files=extend_files,
                    enable_accuracy=enable_accuracy,
                    ref_column=ref_column,
                    pred_column=pred_column,
                    mode=mode,
                    report=report,
                    unknown_dir=unknown_dir,
                    chip_name=chip_name,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("分类结果", result, console, verbose)
    return


def _print_report(stats: Dict[str, int]) -> None:
    table = Table(title="分类报告")
    table.add_column("分类", style="cyan")
    table.add_column("数量", justify="right", style="green")

    total = 0
    for category, count in sorted(stats.items()):
        table.add_row(category, str(count))
        total += count

    table.add_row("[bold]总计[/bold]", f"[bold]{total}[/bold]")
    console.print(table)
