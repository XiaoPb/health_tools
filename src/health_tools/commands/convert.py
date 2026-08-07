from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, cast

import click
import yaml
from rich.console import Console
from rich.table import Table

from health_tools.utils.errors import REASON_RULE_MISMATCH, classify_exception
from health_tools.utils.progress import progress_track
from health_tools.utils.reporting import ResultCollector, print_summary

if TYPE_CHECKING:
    import pandas as pd

    from health_tools.core.converter import DataConverter
    from health_tools.models.rules import ChipRule

console = Console()

ConvertStatus = Dict[str, str]

_ACC_MAP = {"x": "0", "y": "1", "z": "2"}
_ALIAS_MAP = {
    "frame_cnt": "FRAME_ID",
    "frame_id": "FRAME_ID",
    "hba_out": "ALGO_RESULT0",
}


def _normalize_col(name: str) -> str:
    """将源列名归一化为可比较的形式：小写，去掉 [] 和 _pa 后缀，[n] → n，去下划线"""
    s = name.lower().strip()
    s = s.replace("_pa", "")
    s = re.sub(r"\[(\d+)\]", r"\1", s)
    s = s.replace("_", "")
    return s


def _build_source_index(source_columns: List[str]) -> Dict[str, str]:
    """构建归一化源列名 → 原始源列名的映射"""
    index: Dict[str, str] = {}
    for col in source_columns:
        norm = _normalize_col(col)
        index[norm] = col
        if col.lower() in _ALIAS_MAP:
            index[_ALIAS_MAP[col.lower()].lower()] = col
    return index


def _match_target_col(target_col: str, source_index: Dict[str, str]) -> Optional[str]:
    """尝试将目标列匹配到源列"""
    target_lower = target_col.lower()
    if target_lower in source_index:
        return source_index[target_lower]

    # ACCX/ACCY/ACCZ → acc0/acc1/acc2
    m = re.match(r"acc([xyz])$", target_lower)
    if m:
        key = f"acc{_ACC_MAP[m.group(1)]}"
        if key in source_index:
            return source_index[key]

    # GYRO_X/Y/Z → gyro0/gyro1/gyro2
    m = re.match(r"gyro_([xyz])$", target_lower)
    if m:
        key = f"gyro{_ACC_MAP[m.group(1)]}"
        if key in source_index:
            return source_index[key]

    # Ipd0 → ipd0, Rawdata0 → rawdata0, AGC_INFO_CH0 → agc_info0
    norm_target = re.sub(r"_ch(\d+)$", r"\1", target_lower)
    norm_target = re.sub(r"_", "", norm_target)
    if norm_target in source_index:
        return source_index[norm_target]

    return None


def _generate_rule_template(
    chip_rule: ChipRule, output_path: Path, source_file: Optional[Path] = None
) -> None:
    import pandas as pd

    source_columns: List[str] = []
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
    if source_columns:
        source_index = _build_source_index(source_columns)
        matched_sources = set()
        for target_col in chip_rule.columns:
            matched = _match_target_col(target_col, source_index)
            if matched:
                column_mapping[matched] = target_col
                matched_sources.add(matched)
        for src_col in source_columns:
            if src_col not in matched_sources:
                column_mapping[src_col] = "Unknown"
    else:
        for target_col in chip_rule.columns:
            column_mapping[target_col] = target_col

    source_csv_config = {
        "header_row": 1,
        "data_start_row": 2,
        "delimiter": ",",
    }
    if source_file and source_file.is_file():
        try:
            with open(source_file, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line and ("," not in first_line or first_line.startswith("Version")):
                source_csv_config = {
                    "info_row": 1,
                    "header_row": 2,
                    "data_start_row": 3,
                    "delimiter": ",",
                    "info": first_line,
                }
        except Exception:
            pass

    template = {
        "version": "1.0",
        "description": f"转换为{chip_rule.chip}格式",
        "target_chip": chip_rule.chip,
        "csv": source_csv_config,
        "column_mapping": column_mapping,
    }

    template["extra_source"] = {
        "suffix": ".txt",
        "csv": {
            "header_row": 1,
            "data_start_row": 2,
            "delimiter": ",",
        },
        "align": {
            "left_on": "time",
            "right_on": "time",
        },
        "column_mapping": {
            "polar": "REF_RESULT0",
        },
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
        f.write("# split:  # 先分割再转换（by_column/by_size/by_time）\n")
        f.write("# classify: []  # 转换后分类（完整 classify 规则参数）\n")

    if source_columns:
        matched_count = sum(1 for v in column_mapping.values() if v != "Unknown")
        console.print(
            f"[green]OK[/green] 模板已生成: {output_path} "
            f"(源列 {len(source_columns)} 个, 匹配 {matched_count}/{len(source_columns)})"
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
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件（目录模式）")
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
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """CSV格式转换"""
    from health_tools.api import ConvertRequest, run_convert
    from health_tools.commands.api_support import CliExecution, invoke_api, print_batch

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_convert(
                ConvertRequest(
                    input_path=Path(input_path) if input_path else None,
                    output_path=Path(output_path) if output_path else None,
                    rule_file=rule_file,
                    chip_name=chip_name,
                    from_format=from_format,
                    to_format=to_format,
                    merge=merge,
                    split=split,
                    init_rule=init_rule,
                    filter_name=filter_name,
                ),
                context=context,
            )
        )
    print_batch("转换汇总", result, console, verbose)
    return


def _read_input_csv(file_path: Path, csv_config: Optional[dict]) -> pd.DataFrame:
    import pandas as pd

    if csv_config:
        from health_tools.models.rules import ChipRule
        from health_tools.utils.csv_handler import CSVHandler

        handler = CSVHandler(ChipRule(chip="input", csv=csv_config, columns=[]))
        try:
            _, df = handler.read(file_path, auto_detect_encoding=False)
            return df
        except Exception:
            header_row = csv_config.get("header_row", 1) - 1
            data_start = csv_config.get("data_start_row", 2) - 1
            skip = list(range(0, header_row)) + list(range(header_row + 1, data_start))
            return pd.read_csv(
                file_path,
                header=0,
                skiprows=skip if skip else None,
                on_bad_lines="skip",
            )
    return pd.read_csv(file_path, on_bad_lines="skip")


def _write_output_csv(df: pd.DataFrame, output_file: Path, csv_config: Optional[dict]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if csv_config:
        from health_tools.models.rules import ChipRule
        from health_tools.utils.csv_handler import CSVHandler

        handler = CSVHandler(ChipRule(chip="output", csv=csv_config, columns=[]))
        info = csv_config.get("info", "")
        handler.write(output_file, df, info=info if info else None)
    else:
        df.to_csv(output_file, index=False)


def _print_convert_results_table(results: List[ConvertStatus], verbose: bool) -> None:
    if not results:
        return
    visible_results = results if verbose else [r for r in results if r["status"] != "OK"]
    if not visible_results:
        ok_count = sum(1 for r in results if r["status"] == "OK")
        console.print(f"[green]OK[/green] 转换完成: {ok_count} 个文件")
        return

    table = Table(title="转换结果")
    table.add_column("状态", no_wrap=True)
    table.add_column("输入")
    table.add_column("输出")
    table.add_column("说明")
    for result in visible_results:
        style = {"OK": "green", "SKIP": "yellow", "FAIL": "red"}.get(result["status"], "")
        table.add_row(
            f"[{style}]{result['status']}[/{style}]" if style else result["status"],
            result["input"],
            result["output"],
            result["message"],
        )
    console.print(table)


def _print_convert_summary(results: List[ConvertStatus], verbose: bool) -> None:
    collector = ResultCollector()
    for result in results:
        status = result["status"]
        if status == "OK":
            collector.add_ok(result["input"], output=result["output"])
        elif status == "SKIP":
            collector.add_skip(
                result["input"],
                reason=result.get("reason", result.get("message", "")),
                output=result["output"],
                detail=result.get("message", ""),
            )
        else:
            collector.add_fail(
                result["input"],
                reason=result.get("reason", result.get("message", "")),
                output=result["output"],
                detail=result.get("message", ""),
            )
    print_summary("转换汇总", collector, console=console, verbose=verbose)


def _write_extra_source_align_error_report(
    converter: DataConverter, output_dir: Path, report_name: str = "extra_source_align_errors.csv"
) -> None:
    errors = getattr(converter, "extra_source_align_errors", [])
    if not errors:
        return

    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    report_file = output_dir / report_name
    pd.DataFrame(errors).to_csv(report_file, index=False, encoding="utf-8-sig")

    table = Table(title=f"extra_source 对齐异常 {len(errors)} 个")
    table.add_column("目录")
    table.add_column("原始文件")
    table.add_column("对比文件")
    table.add_column("对比源")
    for error in errors:
        input_file = Path(error["input_file"])
        extra_file = Path(error["extra_file"])
        table.add_row(
            str(input_file.parent),
            input_file.name,
            extra_file.name,
            error["extra_source"],
        )
    console.print(table)
    console.print(f"[yellow]WARN[/yellow] 对齐异常已保存: {report_file}")


def _convert_file(
    input_file: Path,
    output_file: Path,
    converter: DataConverter,
    input_csv_config: Optional[dict],
    output_csv_config: Optional[dict],
    verbose: bool,
) -> ConvertStatus:
    try:
        df = _read_input_csv(input_file, input_csv_config)
        if not converter.has_matching_columns(df):
            return {
                "status": "SKIP",
                "input": str(input_file),
                "output": str(output_file),
                "message": "不符合转换规则",
                "reason": REASON_RULE_MISMATCH,
            }
        result = converter.convert(df, source_file=input_file)
        if result.empty and len(result.columns) == 0:
            return {
                "status": "SKIP",
                "input": str(input_file),
                "output": str(output_file),
                "message": "不符合转换规则",
                "reason": REASON_RULE_MISMATCH,
            }
        _write_output_csv(result, output_file, output_csv_config)
        return {
            "status": "OK",
            "input": str(input_file),
            "output": str(output_file),
            "message": "",
            "reason": "",
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "input": str(input_file),
            "output": str(output_file),
            "message": str(e),
            "reason": classify_exception(e),
        }


def _merge_and_convert(
    input_dir: Path,
    output_file: Path,
    converter: DataConverter,
    input_csv_config: Optional[dict],
    output_csv_config: Optional[dict],
    split: Optional[int],
    filter_name: Optional[str],
    verbose: bool,
    show_progress: bool = True,
) -> None:
    import pandas as pd

    files = list(input_dir.rglob("*.csv"))
    if filter_name:
        files = [f for f in files if filter_name in f.name]
    dfs = []
    results: List[ConvertStatus] = []
    for file in progress_track(files, "读取CSV...", console=console, enabled=show_progress):
        try:
            df = _read_input_csv(file, input_csv_config)
            if not converter.has_matching_columns(df):
                results.append(
                    {
                        "status": "SKIP",
                        "input": str(file),
                        "output": str(output_file),
                        "message": "不符合转换规则",
                        "reason": REASON_RULE_MISMATCH,
                    }
                )
                continue
            df = converter._merge_extra_source(df, file)
            if not converter.has_matching_columns(df):
                results.append(
                    {
                        "status": "SKIP",
                        "input": str(file),
                        "output": str(output_file),
                        "message": "不符合转换规则",
                        "reason": REASON_RULE_MISMATCH,
                    }
                )
                continue
            dfs.append(df)
            results.append(
                {
                    "status": "OK",
                    "input": str(file),
                    "output": str(output_file),
                    "message": "已读取",
                    "reason": "",
                }
            )
        except Exception as e:
            results.append(
                {
                    "status": "FAIL",
                    "input": str(file),
                    "output": str(output_file),
                    "message": str(e),
                    "reason": classify_exception(e),
                }
            )

    _print_convert_results_table(results, verbose)
    _print_convert_summary(results, verbose)

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        result = converter.convert(merged)

        if split:
            total_rows = len(result)
            for i, start in enumerate(range(0, total_rows, split)):
                chunk = cast("pd.DataFrame", result.iloc[start : start + split])
                chunk_file = output_file.parent / f"{output_file.stem}_{i + 1}.csv"
                _write_output_csv(chunk, chunk_file, output_csv_config)
                if verbose:
                    console.print(f"[green]OK[/green] 保存: {chunk_file}")
        else:
            _write_output_csv(result, output_file, output_csv_config)
            if verbose:
                console.print(f"[green]OK[/green] 合并保存: {output_file}")
