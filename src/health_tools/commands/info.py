from pathlib import Path

import click
import pandas as pd
import yaml
from rich.console import Console
from rich.table import Table

console = Console()

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
    target_path = Path(target)

    if not target_path.exists():
        console.print(f"[red]错误: 文件不存在: {target}[/red]")
        raise SystemExit(1)

    if target_path.suffix in (".yaml", ".yml"):
        _show_rule_info(target_path, schema)
    elif target_path.suffix == ".csv":
        _show_csv_info(target_path, stats, schema, preview)
    else:
        console.print(f"[red]错误: 不支持的文件类型: {target_path.suffix}[/red]")
        raise SystemExit(1)


def _show_rule_info(file_path: Path, show_schema: bool) -> None:
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
