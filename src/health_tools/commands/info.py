from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command()
@click.argument("target", required=True)
@click.option("--stats", is_flag=True, help="显示统计信息")
@click.option("--schema", is_flag=True, help="显示数据结构")
@click.option("--preview", type=int, default=10, help="预览前N行")
@click.pass_context
def info_cmd(
    ctx: click.Context,
    target: str,
    stats: bool,
    schema: bool,
    preview: int,
) -> None:
    """查看数据文件或规则文件信息"""
    from health_tools.api import InfoRequest, run_info
    from health_tools.commands.api_support import CliExecution, invoke_api

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_info(
                InfoRequest(Path(target), stats=stats, schema=schema, preview=preview),
                context=context,
            )
        )
    if result.kind == "rule":
        import yaml

        console.print(f"\n[bold cyan]规则文件: {result.target.name}[/bold cyan]\n")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("字段", style="cyan")
        table.add_column("值", style="green")
        for key, value in result.schema.items():
            if hasattr(value, "items"):
                text = ", ".join(f"{name}: {item}" for name, item in value.items())
            elif isinstance(value, (list, tuple)):
                text = ", ".join(str(item) for item in value[:5])
                if len(value) > 5:
                    text += f" ... ({len(value)} items)"
            else:
                text = str(value)
            table.add_row(str(key), text)
        console.print(table)
        if schema:
            console.print("\n[bold]完整结构:[/bold]")
            console.print(
                yaml.safe_dump(_plain(result.schema), allow_unicode=True, sort_keys=False)
            )
    else:
        import pandas as pd

        console.print(f"\n[bold cyan]CSV文件: {result.target.name}[/bold cyan]\n")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("属性", style="cyan")
        table.add_column("值", style="green")
        table.add_row("行数", str(result.summary["rows"]))
        table.add_row("列数", str(result.summary["columns"]))
        table.add_row("文件大小", f"{result.summary['size_bytes'] / 1024:.2f} KB")
        console.print(table)
        if schema:
            schema_table = Table(show_header=True, header_style="bold magenta")
            schema_table.add_column("列名", style="cyan")
            schema_table.add_column("类型", style="green")
            schema_table.add_column("非空数", style="yellow")
            for name, value in result.schema.items():
                schema_table.add_row(str(name), str(value["dtype"]), str(value["non_null"]))
            console.print(schema_table)
        if result.statistics:
            console.print(pd.DataFrame(_plain(result.statistics)).to_string())
        console.print(pd.DataFrame(_plain(result.preview)).to_string())
    return


def _plain(value):
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _show_rule_info(file_path: Path, show_schema: bool) -> None:
    import yaml

    with open(file_path, "r", encoding="utf-8") as f:
        rule = yaml.safe_load(f)

    console.print(f"\n[bold cyan]规则文件: {file_path.name}[/bold cyan]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("字段", style="cyan")
    table.add_column("值", style="green")

    for key, value in rule.items():
        if isinstance(value, dict):
            value_str = ", ".join(f"{k}: {v}" for k, v in value.items())
        elif isinstance(value, list):
            value_str = ", ".join(str(v) for v in value[:5])
            if len(value) > 5:
                value_str += f" ... ({len(value)} items)"
        else:
            value_str = str(value)
        table.add_row(key, value_str)

    console.print(table)

    if show_schema:
        console.print("\n[bold]完整结构:[/bold]")
        console.print(yaml.dump(rule, default_flow_style=False, allow_unicode=True))


def _show_csv_info(file_path: Path, show_stats: bool, show_schema: bool, preview_rows: int) -> None:
    import pandas as pd

    df = pd.read_csv(file_path)

    console.print(f"\n[bold cyan]CSV文件: {file_path.name}[/bold cyan]\n")

    info_table = Table(show_header=True, header_style="bold magenta")
    info_table.add_column("属性", style="cyan")
    info_table.add_column("值", style="green")

    info_table.add_row("行数", str(len(df)))
    info_table.add_row("列数", str(len(df.columns)))
    info_table.add_row("文件大小", f"{file_path.stat().st_size / 1024:.2f} KB")

    console.print(info_table)

    if show_schema:
        console.print("\n[bold]列信息:[/bold]")
        schema_table = Table(show_header=True, header_style="bold magenta")
        schema_table.add_column("列名", style="cyan")
        schema_table.add_column("类型", style="green")
        schema_table.add_column("非空数", style="yellow")

        for col in df.columns:
            schema_table.add_row(col, str(df[col].dtype), str(df[col].count()))

        console.print(schema_table)

    if show_stats:
        console.print("\n[bold]统计信息:[/bold]")
        stats_df = df.describe()
        console.print(stats_df.to_string())

    console.print(f"\n[bold]前 {preview_rows} 行预览:[/bold]")
    console.print(df.head(preview_rows).to_string())
