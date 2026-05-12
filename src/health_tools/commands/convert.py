from pathlib import Path
from typing import Optional

import click
import pandas as pd
import yaml
from rich.console import Console

from health_tools.core.converter import DataConverter
from health_tools.models.rules import ChipRule, ConvertRule
from health_tools.rules.loader import RuleLoader
from health_tools.utils.csv_handler import CSVHandler

console = Console()


def _generate_rule_template(
    chip_rule: ChipRule, output_path: Path, source_file: Optional[Path] = None
) -> None:
    source_columns = []
    if source_file and source_file.is_file():
        try:
            df = pd.read_csv(source_file, nrows=0)
            cols = list(df.columns)
            if len(cols) == 1 or any(col.startswith("Version") for col in cols):
                df = pd.read_csv(source_file, header=1, nrows=0)
                cols = list(df.columns)
            source_columns = cols
        except Exception:
            pass

    column_mapping = {}
    source_lower_map = {col.lower(): col for col in source_columns}
    for target_col in chip_rule.columns:
        if target_col.lower() in source_lower_map:
            column_mapping[target_col] = source_lower_map[target_col.lower()]
        elif source_columns and target_col in source_columns:
            column_mapping[target_col] = target_col
        else:
            column_mapping[target_col] = "Unknown" if source_columns else target_col

    template = {
        "version": "1.0",
        "description": f"转换为{chip_rule.chip}格式",
        "target_chip": chip_rule.chip,
        "csv": chip_rule.csv,
        "column_mapping": column_mapping,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            template,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        f.write("\n# forward_fill: []  # 前向填充列（如 [TimeStamp, FRAME_ID]）\n")
        f.write("# expand_repeat: []  # 重复扩展列（如 [REF_RESULT{0-15}]）\n")

    if source_columns:
        matched = sum(1 for v in column_mapping.values() if v != "Unknown")
        console.print(
            f"[green]OK[/green] 模板已生成: {output_path} "
            f"(源列 {len(source_columns)} 个, 匹配 {matched}/{len(chip_rule.columns)})"
        )
    else:
        console.print(f"[green]OK[/green] 模板已生成: {output_path}")


@click.command()
@click.option("-i", "--input", "input_path", help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", help="输出文件或目录")
@click.option("-r", "--rule", "rule_file", help="转换规则文件")
@click.option("-c", "--chip", "chip_name", help="目标芯片格式")
@click.option("--from", "from_format", help="源格式: compact|expand|chip")
@click.option("--to", "to_format", help="目标格式: compact|expand|chip")
@click.option("--merge", is_flag=True, help="合并多个文件")
@click.option("--split", type=int, help="按大小分割文件（行数）")
@click.option("--init-rule", is_flag=True, help="生成转换规则模板")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def convert_cmd(
    ctx: click.Context,
    input_path: Optional[str],
    output_path: Optional[str],
    rule_file: Optional[str],
    chip_name: Optional[str],
    from_format: Optional[str],
    to_format: Optional[str],
    merge: bool,
    split: Optional[int],
    init_rule: bool,
    verbose: bool,
) -> None:
    """CSV格式转换"""
    if init_rule:
        if not chip_name:
            console.print("[red]错误: --init-rule 需要指定 --chip 参数[/red]")
            raise SystemExit(1)
        if not output_path:
            output_path = f"convert_{chip_name}.yaml"
        chip_rule = RuleLoader.load_chip_rule(chip_name)
        source_file = Path(input_path) if input_path else None
        _generate_rule_template(chip_rule, Path(output_path), source_file)
        return

    if not input_path or not output_path:
        console.print("[red]错误: 需要指定 --input 和 --output 参数[/red]")
        raise SystemExit(1)

    chip_rule = None
    if rule_file:
        rule = RuleLoader.load_convert_rule(rule_file)
        if rule.target_chip:
            chip_rule = RuleLoader.load_chip_rule(rule.target_chip)
    elif chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)
        rule = ConvertRule(target_chip=chip_name)
    else:
        console.print("[red]错误: 需要指定 --rule 或 --chip 参数[/red]")
        raise SystemExit(1)

    chip_columns = chip_rule.columns if chip_rule else None
    converter = DataConverter(rule, chip_columns=chip_columns)

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)

    input_csv_config = rule.csv if rule.csv else None
    output_csv_config = chip_rule.csv if chip_rule else None

    if input_path_obj.is_file():
        _convert_file(
            input_path_obj, output_path_obj, converter, input_csv_config, output_csv_config, verbose
        )
    elif input_path_obj.is_dir():
        if merge:
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            _merge_and_convert(
                input_path_obj,
                output_path_obj,
                converter,
                input_csv_config,
                output_csv_config,
                split,
                verbose,
            )
        else:
            output_path_obj.mkdir(parents=True, exist_ok=True)
            files = list(input_path_obj.glob("*.csv"))
            for file in files:
                out_file = output_path_obj / file.name
                _convert_file(
                    file, out_file, converter, input_csv_config, output_csv_config, verbose
                )
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)


def _read_input_csv(file_path: Path, csv_config: Optional[dict]) -> pd.DataFrame:
    if csv_config:
        handler = CSVHandler(ChipRule(chip="input", csv=csv_config, columns=[]))
        _, df = handler.read(file_path, auto_detect_encoding=False)
        return df
    return pd.read_csv(file_path)


def _write_output_csv(df: pd.DataFrame, output_file: Path, csv_config: Optional[dict]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if csv_config:
        handler = CSVHandler(ChipRule(chip="output", csv=csv_config, columns=[]))
        info = csv_config.get("info", "")
        handler.write(output_file, df, info=info if info else None)
    else:
        df.to_csv(output_file, index=False)


def _convert_file(
    input_file: Path,
    output_file: Path,
    converter: DataConverter,
    input_csv_config: Optional[dict],
    output_csv_config: Optional[dict],
    verbose: bool,
) -> None:
    try:
        df = _read_input_csv(input_file, input_csv_config)
        result = converter.convert(df)
        _write_output_csv(result, output_file, output_csv_config)
        if verbose:
            console.print(f"[green]OK[/green] {input_file.name} -> {output_file}")
    except Exception as e:
        console.print(f"[red]FAIL[/red] {input_file.name}: {e}")


def _merge_and_convert(
    input_dir: Path,
    output_file: Path,
    converter: DataConverter,
    input_csv_config: Optional[dict],
    output_csv_config: Optional[dict],
    split: Optional[int],
    verbose: bool,
) -> None:
    files = list(input_dir.glob("*.csv"))
    dfs = []
    for file in files:
        try:
            df = _read_input_csv(file, input_csv_config)
            dfs.append(df)
            if verbose:
                console.print(f"[green]OK[/green] 读取: {file.name}")
        except Exception as e:
            console.print(f"[red]FAIL[/red] {file.name}: {e}")

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        result = converter.convert(merged)

        if split:
            total_rows = len(result)
            for i, start in enumerate(range(0, total_rows, split)):
                chunk = result.iloc[start : start + split]
                chunk_file = output_file.parent / f"{output_file.stem}_{i + 1}.csv"
                _write_output_csv(chunk, chunk_file, output_csv_config)
                if verbose:
                    console.print(f"[green]OK[/green] 保存: {chunk_file}")
        else:
            _write_output_csv(result, output_file, output_csv_config)
            if verbose:
                console.print(f"[green]OK[/green] 合并保存: {output_file}")
