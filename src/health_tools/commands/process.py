from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from health_tools.utils.errors import REASON_PROCESS_FAILED, normalize_reason
from health_tools.utils.reporting import ResultCollector, print_summary

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
    from health_tools.core.processor import BatchProcessor
    from health_tools.rules.loader import RuleLoader

    chip_rule = None
    if chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)

    processor = BatchProcessor(chip_rule)

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)

    if not input_path_obj.is_dir():
        console.print(f"[red]错误: 输入路径必须是目录: {input_path}[/red]")
        raise SystemExit(1)

    results = processor.process_directory(
        input_path_obj,
        output_path_obj,
        pattern=pattern,
        recursive=True,
        max_workers=max_workers,
        frame_split=frame_split,
        frame_column=frame_column,
        filter_name=filter_name,
        verbose=verbose,
    )

    collector = ResultCollector()
    for result in results:
        if result.get("success"):
            collector.add_ok(
                result.get("input", input_path_obj),
                output=result.get("output", output_path_obj),
                rows=int(result.get("rows", 0) or 0),
            )
        else:
            collector.add_fail(
                result.get("input", input_path_obj),
                reason=normalize_reason(result.get("reason") or REASON_PROCESS_FAILED),
                output=result.get("output", output_path_obj),
                detail=str(result.get("error") or ""),
            )

    print_summary("处理结果", collector, console=console, verbose=verbose)
