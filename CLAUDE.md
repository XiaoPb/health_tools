# CLAUDE.md

本文件说明 Claude Code 在本仓库中的长期约定。

## 开发与验证

```bash
pip install -e ".[dev]"
ghealth_tool --help
pytest
pytest --cov=health_tools
black --check src/ tests/
ruff check src/ tests/
mypy src/
```

Python 3.9+，Black 与 Ruff 行宽为 100。测试前确认当前导入来自本工作区：

```bash
python -c "import health_tools; print(health_tools.__file__)"
```

## Git 工作流

任何代码或文档改动完成并验证后都必须提交：

```bash
git add <明确的文件列表>
git commit -m "docs: description" -m "Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

提交类型使用 `feat:`、`fix:`、`refactor:`、`docs:`、`test:`、`chore:`。不要使用
`git add .` 混入无关文件。

## 项目结构

入口为 `ghealth_tool` -> `src/health_tools/cli.py`：

- `commands/`：Click 命令和终端呈现。
- `core/`：数据处理业务逻辑。
- `rules/`：五类 YAML 规则加载与验证。
- `models/`：规则数据类。
- `utils/`：CSV、列展开、并行、报告和准确度工具。
- `ui/`：可选 Streamlit 界面。

详细架构见 `docs/architecture.md`，规则字段见 `docs/rules.md`，命令索引见
`docs/commands.md`。

## 实施约定

- 用户文本、注释和文档使用中文。
- 业务逻辑放在 `core/`，命令层只做参数、校验和呈现。
- 新行为先补测试；批量命令复用现有进度和汇总工具。
- 修改命令、规则或输出格式时同步更新对应文档。
- 使用 GHealth Tools 完成数据任务时读取 `.agents/skills/use-ghealth-tool/SKILL.md`。
