"""全局配置命令"""

from typing import Optional

import click
from rich.console import Console

from health_tools.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_RULES_DIR,
    get_user_rules_dir,
    init_config_dir,
    load_config,
    save_config,
)

console = Console()


@click.command()
@click.option("--init", "do_init", is_flag=True, help="初始化用户配置目录")
@click.option("--force", "do_force", is_flag=True, help="强制更新内置规则文件（覆盖已有）")
@click.option("--show", "do_show", is_flag=True, help="显示当前配置")
@click.option("--rules-dir", "rules_dir", help="设置规则目录路径")
@click.pass_context
def config_cmd(
    ctx: click.Context,
    do_init: bool,
    do_force: bool,
    do_show: bool,
    rules_dir: Optional[str],
) -> None:
    """全局配置管理"""
    if do_init or do_force:
        path = init_config_dir()
        console.print(f"[green]OK[/green] 配置目录已初始化: {path}")
        console.print(f"  规则目录: {DEFAULT_RULES_DIR}")

        from health_tools.config import sync_builtin_rules

        count = sync_builtin_rules(force=do_force)
        if do_force:
            console.print(f"  已强制更新 {count} 个内置规则文件")
        else:
            console.print(f"  已同步 {count} 个内置规则文件到用户目录")
        console.print("  子目录: chip/ parse/ classify/ convert/ evaluate/")
        return

    if rules_dir:
        config = load_config()
        config["rules_dir"] = rules_dir
        save_config(config)
        console.print(f"[green]OK[/green] 规则目录已设置: {rules_dir}")
        return

    if do_show or not (do_init or rules_dir):
        config = load_config()
        console.print(f"配置目录: {CONFIG_DIR}")
        console.print(f"配置文件: {CONFIG_FILE} ({'存在' if CONFIG_FILE.exists() else '不存在'})")
        user_dir = get_user_rules_dir()
        console.print(
            f"规则目录: {user_dir if user_dir else DEFAULT_RULES_DIR} ({'有效' if user_dir else '未初始化'})"
        )
        if user_dir:
            for subdir in ["chip", "parse", "classify", "convert", "evaluate"]:
                sub_path = user_dir / subdir
                count = len(list(sub_path.glob("*.yaml"))) if sub_path.exists() else 0
                console.print(f"  {subdir}/: {count} 个规则文件")
