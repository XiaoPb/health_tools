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
                    errors.append(f"正则捕获组数量({groups})与列名数量({len(columns)})不匹配")
            except re.error as e:
                errors.append(f"正则表达式错误: {e}")

    elif rule_type == "classify":
        if "structure" not in rule:
            errors.append("分类规则缺少 'structure' 字段")

    elif rule_type == "convert":
        has_mapping = "column_mapping" in rule and isinstance(rule.get("column_mapping"), dict)
        has_source_target = "source_columns" in rule and "target_columns" in rule
        if not has_mapping and not has_source_target:
            errors.append(
                "转换规则需要提供 'column_mapping' 或同时提供 'source_columns'/'target_columns'"
            )
        if has_source_target:
            src_cols = _expand_columns(rule["source_columns"])
            tgt_cols = _expand_columns(rule["target_columns"])
            if len(src_cols) != len(tgt_cols):
                errors.append(f"源列数({len(src_cols)})与目标列数({len(tgt_cols)})不匹配")
        extra_source = rule.get("extra_source")
        if extra_source is not None:
            if not isinstance(extra_source, dict):
                errors.append("'extra_source' 必须是字典")
            else:
                if "column_mapping" in extra_source and not isinstance(
                    extra_source.get("column_mapping"), dict
                ):
                    errors.append("'extra_source.column_mapping' 必须是字典")
                for key in ("required_columns", "any_required_columns"):
                    if key in extra_source and not isinstance(extra_source.get(key), list):
                        errors.append(f"'extra_source.{key}' 必须是列表")
                align = extra_source.get("align")
                if align is not None:
                    if not isinstance(align, dict):
                        errors.append("'extra_source.align' 必须是字典")
                    elif not align.get("left_on") or not align.get("right_on"):
                        errors.append("'extra_source.align' 需要同时提供 'left_on' 和 'right_on'")

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
