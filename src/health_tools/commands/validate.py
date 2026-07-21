"""验证YAML规则文件格式和内容"""

from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.command()
@click.argument("rule_file", required=True)
@click.option("--strict", is_flag=True, help="严格模式验证")
@click.pass_context
def validate_cmd(ctx: click.Context, rule_file: str, strict: bool) -> None:
    """验证YAML规则文件格式和内容"""
    from health_tools.api import ValidateRequest, run_validate
    from health_tools.commands.api_support import CliExecution, invoke_api

    with CliExecution(console) as context:
        result = invoke_api(
            lambda: run_validate(ValidateRequest(Path(rule_file), strict=strict), context=context)
        )
    if not result.valid:
        raise click.ClickException("规则验证失败: " + "; ".join(result.errors))
    console.print(f"[green]OK[/green] 规则文件验证通过: {rule_file}")
    return
