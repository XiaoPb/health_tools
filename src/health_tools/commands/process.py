from pathlib import Path
from typing import Optional

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（决定CSV格式）")
@click.option("--split", "frame_split", is_flag=True, help="按FRAME_ID分割数据")
@click.option("--frame-column", "frame_column", default="FRAME_ID", help="帧ID列名")
@click.option("--workers", "max_workers", default=4, type=int, help="并行线程数")
@click.option("--pattern", default="*.csv", help="文件匹配模式")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def process_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    chip_name: Optional[str],
    frame_split: bool,
    frame_column: str,
    max_workers: int,
    pattern: str,
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """批量处理命令"""
    from health_tools.api import ProcessRequest, run_process
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_process(
                ProcessRequest(
                    Path(input_path),
                    Path(output_path),
                    chip_name=chip_name,
                    frame_split=frame_split,
                    frame_column=frame_column,
                    max_workers=max_workers,
                    pattern=pattern,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("处理结果", result, console, verbose)
    return
