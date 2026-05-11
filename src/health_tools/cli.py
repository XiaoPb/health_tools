import click
from rich.console import Console

from health_tools import __version__
from health_tools.commands import parse, plot, classify, convert, info, validate, split, process

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="ghealth_tool")
@click.option("--log-level", default="info", help="日志级别: debug|info|warning|error")
@click.pass_context
def main(ctx: click.Context, log_level: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level


main.add_command(parse.parse_cmd, name="parse")
main.add_command(parse.parse_cmd, name="p")
main.add_command(plot.plot_cmd, name="plot")
main.add_command(plot.plot_cmd, name="pl")
main.add_command(classify.classify_cmd, name="classify")
main.add_command(classify.classify_cmd, name="cls")
main.add_command(convert.convert_cmd, name="convert")
main.add_command(convert.convert_cmd, name="cv")
main.add_command(info.info_cmd, name="info")
main.add_command(info.info_cmd, name="i")
main.add_command(validate.validate_cmd, name="validate")
main.add_command(validate.validate_cmd, name="val")
main.add_command(split.split_cmd, name="split")
main.add_command(process.process_cmd, name="process")


if __name__ == "__main__":
    main()
