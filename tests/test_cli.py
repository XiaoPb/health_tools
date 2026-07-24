"""CLI 命令测试。"""

from click.testing import CliRunner

from health_tools.cli import main


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
