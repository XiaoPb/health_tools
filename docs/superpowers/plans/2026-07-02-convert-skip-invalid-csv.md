# Convert 跳过无效 CSV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** convert 命令遇到不符合转换规则的 CSV 时跳过处理，不再生成空 CSV 文件。

**Architecture:** 在 `DataConverter` 中集中判断规则是否命中源列；命令层在转换结果无有效列时跳过写出文件。目录合并模式在合并前过滤不符合规则的文件，避免无效文件污染合并结果。

**Tech Stack:** Python 3.9+、pandas、click、pytest。

---

## File Structure

- Modify: `src/health_tools/core/converter.py` — 增加规则源列命中判断，并在无命中时返回无列结果。
- Modify: `src/health_tools/commands/convert.py` — 单文件/目录转换遇到无列结果时跳过写文件，合并模式只合并符合规则的文件。
- Modify: `tests/test_convert.py` — 增加转换器和命令层回归测试。

### Task 1: 转换器识别无效输入

**Files:**
- Modify: `src/health_tools/core/converter.py`
- Test: `tests/test_convert.py`

- [ ] **Step 1: Write the failing test**

```python
def test_converter_returns_no_columns_when_rule_sources_do_not_match():
    import pandas as pd

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)
    df = pd.DataFrame({"foo": [1], "bar": [2]})

    result = converter.convert(df)

    assert result.empty
    assert list(result.columns) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_convert.py::test_converter_returns_no_columns_when_rule_sources_do_not_match -v`
Expected: FAIL because the converter currently returns an empty DataFrame only by accident in some cases and still may fill chip columns later.

- [ ] **Step 3: Write minimal implementation**

```python
    def has_matching_columns(self, df: pd.DataFrame) -> bool:
        expected_columns = self._expected_source_columns()
        if not expected_columns:
            return True
        return any(col in df.columns for col in expected_columns)

    def _expected_source_columns(self) -> List[str]:
        if self.rule.column_mapping:
            return list(self.rule.column_mapping.keys())
        if self.rule.source_columns and self.rule.target_columns:
            return self.rule.source_columns
        return []
```

Add this guard immediately after `_merge_extra_source` in `convert`:

```python
        if not self.has_matching_columns(df):
            return pd.DataFrame()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_convert.py::test_converter_returns_no_columns_when_rule_sources_do_not_match -v`
Expected: PASS.

### Task 2: 单文件转换跳过写出

**Files:**
- Modify: `src/health_tools/commands/convert.py`
- Test: `tests/test_convert.py`

- [ ] **Step 1: Write the failing test**

```python
def test_convert_file_skips_output_when_rule_sources_do_not_match(tmp_path: Path):
    from health_tools.commands.convert import _convert_file

    input_file = tmp_path / "invalid.csv"
    output_file = tmp_path / "out.csv"
    input_file.write_text("foo,bar\n1,2\n", encoding="utf-8")

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)

    _convert_file(input_file, output_file, converter, None, None, verbose=False)

    assert not output_file.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_convert.py::test_convert_file_skips_output_when_rule_sources_do_not_match -v`
Expected: FAIL because `_convert_file` currently writes `out.csv`.

- [ ] **Step 3: Write minimal implementation**

```python
        result = converter.convert(df, source_file=input_file)
        if result.empty and len(result.columns) == 0:
            if verbose:
                console.print(f"[yellow]SKIP[/yellow] {input_file.name}: 不符合转换规则")
            return
        _write_output_csv(result, output_file, output_csv_config)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_convert.py::test_convert_file_skips_output_when_rule_sources_do_not_match -v`
Expected: PASS.

### Task 3: 合并模式过滤无效文件

**Files:**
- Modify: `src/health_tools/commands/convert.py`
- Test: `tests/test_convert.py`

- [ ] **Step 1: Write the failing test**

```python
def test_merge_and_convert_skips_files_that_do_not_match_rule(tmp_path: Path):
    from health_tools.commands.convert import _merge_and_convert

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "valid.csv").write_text("time,value\n1,10\n", encoding="utf-8")
    (input_dir / "invalid.csv").write_text("foo,bar\n9,99\n", encoding="utf-8")
    output_file = tmp_path / "merged.csv"

    rule = ConvertRule(column_mapping={"time": "TimeStamp", "value": "VALUE"})
    converter = DataConverter(rule)

    _merge_and_convert(input_dir, output_file, converter, None, None, None, None, verbose=False)

    import pandas as pd

    result = pd.read_csv(output_file)
    assert list(result.columns) == ["TimeStamp", "VALUE"]
    assert result.to_dict("records") == [{"TimeStamp": 1, "VALUE": 10}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_convert.py::test_merge_and_convert_skips_files_that_do_not_match_rule -v`
Expected: FAIL because the invalid file is currently included before conversion.

- [ ] **Step 3: Write minimal implementation**

```python
            df = _read_input_csv(file, input_csv_config)
            df = converter._merge_extra_source(df, file)
            if not converter.has_matching_columns(df):
                if verbose:
                    console.print(f"[yellow]SKIP[/yellow] {file.name}: 不符合转换规则")
                continue
            dfs.append(df)
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_convert.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-07-02-convert-skip-invalid-csv.md src/health_tools/core/converter.py src/health_tools/commands/convert.py tests/test_convert.py
git commit -m "fix: skip invalid csv during convert" -m "Co-Authored-By: Codex Opus 4.6 <noreply@anthropic.com>"
```

## Self-Review

- Spec coverage: 单文件、目录转换、合并转换都覆盖“无效 CSV 不生成文件/不参与转换”。
- Placeholder scan: 无 TBD、TODO、implement later。
- Type consistency: 新增方法 `has_matching_columns` 接收 `pd.DataFrame` 并返回 `bool`，命令层只依赖该公共判断。
