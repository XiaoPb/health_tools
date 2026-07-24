from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from health_tools.utils.errors import REASON_NO_DATA
from health_tools.utils.reporting import FileResult, ResultCollector

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
    from health_tools.api import ParseRequest, run_parse
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_parse(
                ParseRequest(
                    Path(input_path),
                    Path(output_path),
                    rule_file=rule_file,
                    chip_name=chip_name,
                    delimiter=delimiter,
                    encoding=encoding,
                    filter_name=filter_name,
                    dry_run=dry_run,
                ),
                context=context,
            )
        )
    if dry_run:
        console.print("[green]规则验证通过[/green]")
    else:
        print_batch("解析结果", result, console, verbose)
    return


def _parse_file(
    input_file: Path,
    output_file: Path,
    rule,
    chip_rule,
    chip_columns,
    delimiter: str,
    encoding: str,
    verbose: bool,
) -> FileResult:
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
            return FileResult(
                status="OK",
                input=str(input_file),
                output=str(output_file),
                rows=len(df),
            )
        else:
            return FileResult(
                status="SKIP",
                input=str(input_file),
                output=str(output_file),
                reason=REASON_NO_DATA,
                detail="未匹配到可解析记录",
            )
    except Exception as e:
        collector = ResultCollector()
        return collector.add_exception(input_file, e, output=output_file)


def _parse_file_multi(
    input_file: Path,
    output_dir: Path,
    rule,
    chip_rule,
    chip_columns,
    encoding: str,
    verbose: bool,
) -> FileResult:
    from health_tools.core.parser import LogParser
    from health_tools.utils.csv_handler import write_csv

    parser = LogParser(rule, chip_columns=chip_columns)
    try:
        results = parser.parse_file_multi(input_file, encoding)
        if not results:
            return FileResult(
                status="SKIP",
                input=str(input_file),
                output=str(output_dir),
                reason=REASON_NO_DATA,
                detail="未匹配到可解析记录",
            )
        row_count = 0
        outputs = []
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
            row_count += len(df)
            outputs.append(str(out_file))
        return FileResult(
            status="OK",
            input=str(input_file),
            output=";".join(outputs),
            rows=row_count,
        )
    except Exception as e:
        collector = ResultCollector()
        return collector.add_exception(input_file, e, output=output_dir)
