from pathlib import Path
from typing import Optional

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（决定CSV格式）")
@click.option("--by-column", "by_column", default="FRAME_ID", help="按指定列分割（默认: FRAME_ID）")
@click.option("--column-value", "column_value", default=0, type=float, help="分割值（默认: 0）")
@click.option("--by-size", "by_size", type=int, help="按行数分割")
@click.option("--by-time", "by_time", type=float, help="按时间分割（秒）")
@click.option("--time-column", "time_column", help="时间列名")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件（目录模式）")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def split_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    chip_name: Optional[str],
    by_column: str,
    column_value: float,
    by_size: Optional[int],
    by_time: Optional[float],
    time_column: Optional[str],
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """数据分割命令"""
    from health_tools.api import SplitRequest, run_split
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_split(
                SplitRequest(
                    Path(input_path),
                    Path(output_path),
                    chip_name=chip_name,
                    by_column=by_column,
                    column_value=column_value,
                    by_size=by_size,
                    by_time=by_time,
                    time_column=time_column,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("分割结果", result, console, verbose)
    return
