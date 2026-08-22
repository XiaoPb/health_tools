import json
import os
import re
import subprocess
import sys
from pathlib import Path

import click
import pytest

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
    assert len(PRIMARY_COMMANDS) == 14

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


def test_check_documentation_covers_rules_accuracy_and_sort_contract():
    command_doc = (DOCS_DIR / "cmd_check.md").read_text(encoding="utf-8")
    rules_doc = (DOCS_DIR / "rules.md").read_text(encoding="utf-8")
    skill_commands = (SKILL_DIR / "references" / "commands.md").read_text(encoding="utf-8")
    skill_workflows = (SKILL_DIR / "references" / "workflows.md").read_text(encoding="utf-8")

    assert "`-r/--rule`" in command_doc
    assert "`-r/--rule`" in rules_doc
    assert "`check -r/--rule`" in skill_commands
    assert "check -i data/ -r" in skill_workflows

    for keyword in (
        "主要异常项",
        "Online准确度",
        "Comp准确度",
        "online_below_comp",
        "frame_warning",
        "input",
        "sort_output",
        "workers",
        "verbose",
    ):
        assert keyword in command_doc or keyword in rules_doc

    assert "validate custom_rules/check/custom.yaml" in skill_workflows
    assert "accuracy.ref_column" in skill_workflows
    assert "accuracy.online_column" in skill_workflows
    assert "accuracy.comp_column" in skill_workflows
    assert "全为 0 时跳过" in skill_workflows
    assert "场景分类" in command_doc
    assert "主要异常项" in command_doc
    assert "准确度标定分类" in command_doc
    assert "准确度标定说明" in command_doc
    assert "文件相对路径" in command_doc
    assert "`accuracy.comp_column` 可以省略" in command_doc
    assert "读取既有 check 报告" in command_doc
    assert "不会在同一次调用中重新检查" in command_doc


def test_check_documentation_describes_bounded_parallel_scheduling():
    command_doc = (DOCS_DIR / "cmd_check.md").read_text(encoding="utf-8")

    for statement in (
        "文件检查线程最多为 32 个",
        "在途任务窗口最多为 `实际生效线程数 * 2`",
        "按输入顺序汇总报告",
        "取消操作会停止提交新文件",
        "不保证线性提速",
    ):
        assert statement in command_doc


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
    assert namespace["plot_request"].workers == 8
    assert namespace["offline_run_request"].workers == 8


@pytest.mark.parametrize("path", ["docs/cmd_offline.md", "docs/cmd_plot.md"])
def test_parallel_command_docs_include_workers(path: str):
    text = (ROOT / path).read_text(encoding="utf-8")

    assert "--workers" in text
    assert "最多 8" in text


def test_offline_doc_describes_parallel_scheduling_and_recovery():
    text = (DOCS_DIR / "cmd_offline.md").read_text(encoding="utf-8")

    for keyword in (
        "根目录 CSV",
        "一级子目录",
        "进入队列",
        "<输入目录名>_mv",
        "不同失败文件",
        "同一个失败文件",
        ".offline_tasks/<task-id>/raw",
        "--workers 1",
    ):
        assert keyword in text


def test_plot_doc_describes_parallel_units_and_output_conflicts():
    text = (DOCS_DIR / "cmd_plot.md").read_text(encoding="utf-8")

    for keyword in ("按 CSV", "PSD 文件组", "输出文件冲突", "--workers 1"):
        assert keyword in text


def test_architecture_and_api_docs_describe_parallel_workflows():
    architecture = (DOCS_DIR / "architecture.md").read_text(encoding="utf-8")
    api_usage = (DOCS_DIR / "api_usage.md").read_text(encoding="utf-8")

    for keyword in ("offline_parallel.py", "isolated raw outputs", "single-thread merge"):
        assert keyword in architecture
    assert 'PlotRequest(Path("data"), Path("plots"), workers=8)' in api_usage
    assert "OfflineRequest(" in api_usage
    assert "workers=8" in api_usage
