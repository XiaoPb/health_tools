from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from health_tools.core.processor import BatchProcessor
from health_tools.rules.loader import RuleLoader

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（决定CSV格式）")
@click.option("--split", "frame_split", is_flag=True, help="按FRAME_ID分割数据")
@click.option("--frame-column", "frame_column", default="FRAME_ID", help="帧ID列名")
@click.option("--workers", "max_workers", default=4, type=int, help="并行线程数")
@click.option("--pattern", default="*.csv", help="文件匹配模式")
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
    verbose: bool,
) -> None:
    """批量处理命令"""
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
        verbose=verbose,
    )

    success_count = sum(1 for r in results if r.get("success"))
    error_count = len(results) - success_count

    console.print(f"[green]✓[/green] 处理完成: {success_count} 成功, {error_count} 失败")
