import importlib
import sys
from typing import Any

import click

from health_tools import __version__


def _configure_windows_stdio() -> None:
    """让 Windows 控制台可以输出中文帮助和错误信息。"""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        encoding = str(getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding == "utf8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_configure_windows_stdio()

COMMAND_MAP = {
    "parse": ("health_tools.commands.parse", "parse_cmd"),
    "p": ("health_tools.commands.parse", "parse_cmd"),
    "plot": ("health_tools.commands.plot", "plot_cmd"),
    "pl": ("health_tools.commands.plot", "plot_cmd"),
    "classify": ("health_tools.commands.classify", "classify_cmd"),
    "cls": ("health_tools.commands.classify", "classify_cmd"),
    "convert": ("health_tools.commands.convert", "convert_cmd"),
    "cv": ("health_tools.commands.convert", "convert_cmd"),
    "info": ("health_tools.commands.info", "info_cmd"),
    "i": ("health_tools.commands.info", "info_cmd"),
    "validate": ("health_tools.commands.validate", "validate_cmd"),
    "val": ("health_tools.commands.validate", "validate_cmd"),
    "split": ("health_tools.commands.split", "split_cmd"),
    "process": ("health_tools.commands.process", "process_cmd"),
    "snr": ("health_tools.commands.factory", "factory_cmd"),
    "factory": ("health_tools.commands.factory", "factory_cmd"),
    "fac": ("health_tools.commands.factory", "factory_cmd"),
    "config": ("health_tools.commands.config", "config_cmd"),
    "cfg": ("health_tools.commands.config", "config_cmd"),
    "evaluate": ("health_tools.commands.evaluate", "evaluate_cmd"),
    "eval": ("health_tools.commands.evaluate", "evaluate_cmd"),
    "offline": ("health_tools.commands.offline", "offline_cmd"),
    "check": ("health_tools.commands.check", "check_cmd"),
    "chk": ("health_tools.commands.check", "check_cmd"),
    "analyze": ("health_tools.commands.analyze", "analyze_cmd"),
    "ana": ("health_tools.commands.analyze", "analyze_cmd"),
}

COMMAND_HELP = {
    "parse": "log解析转CSV命令",
    "plot": "数据绘图命令",
    "classify": "数据分类命令",
    "convert": "CSV格式转换",
    "info": "查看规则和文件信息",
    "validate": "验证规则文件",
    "split": "数据分割命令",
    "process": "批量处理命令",
    "factory": "工厂测试数据分析",
    "config": "配置管理",
    "evaluate": "评估指标命令",
    "offline": "离线评估流程",
    "check": "数据质量检查",
    "analyze": "自动数据分析与诊断报告",
}

PRIMARY_COMMANDS = [
    "parse",
    "plot",
    "classify",
    "convert",
    "info",
    "validate",
    "split",
    "process",
    "factory",
    "config",
    "evaluate",
    "offline",
    "check",
    "analyze",
]

ALIASES: dict = {}
for _name, _target in COMMAND_MAP.items():
    for _primary in PRIMARY_COMMANDS:
        if _name != _primary and COMMAND_MAP.get(_primary) == _target:
            ALIASES.setdefault(_primary, []).append(_name)
            break


class LazyGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list:
        return PRIMARY_COMMANDS

    def get_command(self, ctx: click.Context, cmd_name: str) -> Any:
        if cmd_name not in COMMAND_MAP:
            return None
        module_path, attr_name = COMMAND_MAP[cmd_name]
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            return None
        return getattr(module, attr_name)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        commands = []
        for subcommand in self.list_commands(ctx):
            help_text = COMMAND_HELP.get(subcommand, "")
            aliases = ALIASES.get(subcommand, [])
            name_col = f"{subcommand} ({', '.join(aliases)})" if aliases else subcommand
            commands.append((name_col, help_text))

        if commands:
            with formatter.section("Commands"):
                formatter.write_dl(commands)


@click.group(cls=LazyGroup)
@click.version_option(version=__version__, prog_name="ghealth_tool")
@click.option("--log-level", default="info", help="日志级别: debug|info|warning|error")
@click.pass_context
def main(ctx: click.Context, log_level: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level


if __name__ == "__main__":
    main()
