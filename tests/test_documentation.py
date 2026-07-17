import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click

from health_tools.cli import PRIMARY_COMMANDS, main


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
SKILL_DIR = ROOT / ".agents" / "skills" / "use-ghealth-tool"


def _command_options(command_name: str) -> set[str]:
    context = click.Context(main)
    command = main.get_command(context, command_name)
    assert command is not None

    options = set()
    for parameter in command.params:
        if not isinstance(parameter, click.Option) or parameter.hidden:
            continue
        for option in [*parameter.opts, *parameter.secondary_opts]:
            if option.startswith("--"):
                options.add(option)
    return options


def test_every_primary_command_has_complete_reference_page():
    assert len(PRIMARY_COMMANDS) == 13

    for command_name in PRIMARY_COMMANDS:
        doc_path = DOCS_DIR / f"cmd_{command_name}.md"
        assert doc_path.is_file(), f"缺少命令文档: {doc_path.name}"
        content = doc_path.read_text(encoding="utf-8")
        missing = sorted(
            option for option in _command_options(command_name) if option not in content
        )
        assert not missing, f"{doc_path.name} 缺少选项: {', '.join(missing)}"


def test_command_indexes_cover_all_primary_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    command_index = (DOCS_DIR / "commands.md").read_text(encoding="utf-8")

    assert "--version" in readme
    assert "--log-level" in command_index
    for command_name in PRIMARY_COMMANDS:
        doc_name = f"cmd_{command_name}.md"
        assert doc_name in readme
        assert doc_name in command_index


def test_current_documentation_has_no_broken_local_links():
    markdown_files = [ROOT / "README.md", ROOT / "CHANGELOG.md", *DOCS_DIR.glob("*.md")]
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    broken = []

    for markdown_file in markdown_files:
        content = markdown_file.read_text(encoding="utf-8")
        for target in link_pattern.findall(content):
            path_text = target.split("#", 1)[0]
            if not path_text or "://" in path_text or path_text.startswith("mailto:"):
                continue
            target_path = (markdown_file.parent / path_text).resolve()
            if not target_path.exists():
                broken.append(f"{markdown_file.relative_to(ROOT)} -> {target}")

    assert not broken, "失效的本地文档链接:\n" + "\n".join(broken)


def test_environment_inspector_reports_workspace_install():
    script = SKILL_DIR / "scripts" / "inspect_environment.py"
    env = os.environ.copy()
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [source_path, env.get("PYTHONPATH")]))

    result = subprocess.run(
        [sys.executable, str(script), "--json"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["uses_workspace_source"] is True
    assert Path(report["module_path"]).is_relative_to(ROOT / "src" / "health_tools")
    assert report["cli_path"]
    assert report["package_version"]
    assert report["package_version"] in report["cli_version"]


def test_api_usage_contract_example_executes():
    content = (DOCS_DIR / "api_usage.md").read_text(encoding="utf-8")
    marker = "<!-- api-contract-example -->"
    example = content.split(marker, 1)[1].split("```python", 1)[1].split("```", 1)[0]

    namespace = {}
    exec(example, namespace)

    assert namespace["rule_list_request"].rule_type is None
    assert namespace["config_request"].action.value == "replace"
    assert namespace["offline_request"].chip_name == "gh3036"
