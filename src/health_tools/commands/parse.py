import re
from pathlib import Path
from typing import Optional

import click
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from health_tools.core.parser import LogParser
from health_tools.rules.loader import RuleLoader

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出文件或目录")
@click.option("-r", "--rule", "rule_file", help="解析规则文件（YAML格式）")
@click.option("-c", "--chip", "chip_name", help="芯片类型")
@click.option("--delimiter", default=",", help="字段分隔符（默认: 逗号）")
@click.option("--encoding", default="utf-8", help="输入文件编码")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.option("--dry-run", is_flag=True, help="仅验证规则，不生成文件")
@click.pass_context
def parse_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    rule_file: Optional[str],
    chip_name: Optional[str],
    delimiter: str,
    encoding: str,
    verbose: bool,
    dry_run: bool,
) -> None:
    """log解析转CSV命令"""
    if rule_file:
        rule = RuleLoader.load_parse_rule(rule_file)
    elif chip_name:
        rule = RuleLoader.load_chip_rule(chip_name)
    else:
        console.print("[red]错误: 需要指定 --rule 或 --chip 参数[/red]")
        raise SystemExit(1)

    if dry_run:
        console.print("[green]规则验证通过[/green]")
        console.print(f"  正则表达式: {rule.regex}")
        console.print(f"  列名: {rule.columns}")
        return

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)

    if input_path_obj.is_file():
        _parse_file(
            input_path_obj, output_path_obj, rule, delimiter, encoding, verbose
        )
    elif input_path_obj.is_dir():
        output_path_obj.mkdir(parents=True, exist_ok=True)
        files = list(input_path_obj.glob("*.log")) + list(input_path_obj.glob("*.txt"))
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for file in progress.track(files, description="解析文件..."):
                out_file = output_path_obj / f"{file.stem}.csv"
                _parse_file(file, out_file, rule, delimiter, encoding, verbose)
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)


def _parse_file(
    input_file: Path,
    output_file: Path,
    rule,
    delimiter: str,
    encoding: str,
    verbose: bool,
) -> None:
    parser = LogParser(rule)
    try:
        df = parser.parse_file(input_file, encoding)
        if df is not None and not df.empty:
            df.to_csv(output_file, index=False, sep=delimiter)
            if verbose:
                console.print(f"[green]✓[/green] {input_file.name} -> {output_file}")
        else:
            if verbose:
                console.print(f"[yellow]![/yellow] {input_file.name}: 无有效数据")
    except Exception as e:
        console.print(f"[red]✗[/red] {input_file.name}: {e}")
