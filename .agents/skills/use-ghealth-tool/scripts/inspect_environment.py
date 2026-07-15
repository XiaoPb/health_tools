"""只读检查 GHealth Tools 的 Python 包与 CLI 是否来自当前工作区。"""

import argparse
import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _distribution_version() -> Optional[str]:
    try:
        return importlib.metadata.version("ghealth-tools")
    except importlib.metadata.PackageNotFoundError:
        return None


def _module_path() -> Optional[Path]:
    spec = importlib.util.find_spec("health_tools")
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).resolve()


def _cli_version(cli_path: Optional[str]) -> Optional[str]:
    if cli_path is None:
        return None
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output or None


def inspect_environment() -> Dict[str, object]:
    workspace_root = Path(__file__).resolve().parents[4]
    workspace_source = (workspace_root / "src" / "health_tools").resolve()
    workspace_present = (workspace_root / "pyproject.toml").is_file() and workspace_source.is_dir()
    module_path = _module_path()
    cli_path = shutil.which("ghealth_tool")
    package_version = _distribution_version()
    cli_version = _cli_version(cli_path)
    issues: List[str] = []

    if module_path is None:
        issues.append("未找到 health_tools Python 包")
    elif workspace_present and not _is_relative_to(module_path, workspace_source):
        issues.append("health_tools 未从当前工作区的 src 目录导入")

    if package_version is None:
        issues.append("未找到 ghealth-tools 安装元数据")
    if cli_path is None:
        issues.append("PATH 中未找到 ghealth_tool 命令")
    elif cli_version is None:
        issues.append("无法读取 ghealth_tool 版本")
    elif package_version and f"version {package_version}" not in cli_version:
        issues.append("ghealth_tool 与 Python 包版本不一致")

    return {
        "status": "ok" if not issues else "error",
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "workspace_root": str(workspace_root),
        "workspace_present": workspace_present,
        "workspace_source": str(workspace_source),
        "package_version": package_version,
        "module_path": str(module_path) if module_path else None,
        "uses_workspace_source": bool(
            module_path and workspace_present and _is_relative_to(module_path, workspace_source)
        ),
        "cli_path": cli_path,
        "cli_version": cli_version,
        "issues": issues,
    }


def _print_text(report: Dict[str, object]) -> None:
    labels = {
        "status": "状态",
        "python_executable": "Python",
        "python_version": "Python 版本",
        "workspace_root": "工作区",
        "package_version": "包版本",
        "module_path": "模块路径",
        "cli_path": "CLI 路径",
        "cli_version": "CLI 版本",
        "uses_workspace_source": "使用工作区源码",
    }
    for key, label in labels.items():
        print(f"{label}: {report.get(key)}")
    issues = report.get("issues", [])
    if issues:
        print("问题:")
        for issue in issues:
            print(f"- {issue}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="以 JSON 输出检查结果")
    args = parser.parse_args()
    report = inspect_environment()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
