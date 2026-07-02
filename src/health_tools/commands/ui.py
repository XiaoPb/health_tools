"""启动可视化界面"""

import subprocess
import sys

import click
from rich.console import Console

console = Console()


@click.command()
@click.option("--port", default=8501, type=int, help="端口号")
def ui_cmd(port):
    """启动可视化界面 (需要安装 UI 依赖: pip install ghealth-tools[ui])"""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        console.print("[red]需要安装 UI 依赖: pip install ghealth-tools[ui][/red]")
        raise SystemExit(1)

    from health_tools.ui import get_app_path

    app_path = get_app_path()
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        app_path,
        f"--server.port={port}",
        "--server.headless=false",
    ]
    subprocess.run(cmd)
