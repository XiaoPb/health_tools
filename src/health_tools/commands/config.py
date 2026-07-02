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

    if offline_path:
        _set_offline_path(offline_path)
        return

    if offline_default:
        _set_offline_default(offline_default)
        return

    if do_offline_scan:
        _scan_offline_versions()
        return

    if do_show or not (do_init or rules_dir):
        config = load_config()
        console.print(f"配置目录: {CONFIG_DIR}")
        console.print(f"配置文件: {CONFIG_FILE} ({'存在' if CONFIG_FILE.exists() else '不存在'})")
        user_dir = get_user_rules_dir()
        console.print(
            f"规则目录: {user_dir if user_dir else DEFAULT_RULES_DIR}"
            f" ({'有效' if user_dir else '未初始化'})"
        )
        if user_dir:
            for subdir in ["chip", "parse", "classify", "convert", "evaluate"]:
                sub_path = user_dir / subdir
                count = len(list(sub_path.glob("*.yaml"))) if sub_path.exists() else 0
                console.print(f"  {subdir}/: {count} 个规则文件")

        offline_tools_path = config.get("offline_tools_path", "")
        if offline_tools_path:
            console.print(f"离线工具路径: {offline_tools_path}")
            versions = config.get("offline_versions", {})
            for chip, info in versions.items():
                default_ver = info.get("default", "")
                categories = info.get("versions", {})
                if isinstance(categories, dict):
                    total = sum(len(v) for v in categories.values())
                    console.print(f"  {chip}: {total} 个版本, 默认={default_ver}")
                    for cat, ver_list in categories.items():
                        console.print(f"    {cat}/: {', '.join(ver_list)}")
                else:
                    ver_count = len(categories) if isinstance(categories, list) else 0
                    console.print(f"  {chip}: {ver_count} 个版本, 默认={default_ver}")


def _set_offline_path(path_str: str) -> None:
    """设置离线工具路径并自动扫描"""
    from pathlib import Path

    from health_tools.core.offline import merge_scanned_versions, save_offline_config, scan_versions

    tools_path = Path(path_str)
    if not tools_path.exists():
        console.print(f"[red]错误: 路径不存在: {path_str}[/red]")
        raise SystemExit(1)

    config = load_config()
    versions = merge_scanned_versions(scan_versions(tools_path), config.get("offline_versions", {}))
    save_offline_config(tools_path, versions)

    console.print(f"[green]OK[/green] 离线工具路径已设置: {tools_path}")
    if versions:
        for chip, info in versions.items():
            categories = info.get("versions", {})
            default_ver = info.get("default", "")
            total = sum(len(v) for v in categories.values()) if isinstance(categories, dict) else 0
            console.print(f"  {chip}: {total} 个版本, 默认={default_ver}")
            if isinstance(categories, dict):
                for cat, ver_list in categories.items():
                    console.print(f"    {cat}/: {len(ver_list)} 个版本")
    else:
        console.print("  [yellow]未发现任何版本[/yellow]")


def _set_offline_default(default_str: str) -> None:
    """设置芯片默认版本"""
    if "=" not in default_str:
        console.print("[red]错误: 格式应为 chip=version (如 gh3036=GH_HR_exc_v1.0)[/red]")
        raise SystemExit(1)

    chip, version = default_str.split("=", 1)
    config = load_config()
    versions = config.get("offline_versions", {})

    if chip not in versions:
        console.print(f"[red]错误: 未找到芯片 {chip} 的版本信息[/red]")
        console.print("请先运行: ghealth_tool cfg --offline-scan")
        raise SystemExit(1)

    categories = versions[chip].get("versions", {})
    if isinstance(categories, dict):
        all_versions = [v for ver_list in categories.values() for v in ver_list]
        found_category = None
        for cat, ver_list in categories.items():
            if version in ver_list:
                found_category = cat
                break
    else:
        all_versions = categories if isinstance(categories, list) else []
        found_category = "exclusive"

    if version not in all_versions:
        console.print(f"[red]错误: 版本 {version} 不在可用列表中[/red]")
        console.print(f"可用版本: {', '.join(all_versions)}")
        raise SystemExit(1)

    versions[chip]["default"] = version
    if found_category:
        versions[chip]["default_category"] = found_category
    config["offline_versions"] = versions
    save_config(config)
    console.print(f"[green]OK[/green] {chip} 默认版本已设置: {version}")


def _scan_offline_versions() -> None:
    """重新扫描离线工具版本"""
    from health_tools.core.offline import (
        get_category_label,
        get_offline_config,
        merge_scanned_versions,
        save_offline_config,
        scan_versions,
    )

    cfg = get_offline_config()
    if not cfg.tools_path.exists():
        console.print(f"[red]错误: 离线工具路径不存在: {cfg.tools_path}[/red]")
        console.print("请先设置: ghealth_tool cfg --offline-path <路径>")
        raise SystemExit(1)

    config = load_config()
    versions = merge_scanned_versions(
        scan_versions(cfg.tools_path), config.get("offline_versions", {})
    )
    save_offline_config(cfg.tools_path, versions)

    console.print(f"[green]OK[/green] 扫描完成: {cfg.tools_path}")
    if versions:
        for chip, info in versions.items():
            categories = info.get("versions", {})
            default_ver = info.get("default", "")
            total = sum(len(v) for v in categories.values()) if isinstance(categories, dict) else 0
            console.print(f"  {chip}: {total} 个版本, 默认={default_ver}")
            if isinstance(categories, dict):
                for cat, ver_list in categories.items():
                    cat_label = get_category_label(cat)
                    console.print(f"    {cat_label}/: {len(ver_list)} 个版本")
                    for v in ver_list:
                        marker = " [green]*默认[/green]" if v == default_ver else ""
                        console.print(f"      - {v}{marker}")
    else:
        console.print("  [yellow]未发现任何版本[/yellow]")
