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
) -> None:
    """全局配置管理"""
    from health_tools.api import ConfigAction, ConfigRequest, run_config
    from health_tools.commands.api_support import CliExecution, invoke_api

    if do_init or do_force:
        action, value = ConfigAction.INIT, None
    elif rules_dir:
        action, value = ConfigAction.SET_RULES_DIR, rules_dir
    elif offline_path:
        action, value = ConfigAction.SET_OFFLINE_PATH, offline_path
    elif offline_default:
        action, value = ConfigAction.SET_OFFLINE_DEFAULT, offline_default
    elif do_offline_scan:
        action, value = ConfigAction.SCAN_OFFLINE, None
    else:
        action, value = ConfigAction.SHOW, None
    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_config(ConfigRequest(action, value=value, force=do_force), context=context)
        )
    console.print(f"[green]OK[/green] 配置操作完成: {result.action.value}")
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
