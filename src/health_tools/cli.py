import importlib
from typing import Any

import click

from health_tools import __version__

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
    "snr": ("health_tools.commands.snr", "snr_cmd"),
}


class LazyGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list:
        return sorted(set(COMMAND_MAP.keys()))

    def get_command(self, ctx: click.Context, cmd_name: str) -> Any:
        if cmd_name not in COMMAND_MAP:
            return None
        module_path, attr_name = COMMAND_MAP[cmd_name]
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            return None
        return getattr(module, attr_name)


@click.group(cls=LazyGroup)
@click.version_option(version=__version__, prog_name="ghealth_tool")
@click.option("--log-level", default="info", help="日志级别: debug|info|warning|error")
@click.pass_context
def main(ctx: click.Context, log_level: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level


if __name__ == "__main__":
    main()
