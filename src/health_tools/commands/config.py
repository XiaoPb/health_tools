"""全局配置命令"""

from collections.abc import Mapping
from typing import Optional

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("--init", "do_init", is_flag=True, help="初始化用户配置目录")
@click.option("--force", "do_force", is_flag=True, help="强制更新内置规则文件（覆盖已有）")
@click.option("--show", "do_show", is_flag=True, help="显示当前配置")
@click.option("--rules-dir", "rules_dir", help="设置规则目录路径")
@click.option("--offline-path", "offline_path", help="设置离线工具搜索路径（自动扫描版本）")
@click.option("--offline-default", "offline_default", help="设置芯片默认版本 (格式: chip=version)")
@click.option("--offline-scan", "do_offline_scan", is_flag=True, help="重新扫描离线工具版本")
@click.option("--add", "do_add", is_flag=True, help="添加用户规则")
@click.option(
    "--chip", "chip_rule", type=click.Path(exists=True, dir_okay=False), help="添加 chip 规则文件"
)
@click.option(
    "--parse",
    "parse_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 parse 规则文件",
)
@click.option(
    "--classify",
    "classify_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 classify 规则文件",
)
@click.option(
    "--convert",
    "convert_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 convert 规则文件",
)
@click.option(
    "--evaluate",
    "evaluate_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 evaluate 规则文件",
)
@click.option(
    "--analysis",
    "analysis_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 analysis 规则文件",
)
@click.option(
    "--check",
    "check_rule",
    type=click.Path(exists=True, dir_okay=False),
    help="添加 check 规则文件",
)
@click.argument("subcommand", required=False)
@click.pass_context
def config_cmd(
    ctx: click.Context,
    do_init: bool,
    do_force: bool,
    do_show: bool,
    rules_dir: Optional[str],
    offline_path: Optional[str],
    offline_default: Optional[str],
    do_offline_scan: bool,
    do_add: bool,
    chip_rule: Optional[str],
    parse_rule: Optional[str],
    classify_rule: Optional[str],
    convert_rule: Optional[str],
    evaluate_rule: Optional[str],
    analysis_rule: Optional[str],
    check_rule: Optional[str],
    subcommand: Optional[str],
) -> None:
    """全局配置管理"""
    from health_tools.api import ConfigAction, ConfigRequest, run_config
    from health_tools.commands.api_support import CliExecution, invoke_api

    selected_rules = [
        ("chip", chip_rule),
        ("parse", parse_rule),
        ("classify", classify_rule),
        ("convert", convert_rule),
        ("evaluate", evaluate_rule),
        ("analysis", analysis_rule),
        ("check", check_rule),
    ]
    selected_rules = [(name, path) for name, path in selected_rules if path]
    if subcommand not in (None, "add"):
        raise click.UsageError(f"未知 cfg 子命令: {subcommand}")
    do_add = do_add or subcommand == "add"
    if do_add:
        if len(selected_rules) != 1:
            raise click.UsageError("--add 必须且只能配合一个规则类型选项使用")
        from health_tools.api import RuleType

        rule_name, rule_path = selected_rules[0]
        action, value, rule_type = ConfigAction.ADD_RULE, rule_path, RuleType(rule_name)
    elif any(path for _, path in selected_rules):
        raise click.UsageError("规则类型选项必须与 --add 一起使用")
    elif do_init or do_force:
        action, value = ConfigAction.INIT, None
        rule_type = None
    elif rules_dir:
        action, value = ConfigAction.SET_RULES_DIR, rules_dir
        rule_type = None
    elif offline_path:
        action, value = ConfigAction.SET_OFFLINE_PATH, offline_path
        rule_type = None
    elif offline_default:
        action, value = ConfigAction.SET_OFFLINE_DEFAULT, offline_default
        rule_type = None
    elif do_offline_scan:
        action, value = ConfigAction.SCAN_OFFLINE, None
        rule_type = None
    else:
        action, value = ConfigAction.SHOW, None
        rule_type = None
    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_config(
                ConfigRequest(action, value=value, force=do_force, rule_type=rule_type),
                context=context,
            )
        )
    console.print(f"[green]OK[/green] 配置操作完成: {result.action.value}")
    if action == ConfigAction.ADD_RULE:
        console.print(f"已添加规则文件: {result.changed_paths[0]}")
    if action == ConfigAction.SHOW:
        console.print(dict(result.config))
    elif action in (ConfigAction.SCAN_OFFLINE, ConfigAction.SET_OFFLINE_PATH):
        _print_versions_summary(result.versions)
    elif action == ConfigAction.SET_OFFLINE_DEFAULT:
        if result.versions:
            _print_versions_summary(result.versions)
    return


def _print_versions_summary(versions: Mapping) -> None:
    """打印离线版本汇总信息。"""
    from health_tools.core.offline import get_category_label

    if not versions:
        console.print("  [yellow]未发现任何版本[/yellow]")
        return

    for chip, info in sorted(versions.items()):
        if not isinstance(info, Mapping):
            continue
        categories = info.get("versions", {})
        default_ver = info.get("default", "")
        if isinstance(categories, Mapping):
            total = sum(len(v) for v in categories.values())
        else:
            total = 0
        console.print(f"  {chip}: {total} 个版本, 默认={default_ver}")
        if isinstance(categories, Mapping):
            for cat, ver_list in sorted(categories.items()):
                cat_label = get_category_label(cat)
                console.print(f"    {cat_label}/ ({len(ver_list)} 个)")
                for v in ver_list:
                    marker = " [green]*默认[/green]" if v == default_ver else ""
                    console.print(f"      - {v}{marker}")
