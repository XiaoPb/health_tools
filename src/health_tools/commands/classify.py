import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import click
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from health_tools.core.classifier import DataClassifier
from health_tools.rules.loader import RuleLoader

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option("-r", "--rule", "rule_file", required=True, help="分类规则文件")
@click.option("--copy", "mode", flag_value="copy", default=True, help="复制文件到分类目录")
@click.option("--move", "mode", flag_value="move", help="移动文件到分类目录")
@click.option("--symlink", "mode", flag_value="symlink", help="创建符号链接")
@click.option("--report", is_flag=True, help="生成分类报告")
@click.option("--unknown", "unknown_dir", help="未匹配文件的存放目录")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def classify_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    rule_file: str,
    mode: str,
    report: bool,
    unknown_dir: Optional[str],
    verbose: bool,
) -> None:
    """根据规则对数据进行分类保存"""
    rule = RuleLoader.load_classify_rule(rule_file)
    classifier = DataClassifier(rule)

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)

    classifier.create_structure(output_path_obj)

    stats: Dict[str, int] = {}

    if input_path_obj.is_file():
        files = [input_path_obj]
    elif input_path_obj.is_dir():
        files = list(input_path_obj.glob("*.csv"))
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for file in progress.track(files, description="分类文件..."):
            target_dir = classifier.classify(file, output_path_obj)
            if target_dir:
                target_path = target_dir / file.name
                if mode == "copy":
                    shutil.copy2(file, target_path)
                elif mode == "move":
                    shutil.move(str(file), str(target_path))
                elif mode == "symlink":
                    target_path.symlink_to(file.resolve())

                category = str(target_dir.relative_to(output_path_obj))
                stats[category] = stats.get(category, 0) + 1

                if verbose:
                    console.print(f"[green]✓[/green] {file.name} -> {category}")
            else:
                if unknown_dir:
                    unknown_path = output_path_obj / unknown_dir
                    unknown_path.mkdir(parents=True, exist_ok=True)
                    if mode == "copy":
                        shutil.copy2(file, unknown_path / file.name)
                    elif mode == "move":
                        shutil.move(str(file), str(unknown_path / file.name))
                    stats[unknown_dir] = stats.get(unknown_dir, 0) + 1
                if verbose:
                    console.print(f"[yellow]![/yellow] {file.name}: 未匹配")

    if report:
        _print_report(stats)


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
