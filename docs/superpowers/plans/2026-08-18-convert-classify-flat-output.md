# Convert Classify 扁平分类输出 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 配置 `classify` 后，让 convert 的普通、默认和 split 分类结果直接写入输出根目录下的类别路径，不再保留源文件相对目录。

**Architecture:** 保留目录扫描阶段现有的 `destination` 计算，使未配置分类的 convert 行为不变；调用 `_convert_one` 时额外显式传入统一的分类输出根目录。`_convert_one` 仅在分类器存在时使用该根目录拼接 `category/filename`，源相对路径仍通过 `input_root` 提供给 `path.regex` 做字段提取。

**Tech Stack:** Python 3.9+、pathlib、pandas、pytest、Black、Ruff、mypy

---

## 文件结构

- Modify: `tests/test_api_operations.py`：增加和调整 convert 内联 classify 的输出路径回归测试。
- Modify: `src/health_tools/api/file_operations.py`：向单文件转换流程传递分类输出根目录，并统一分类写出路径。
- Modify: `docs/cmd_convert.md`：说明分类路径取代源相对目录。
- Modify: `docs/rules.md`：说明 `path.regex` 的相对路径只用于提取变量，不参与分类输出布局。

### Task 1: 用回归测试定义分类后的扁平输出语义

**Files:**
- Modify: `tests/test_api_operations.py:425`
- Modify: `tests/test_api_operations.py:527`
- Modify: `tests/test_api_operations.py:629`
- Modify: `tests/test_api_operations.py:656`

- [ ] **Step 1: 修改现有目录分类测试，要求分类目录直接位于输出根目录**

把 `test_run_convert_directory_with_classify_preserves_subdirs` 改名并将断言替换为：

```python
def test_run_convert_directory_with_classify_discards_relative_subdirs(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text("frame,value\n0,5\n1,6\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify.yaml"
    rule.parent.mkdir()
    rule.write_text(_CLASSIFY_RULE, encoding="utf-8")
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    assert result.ok_count == 1
    assert result.artifacts == (output / "high" / "a.csv",)
    assert (output / "high" / "a.csv").exists()
    assert not (output / "sub" / "high" / "a.csv").exists()
```

- [ ] **Step 2: 修改 path.regex 测试，复现 name/scene/side 目录并确认只输出类别路径**

用下面的测试替换 `test_run_convert_directory_classify_path_regex`：

```python
def test_run_convert_directory_classify_path_regex_uses_path_only_for_fields(tmp_path: Path):
    input_dir = tmp_path / "input"
    source_dir = input_dir / "Abigail" / "Abigail_操场跑_左手"
    source_dir.mkdir(parents=True)
    (source_dir / "data.csv").write_text("value\n1\n2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_path.yaml"
    rule.parent.mkdir()
    rule.write_text(
        "version: '1.0'\n"
        "column_mapping:\n  value: VALUE\n"
        "classify:\n"
        "  path:\n"
        "    regex: '(?P<name>[^/\\\\]+)[/\\\\](?P=name)_(?P<scene>[^_]+)_"
        "(?P<side>左手|右手)[/\\\\][^/\\\\]+\\.csv'\n"
        "  structure:\n"
        "    placeholder: ''\n"
        "  rules:\n"
        "    - target: '{scene}'\n"
        "  rename: '{name}_{scene}_{side}_{filename}'\n"
        "  default: unclassified\n",
        encoding="utf-8",
    )
    output = tmp_path / "data_gh3036"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    expected = output / "操场跑" / "Abigail_操场跑_左手_data.csv"
    assert result.ok_count == 1
    assert result.artifacts == (expected,)
    assert expected.exists()
    assert not (output / "Abigail").exists()
```

- [ ] **Step 3: 增加目录输入未命中分类时的扁平 default 测试**

在 `test_run_convert_classify_no_match_uses_default` 后增加：

```python
def test_run_convert_directory_classify_default_discards_relative_subdirs(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text("frame,value\n0,1\n1,2\n", encoding="utf-8")
    rule = tmp_path / "convert" / "classify_default.yaml"
    rule.parent.mkdir()
    rule.write_text(
        _CLASSIFY_RULE.replace("'val_median >= 3'", "'val_median >= 999'").replace(
            "'val_median < 3'", "'val_median < 0'"
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    expected = output / "unclassified" / "a.csv"
    assert result.ok_count == 1
    assert result.artifacts == (expected,)
    assert expected.exists()
    assert not (output / "sub" / "unclassified" / "a.csv").exists()
```

- [ ] **Step 4: 增加目录输入 split 后各分段直接进入类别目录的测试**

在现有 split/classify 测试附近增加：

```python
def test_run_convert_directory_split_with_classify_discards_relative_subdirs(tmp_path: Path):
    input_dir = tmp_path / "input"
    (input_dir / "sub").mkdir(parents=True)
    (input_dir / "sub" / "a.csv").write_text(
        "frame,value\n0,1\n1,2\n2,3\n3,4\n", encoding="utf-8"
    )
    rule = tmp_path / "convert" / "split_classify.yaml"
    rule.parent.mkdir()
    rule.write_text(
        _CLASSIFY_RULE.replace("classify:", "split:\n  by_size: 2\nclassify:", 1),
        encoding="utf-8",
    )
    output = tmp_path / "output"

    result = run_convert(ConvertRequest(input_dir, output, rule_file=str(rule)))

    expected = (output / "low" / "a_1.csv", output / "high" / "a_2.csv")
    assert result.ok_count == 1
    assert result.artifacts == expected
    assert all(path.exists() for path in expected)
    assert not (output / "sub").exists()
```

- [ ] **Step 5: 运行新回归测试，确认当前实现失败且未分类行为仍通过**

Run:

```bash
pytest tests/test_api_operations.py::test_run_convert_directory_with_classify_discards_relative_subdirs tests/test_api_operations.py::test_run_convert_directory_classify_path_regex_uses_path_only_for_fields tests/test_api_operations.py::test_run_convert_directory_classify_default_discards_relative_subdirs tests/test_api_operations.py::test_run_convert_directory_split_with_classify_discards_relative_subdirs -v
```

Expected: 4 个测试 FAIL；实际文件仍位于原相对目录下。

Run:

```bash
pytest tests/test_api_operations.py::test_run_convert_directory_with_rule_split_keeps_relative_paths -v
```

Expected: PASS，证明未配置 `classify` 时仍应保留相对目录。

### Task 2: 让分类写出使用统一输出根目录

**Files:**
- Modify: `src/health_tools/api/file_operations.py:82-169`
- Modify: `src/health_tools/api/file_operations.py:292-416`
- Test: `tests/test_api_operations.py`

- [ ] **Step 1: 为 `_convert_one` 增加必传的分类输出根目录参数**

将函数签名改为：

```python
def _convert_one(
    source,
    destination,
    converter,
    input_config,
    output_config,
    *,
    output_root,
    input_root=None,
) -> ItemResult:
```

这里的 `destination` 仍表示未分类时的完整候选输出文件；`output_root` 只用于配置了
`classify` 的写出分支。

- [ ] **Step 2: 普通和 split 分类分支都从 `output_root` 拼接类别路径**

把 split 分支中的：

```python
chunk_path = destination.parent / category / _output_name(index)
```

替换为：

```python
chunk_path = output_root / category / _output_name(index)
```

把普通分支中的：

```python
write_path = destination.parent / category / _output_name() if category else destination
```

替换为：

```python
write_path = output_root / category / _output_name() if category else destination
```

分类器为空时仍使用 `destination`，因此普通目录转换和未分类 split 的相对路径行为不变。

- [ ] **Step 3: 在单文件和目录调用点显式传入正确输出根目录**

单文件调用改为：

```python
item = _convert_one(
    path,
    destination,
    converter,
    input_config,
    output_config,
    output_root=destination.parent,
)
```

目录调用改为：

```python
item = _convert_one(
    path,
    output_file,
    converter,
    input_config,
    output_config,
    output_root=destination,
    input_root=source,
)
```

不要修改 `output_file = destination / path.relative_to(source)`；它仍服务于未配置分类的转换。
合并模式使用独立的 `_merge_path`，没有源相对路径问题，本任务不修改该分支。

- [ ] **Step 4: 运行分类路径和兼容性测试**

Run:

```bash
pytest tests/test_api_operations.py -k "convert and (classify or rule_split_keeps_relative_paths)" -v
```

Expected: PASS；包含普通分类、path.regex、default、split、rename、合并模式以及未分类相对路径测试。

- [ ] **Step 5: 运行格式与静态检查**

Run:

```bash
black --check src/health_tools/api/file_operations.py tests/test_api_operations.py
ruff check src/health_tools/api/file_operations.py tests/test_api_operations.py
mypy src/health_tools/api/file_operations.py
```

Expected: 三条命令均以退出码 0 完成。

- [ ] **Step 6: 提交实现与测试**

```bash
git add src/health_tools/api/file_operations.py tests/test_api_operations.py
git commit -m "fix: 分类转换不保留原相对路径" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 3: 更新 convert 分类输出文档

**Files:**
- Modify: `docs/cmd_convert.md:134-141`
- Modify: `docs/rules.md:534-558`

- [ ] **Step 1: 在命令页明确分类路径替代源相对目录**

在 `docs/cmd_convert.md` 的“规则 classify”段落中，将说明整理为：

```markdown
规则文件配置 `classify` 时，convert 在转换完成（含 `split` 分段）后对每个转换结果执行分类，
写入 `{输出目录}/{类别路径}/{输出文件名}`。目录输入配置分类后，类别路径会取代源文件的
相对目录；源相对路径仍可供 `path.regex` 提取变量，但不参与输出路径拼接。块内支持完整
classify 规则参数：`filename`/`path`/`data_columns`/`structure`/`rules`（简单分类，含文件名
重分类）、`extract`/`classify`（条件分类）、`default`、`rename`（重命名输出文件名）。
`extract` 的列参数使用转换后的目标列名（如 `REF_RESULT5`）；未命中任何条件时输出到
`classify.default` 目录（默认 `unclassified`），保证转换产物不丢失。
```

- [ ] **Step 2: 在规则文档明确 path.regex 与输出布局的职责边界**

在 `docs/rules.md` 的 classify 说明中，将相关段落整理为：

```markdown
与 classify 命令的关键区别：`extract` 直接作用于**转换后的内存 DataFrame**，其中基于列参数
的函数（如 `calculate_median`）作用于转换后的 DataFrame，`params.column` 必须使用转换后的
目标列名（如 `REF_RESULT5`）；基于文件路径的函数（`params.patterns`）仍基于源文件路径。
`filename`/`path` 仍基于源文件路径，目录模式下 `path.regex` 匹配相对输入目录的路径并提取
变量。配置 `classify` 后，该源相对路径不参与输出布局，转换结果直接写入
`{输出目录}/{类别路径}/{输出文件名}`。分类条件未命中时直接写入输出根目录下的 `{default}`
目录，保证转换产物不丢失。`rename` 生成新的输出文件名（split 分段时追加 `_{序号}`）。
`split` 与 `classify` 可同时配置：先分割并逐段转换，再对每段独立分类。
```

- [ ] **Step 3: 检查文档格式和变更范围**

Run:

```bash
git diff --check
git diff -- docs/cmd_convert.md docs/rules.md
```

Expected: `git diff --check` 无输出；diff 只包含分类输出路径语义更新。

- [ ] **Step 4: 提交文档**

```bash
git add docs/cmd_convert.md docs/rules.md
git commit -m "docs: 说明分类转换输出路径" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

### Task 4: 完成工作区级验证

**Files:**
- Verify: `src/health_tools/api/file_operations.py`
- Verify: `tests/test_api_operations.py`
- Verify: `docs/cmd_convert.md`
- Verify: `docs/rules.md`

- [ ] **Step 1: 安装当前工作区及开发依赖**

Run:

```bash
pip install -e ".[dev]"
```

Expected: 安装成功，`ghealth-tools` 指向当前工作区。

- [ ] **Step 2: 确认测试导入的是当前工作区源码**

Run:

```bash
python -c "import health_tools; print(health_tools.__file__)"
```

Expected: 输出路径位于 `E:\Code\Python\health_tools\src\health_tools\__init__.py`。

- [ ] **Step 3: 运行全量质量检查**

Run:

```bash
pytest
black --check src/ tests/
ruff check src/ tests/
mypy src/
```

Expected: pytest 全部通过；Black、Ruff、mypy 均以退出码 0 完成。

- [ ] **Step 4: 核对提交和工作区状态**

Run:

```bash
git log -3 --oneline
git status --short
```

Expected: 最近提交包含设计文档、实现测试、用户文档三个提交；`git status --short` 无输出。
