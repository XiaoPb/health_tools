import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

console = Console()


@click.command()
@click.option("-i", "--input", "input_path", required=True, help="输入CSV文件或目录")
@click.option("-o", "--output", "output_path", required=True, help="输出目录")
@click.option(
    "-r",
    "--rule",
    "rule_file",
    default="spo2_posture.yaml",
    help="分类规则文件（默认: spo2_posture.yaml）",
)
@click.option("--extend", "extend_files", multiple=True, help="扩展patterns文件（可多次使用）")
@click.option("--accuracy", "enable_accuracy", is_flag=True, help="启用准确度计算")
@click.option("--ref-column", help="参考列名/列索引（覆盖规则配置）")
@click.option("--pred-column", help="预测列名/列索引（覆盖规则配置）")
@click.option("--copy", "mode", flag_value="copy", default=True, help="复制文件到分类目录")
@click.option("--move", "mode", flag_value="move", help="移动文件到分类目录")
@click.option("--symlink", "mode", flag_value="symlink", help="创建符号链接")
@click.option("--report", is_flag=True, help="生成分类报告")
@click.option("--unknown", "unknown_dir", help="未匹配文件的存放目录")
@click.option("-c", "--chip", "chip_name", help="芯片类型（决定CSV格式）")
@click.option("--filter", "filter_name", help="仅处理文件名包含指定字符的CSV文件")
@click.option("-v", "--verbose", is_flag=True, help="详细输出模式")
@click.pass_context
def classify_cmd(
    ctx: click.Context,
    input_path: str,
    output_path: str,
    rule_file: str,
    extend_files: Tuple[str, ...],
    enable_accuracy: bool,
    ref_column: Optional[str],
    pred_column: Optional[str],
    mode: str,
    report: bool,
    unknown_dir: Optional[str],
    chip_name: Optional[str],
    filter_name: Optional[str],
    verbose: bool,
) -> None:
    """根据规则对数据进行分类保存"""
    from health_tools.core.classifier import DataClassifier
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.accuracy import AccuracyCalculator
    from health_tools.utils.csv_handler import CSVHandler

    extend_list = list(extend_files) if extend_files else None
    rule = RuleLoader.load_classify_rule(rule_file, extend_list)

    chip_rule = None
    if chip_name:
        chip_rule = RuleLoader.load_chip_rule(chip_name)
    elif rule.target_chip:
        chip_rule = RuleLoader.load_chip_rule(rule.target_chip)

    classifier = DataClassifier(rule, chip_rule)

    input_path_obj = Path(input_path)
    output_path_obj = Path(output_path)
    output_path_obj.mkdir(parents=True, exist_ok=True)

    classifier.create_structure(output_path_obj)

    accuracy_config = rule.accuracy if hasattr(rule, "accuracy") else {}
    accuracy_calc: Optional[AccuracyCalculator] = None

    if enable_accuracy and (accuracy_config or (ref_column and pred_column)):
        ref_col = ref_column or accuracy_config.get("ref_column")
        pred_col = pred_column or accuracy_config.get("pred_column")
        methods = accuracy_config.get(
            "methods", ["std", "rmse", "mae", "within_1", "within_2", "within_3"]
        )
        thresholds = accuracy_config.get("thresholds", [])

        if ref_col and pred_col:
            accuracy_calc = AccuracyCalculator(
                ref_column=ref_col,
                pred_column=pred_col,
                methods=methods,
                thresholds=thresholds,
            )

    csv_handler = CSVHandler(chip_rule)
    stats: Dict[str, int] = {}
    category_files: Dict[str, List[Path]] = {}

    if input_path_obj.is_file():
        files = [input_path_obj]
    elif input_path_obj.is_dir():
        files = list(input_path_obj.rglob("*.csv"))
        if filter_name:
            files = [f for f in files if filter_name in f.name]
    else:
        console.print(f"[red]错误: 输入路径不存在: {input_path}[/red]")
        raise SystemExit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for file in progress.track(files, description="分类文件..."):
            try:
                target_dir = classifier.classify(file, output_path_obj)
                if target_dir:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_path = target_dir / file.name
                    if mode == "copy":
                        shutil.copy2(file, target_path)
                    elif mode == "move":
                        shutil.move(str(file), str(target_path))
                    elif mode == "symlink":
                        target_path.symlink_to(file.resolve())

                    category = str(target_dir.relative_to(output_path_obj))
                    stats[category] = stats.get(category, 0) + 1

                    if category not in category_files:
                        category_files[category] = []
                    category_files[category].append(target_path)

                    if accuracy_calc:
                        try:
                            info, df = csv_handler.read(target_path)
                            accuracy_calc.add_file_result(category, df)
                        except Exception as e:
                            if verbose:
                                console.print(
                                    f"[yellow]WARN[/yellow] 准确率计算跳过 {file.name}: {e}"
                                )

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
                        debug_info = classifier.get_last_values()
                        if debug_info["filename"]:
                            console.print(f"  文件名字段: {debug_info['filename']}")
                        if debug_info["extracted"]:
                            console.print(f"  提取值: {debug_info['extracted']}")
            except Exception as e:
                console.print(f"[red]FAIL[/red] {file.name}: {e}")

    if report:
        _print_report(stats)

    if accuracy_calc:
        accuracy_calc.print_report()
        accuracy_report_path = output_path_obj / "accuracy_summary.csv"
        accuracy_calc.save_report(accuracy_report_path)


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
