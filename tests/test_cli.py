"""CLI 命令测试。"""

import click
import pytest
from click.testing import CliRunner

from health_tools.cli import main
from health_tools.commands.accuracy_options import accuracy_options
from health_tools.commands.plot import _parse_time_range


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "ghealth_tool" in result.output or "Usage" in result.output


def test_cli_help_lists_aliases_without_loading_commands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "parse (p)" in result.output
    assert "convert (cv)" in result.output


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0-10", (0.0, 10.0)), (" 1.5 - 2.5 ", (1.5, 2.5))],
)
def test_plot_time_range_parser_accepts_seconds(value, expected):
    assert _parse_time_range(value) == expected


@pytest.mark.parametrize("value", ["", "10", "10-5", "-1-5", "1-nan", "1-inf"])
def test_plot_time_range_parser_rejects_invalid_bounds(value):
    with pytest.raises(click.BadParameter, match="START-END"):
        _parse_time_range(value)


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "ghealth_tool" in result.output


def test_cli_parse_help():
    runner = CliRunner()
    result = runner.invoke(main, ["parse", "--help"])
    assert result.exit_code == 0


def test_cli_convert_help():
    runner = CliRunner()
    result = runner.invoke(main, ["convert", "--help"])
    assert result.exit_code == 0


def test_cli_classify_help():
    runner = CliRunner()
    result = runner.invoke(main, ["classify", "--help"])
    assert result.exit_code == 0
    assert "--dry-run" in result.output
    assert "--min-rows" in result.output
    assert "--min-size" in result.output
    assert "--conflict" in result.output


def test_cli_split_help():
    runner = CliRunner()
    result = runner.invoke(main, ["split", "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize("command", ["evaluate", "classify", "offline", "plot", "analyze"])
def test_accuracy_commands_expose_shared_options(command):
    result = CliRunner().invoke(main, [command, "--help"])

    assert result.exit_code == 0
    assert "--accuracy-thresholds" in result.output
    assert "--accuracy-inclusive" in result.output
    assert "--accuracy-strict" in result.output


@click.command()
@accuracy_options
def _accuracy_option_command(accuracy_thresholds, accuracy_inclusive):
    click.echo(f"{accuracy_thresholds}|{accuracy_inclusive}")


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--accuracy-thresholds", "5,10,15"], "(5.0, 10.0, 15.0)|False"),
        (
            ["--accuracy-thresholds", "3.5,6", "--accuracy-inclusive"],
            "(3.5, 6.0)|True",
        ),
    ],
)
def test_accuracy_options_parse_valid_values(args, expected):
    result = CliRunner().invoke(_accuracy_option_command, args)

    assert result.exit_code == 0
    assert result.output.strip() == expected


@pytest.mark.parametrize("value", ["", "5,0", "5,-1", "5,5", "5,nan", "5,inf"])
def test_accuracy_options_reject_invalid_values(value):
    result = CliRunner().invoke(
        _accuracy_option_command,
        ["--accuracy-thresholds", value],
    )

    assert result.exit_code != 0
    assert "Invalid value" in result.output
