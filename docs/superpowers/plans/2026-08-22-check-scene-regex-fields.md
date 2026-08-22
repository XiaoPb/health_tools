# check 场景正则字段 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `check` 的 `scene_regex` 识别 `scene`、`name`、`hand` 并按约定输出报告列。

**Architecture:** 在 API 层集中完成正则匹配并把三元组传入 `FileCheckReport`，命令层只负责序列化报告列。可选命名组缺失时统一回退 `default`，不破坏旧规则。

**Tech Stack:** Python、dataclasses、`re`、pytest、CSV writer。

---

### Task 1: 正则字段解析

**Files:**
- Modify: `src/health_tools/api/check_operation.py`
- Test: `tests/test_acc_checker.py`

- [ ] 写测试覆盖带 `name`/`hand` 的正反斜杠路径、未匹配和仅 `scene` 规则。
- [ ] 运行测试确认新断言失败。
- [ ] 扩展解析 helper 并在 `check` 报告构造时传递字段。
- [ ] 运行该测试文件确认通过。

### Task 2: 报告模型与 CSV 列

**Files:**
- Modify: `src/health_tools/core/checker.py`
- Modify: `src/health_tools/commands/check.py`
- Test: `tests/test_check_sort.py`

- [ ] 增加报告字段和 CSV 列顺序断言。
- [ ] 运行测试确认失败。
- [ ] 实现字段默认值与序列化。
- [ ] 运行相关测试确认通过。

### Task 3: 全量验证与提交

- [ ] 运行 `pytest tests/test_acc_checker.py tests/test_check_sort.py`。
- [ ] 运行 `ruff check src/ tests/` 与 `black --check src/ tests/`。
- [ ] 提交明确文件列表，提交信息使用 `feat:` 并包含 Co-Authored-By。
