from pathlib import Path
from typing import Optional

import click
import pandas as pd
from rich.console import Console

from health_tools.core.converter import DataConverter
from health_tools.rules.loader import RuleLoader

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出文件或目录")
@click.option("-r", "--rule", "rule_file", help="转换规则文件")
@click.option("-c", "--chip", "chip_name", help="目标芯片格式")
@click.option("--from", "from_format", help="源格式: compact|expand|chip")
@click.option("--to", "to_format", help="目标格式: compact|expand|chip")
@click.option("--merge", is_flag=True, help="合并多个文件")
@click.option("--split", type=int, help="按大小分割文件（行数）")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def convert_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    rule_file: Optional[str],
    chip_name: Optional[str],
    from_format: Optional[str],
    to_format: Optional[str],
    merge: bool,
    split: Optional[int],
    verbose: bool,
) -> None:
    """CSV格式转换"""
    if rule_file:
        rule = RuleLoader.load_convert_rule(rule_file)
    elif chip_name:
        rule = RuleLoader.load_chip_rule(chip_name)
    else:
        console.print("[red]错误: 需要指定 --rule 或 --chip 参数[/red]")
        raise SystemExit(1)

    converter = DataConverter(rule)

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)

    if input_path_obj.is_file():
        _convert_file(input_path_obj, output_path_obj, converter, verbose)
    elif input_path_obj.is_dir():
        if merge:
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            _merge_and_convert(input_path_obj, output_path_obj, converter, split, verbose)
        else:
            output_path_obj.mkdir(parents=True, exist_ok=True)
            files = list(input_path_obj.glob("*.csv"))
            for file in files:
                out_file = output_path_obj / file.name
                _convert_file(file, out_file, converter, verbose)
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)


def _convert_file(
    input_file: Path,
    output_file: Path,
    converter: DataConverter,
    verbose: bool,
) -> None:
    try:
        df = pd.read_csv(input_file)
        result = converter.convert(df)
        result.to_csv(output_file, index=False)
        if verbose:
            console.print(f"[green]✓[/green] {input_file.name} -> {output_file}")
    except Exception as e:
        console.print(f"[red]✗[/red] {input_file.name}: {e}")


def _merge_and_convert(
    input_dir: Path,
    output_file: Path,
    converter: DataConverter,
    split: Optional[int],
    verbose: bool,
) -> None:
    files = list(input_dir.glob("*.csv"))
    dfs = []
    for file in files:
        try:
            df = pd.read_csv(file)
            dfs.append(df)
            if verbose:
                console.print(f"[green]✓[/green] 读取: {file.name}")
        except Exception as e:
            console.print(f"[red]✗[/red] {file.name}: {e}")

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        result = converter.convert(merged)

        if split:
            total_rows = len(result)
            for i, start in enumerate(range(0, total_rows, split)):
                chunk = result.iloc[start : start + split]
                chunk_file = output_file.parent / f"{output_file.stem}_{i + 1}.csv"
                chunk.to_csv(chunk_file, index=False)
                if verbose:
                    console.print(f"[green]✓[/green] 保存: {chunk_file}")
        else:
            result.to_csv(output_file, index=False)
            if verbose:
                console.print(f"[green]✓[/green] 合并保存: {output_file}")
