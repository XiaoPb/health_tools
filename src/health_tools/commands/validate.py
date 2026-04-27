from pathlib import Path

import click
import yaml
from rich.console import Console

console = Console()


@click.command()
@click.argument("rule_file", required=True)
@click.option("--strict", is_flag=True, help="严格模式验证")
@click.pass_context
def validate_cmd(ctx: click.Context, rule_file: str, strict: bool) -> None:
    """验证YAML规则文件格式和内容"""
    rule_path = Path(rule_file)

    if not rule_path.exists():
        console.print(f"[red]错误: 文件不存在: {rule_file}[/red]")
        raise SystemExit(1)

    if rule_path.suffix not in (".yaml", ".yml"):
        console.print(f"[red]错误: 文件必须是YAML格式: {rule_file}[/red]")
        raise SystemExit(1)

    try:
        with open(rule_path, "r", encoding="utf-8") as f:
            rule = yaml.safe_load(f)

        if not isinstance(rule, dict):
            console.print("[red]错误: 规则文件必须是一个字典结构[/red]")
            raise SystemExit(1)

        errors = _validate_rule(rule, rule_path, strict)

        if errors:
            console.print(f"\n[red]验证失败，发现 {len(errors)} 个错误:[/red]\n")
            for error in errors:
                console.print(f"  [red]✗[/red] {error}")
            raise SystemExit(1)
        else:
            console.print(f"[green]✓[/green] 规则文件验证通过: {rule_file}")

    except yaml.YAMLError as e:
        console.print(f"[red]YAML解析错误: {e}[/red]")
        raise SystemExit(1)


def _validate_rule(rule: dict, rule_path: Path, strict: bool) -> list:
    errors = []

    if "version" not in rule:
        errors.append("缺少 'version' 字段")

    rule_type = _detect_rule_type(rule_path)

    if rule_type == "chip":
        if "chip" not in rule:
            errors.append("芯片规则缺少 'chip' 字段")
        if "csv" not in rule:
            errors.append("芯片规则缺少 'csv' 字段")
        elif isinstance(rule.get("csv"), dict):
            csv_config = rule["csv"]
            if "header_row" not in csv_config:
                errors.append("csv配置缺少 'header_row' 字段")
            if "data_start_row" not in csv_config:
                errors.append("csv配置缺少 'data_start_row' 字段")
        if "columns" not in rule:
            errors.append("芯片规则缺少 'columns' 字段")

    elif rule_type == "parse":
        if "regex" not in rule:
            errors.append("解析规则缺少 'regex' 字段")
        if "columns" not in rule:
            errors.append("解析规则缺少 'columns' 字段")
        else:
            import re

            try:
                pattern = re.compile(rule["regex"])
                groups = pattern.groups
                columns = _expand_columns(rule["columns"])
                if len(columns) != groups:
                    errors.append(
                        f"正则捕获组数量({groups})与列名数量({len(columns)})不匹配"
                    )
            except re.error as e:
                errors.append(f"正则表达式错误: {e}")

    elif rule_type == "classify":
        if "structure" not in rule:
            errors.append("分类规则缺少 'structure' 字段")

    elif rule_type == "convert":
        if "source_columns" not in rule:
            errors.append("转换规则缺少 'source_columns' 字段")
        if "target_columns" not in rule:
            errors.append("转换规则缺少 'target_columns' 字段")

    if strict:
        if rule_type == "parse":
            if "description" not in rule:
                errors.append("[严格模式] 缺少 'description' 字段")

    return errors


def _detect_rule_type(rule_path: Path) -> str:
    parts = rule_path.parts
    if "chip" in parts:
        return "chip"
    elif "parse" in parts:
        return "parse"
    elif "classify" in parts:
        return "classify"
    elif "convert" in parts:
        return "convert"
    return "unknown"


def _expand_columns(columns: list) -> list:
    import re

    expanded = []
    for col in columns:
        match = re.match(r"^(.+?)\[(\d+)-(\d+)\]$", col)
        if match:
            prefix, start, end = match.groups()
            for i in range(int(start), int(end) + 1):
                expanded.append(f"{prefix}{i}")
        else:
            expanded.append(col)
    return expanded
