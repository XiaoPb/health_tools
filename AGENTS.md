# AGENTS.md

本文件说明 AI 编码代理在本仓库中的长期约定。

## 开发与验证

```bash
pip install -e ".[dev]"       # 安装当前工作区及开发依赖
ghealth_tool --help            # 查看 CLI
pytest                         # 全量测试
pytest --cov=health_tools      # 覆盖率
black --check src/ tests/      # 格式检查
ruff check src/ tests/         # 静态检查
mypy src/                      # 类型检查
```

Python 3.9+。Black 与 Ruff 行宽均为 100。运行测试前用下面的命令确认没有误用其他目录的
已安装版本：

```bash
python -c "import health_tools; print(health_tools.__file__)"
```

如果 pytest 在初始化阶段出现 `pytestqt` 加载失败或 `QtCore` 的 DLL 异常（例如
`ImportError: DLL load failed while importing QtCore`），这通常是当前环境没有可用的 Qt
运行库，并非业务测试失败。先禁用 pytest 自动加载插件再运行测试：

```bash
# Linux/macOS
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest

# Windows PowerShell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
pytest
Remove-Item Env:PYTEST_DISABLE_PLUGIN_AUTOLOAD
```

禁用后仍会加载 pytest 自身和项目测试所需的基础插件；验证结果中应记录该环境处理方式。

## Git 工作流

任何代码或文档改动完成并验证后都必须提交：

```bash
git add <明确的文件列表>
git commit -m "docs: description" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

提交类型：`feat:` 新功能、`fix:` 修复、`refactor:` 重构、`docs:` 文档、`test:` 测试、
`chore:` 维护。不要跳过 Co-Authored-By，也不要使用 `git add .` 混入无关文件。

## 架构

入口为 `ghealth_tool` -> `src/health_tools/cli.py`。主要模块：

- `commands/`：Click 参数、校验、进度与汇总。
- `core/`：解析、转换、检查、绘图、评估、产测和离线跑库。
- `rules/`：规则加载、验证及内置 YAML。
- `models/`：chip、parse、convert、classify、evaluate 规则数据类。
- `utils/`：CSV、列展开、文件、并行、日志、准确度和报告工具。
- `ui/`：可选 Streamlit 页面与组件。

完整边界和数据流见 `docs/architecture.md`。

## 规则系统

规则分为 `chip`、`parse`、`classify`、`convert`、`evaluate` 五类。相对规则名优先查找
用户规则目录，再查找包内规则。列范围统一使用 `{start-end}`；转换规则中的 `[]` 保留为
字面量。字段与示例见 `docs/rules.md`。

## 文档要求

- 用户文本、注释和文档使用中文。
- 修改 CLI 选项时同步更新 `docs/cmd_<command>.md`。
- 修改规则字段时同步更新 `docs/rules.md` 和相应示例。
- README 与 `docs/commands.md` 负责导航，完整参数以命令页和 `--help` 为准。
- 面向 GHealth Tools 使用任务时，优先读取 `.agents/skills/use-ghealth-tool/SKILL.md`。
