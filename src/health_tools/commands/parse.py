from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出文件或目录")
@click.option("-r", "--rule", "rule_file", help="解析规则文件（YAML格式）")
@click.option("-c", "--chip", "chip_name", help="芯片类型")
@click.option("--delimiter", default=",", help="字段分隔符（默认: 逗号）")
@click.option("--encoding", default="utf-8", help="输入文件编码")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的文件（目录模式）")
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
    filter_name: Optional[str],
    verbose: bool,
    dry_run: bool,
) -> None:
    """log解析转CSV命令"""
    from health_tools.rules.loader import RuleLoader

    chip_columns = None
    chip_rule = None
    if rule_file:
        rule = RuleLoader.load_parse_rule(rule_file)
        if rule.chip:
            chip_rule = RuleLoader.load_chip_rule(rule.chip)
            chip_columns = chip_rule.columns
    elif chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)
        rule = chip_rule
    else:
        console.print("[red]错误: 需要指定 --rule 或 --chip 参数[/red]")
        raise SystemExit(1)

    multi_mode = bool(getattr(rule, "patterns", None))

    if dry_run:
        console.print("[green]规则验证通过[/green]")
        if multi_mode:
            for name, pat in rule.patterns.items():
                console.print(f"  [{name}] 正则: {pat.regex}")
                console.print(f"  [{name}] 列名: {pat.columns}")
        else:
            console.print(f"  正则表达式: {rule.regex}")
            console.print(f"  列名: {rule.columns}")
        if chip_columns:
            console.print(f"  芯片列数: {len(chip_columns)}")
        return

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)

    if multi_mode:
        output_path_obj.mkdir(parents=True, exist_ok=True)

    if input_path_obj.is_file():
        if multi_mode:
            _parse_file_multi(
                input_path_obj, output_path_obj, rule, chip_rule, chip_columns, encoding, verbose
            )
        else:
            _parse_file(
                input_path_obj,
                output_path_obj,
                rule,
                chip_rule,
                chip_columns,
                delimiter,
                encoding,
                verbose,
            )
    elif input_path_obj.is_dir():
        output_path_obj.mkdir(parents=True, exist_ok=True)
        files = list(input_path_obj.rglob("*.log")) + list(input_path_obj.rglob("*.txt"))
        if filter_name:
            files = [f for f in files if filter_name in f.name]
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            for file in progress.track(files, description="解析文件..."):
                if multi_mode:
                    _parse_file_multi(
                        file, output_path_obj, rule, chip_rule, chip_columns, encoding, verbose
                    )
                else:
                    out_file = output_path_obj / f"{file.stem}.csv"
                    _parse_file(
                        file, out_file, rule, chip_rule, chip_columns, delimiter, encoding, verbose
                    )
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)


def _parse_file(
    input_file: Path,
    output_file: Path,
    rule,
    chip_rule,
    chip_columns,
    delimiter: str,
    encoding: str,
    verbose: bool,
) -> None:
    from health_tools.core.parser import LogParser
    from health_tools.utils.csv_handler import write_csv

    parser = LogParser(rule, chip_columns=chip_columns)
    try:
        df = parser.parse_file(input_file, encoding)
        if df is not None and not df.empty:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            if chip_rule:
                write_csv(output_file, df, chip_rule=chip_rule, info=chip_rule.info)
            else:
                df.to_csv(output_file, index=False, sep=delimiter)
            if verbose:
                console.print(f"[green]OK[/green] {input_file.name} -> {output_file} ({len(df)}行)")
        else:
            if verbose:
                console.print(f"[yellow]WARN[/yellow] {input_file.name}: 无有效数据")
    except Exception as e:
        console.print(f"[red]FAIL[/red] {input_file.name}: {e}")


def _parse_file_multi(
    input_file: Path,
    output_dir: Path,
    rule,
    chip_rule,
    chip_columns,
    encoding: str,
    verbose: bool,
) -> None:
    from health_tools.core.parser import LogParser
    from health_tools.utils.csv_handler import write_csv

    parser = LogParser(rule, chip_columns=chip_columns)
    try:
        results = parser.parse_file_multi(input_file, encoding)
        if not results:
            if verbose:
                console.print(f"[yellow]WARN[/yellow] {input_file.name}: 无有效数据")
            return
        for name, df in results.items():
            out_file = output_dir / f"{input_file.stem}_{name}.csv"
            if chip_rule:
                write_csv(out_file, df, chip_rule=chip_rule, info=chip_rule.info)
            else:
                df.to_csv(out_file, index=False)
            if verbose:
                console.print(
                    f"[green]OK[/green] {input_file.name} [{name}] -> {out_file} ({len(df)}行)"
                )
    except Exception as e:
        console.print(f"[red]FAIL[/red] {input_file.name}: {e}")
