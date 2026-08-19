# Python API 使用指南

安装包后直接从 `health_tools.api` 导入。API 是同步调用，适合脚本，也可以由独立 UI 放入
工作线程执行。

```python
from pathlib import Path

from health_tools.api import ParseRequest, run_parse

result = run_parse(
    ParseRequest(
        input_path=Path("raw.log"),
        output_path=Path("parsed.csv"),
        rule_file="gh3220.yaml",
    )
)
print(result.ok_count, result.artifacts)
```

## 进度、取消和错误

```python
from threading import Event

from health_tools.api import ExecutionContext, GHealthError, OperationCancelled

cancel_event = Event()

context = ExecutionContext(
    on_progress=lambda event: print(event.stage, event.completed, event.total),
    is_cancelled=cancel_event.is_set,
)

try:
    result = run_parse(
        ParseRequest(Path("logs"), Path("output"), rule_file="gh3220.yaml"),
        context=context,
    )
except OperationCancelled as exc:
    print("已取消", exc.stage, exc.partial_result)
except GHealthError as exc:
    print("任务失败", exc)
```

单文件错误位于 `result.items`，不会抛任务级异常：

```python
for item in result.items:
    if item.status != "OK":
        print(item.input, item.status, item.reason, item.detail)
```

## 全部能力

以下示例展示最小请求。请求字段与对应 CLI 的业务选项一致。

```python
from health_tools.api import (
    CheckRequest,
    ClassifyRequest,
    ConfigAction,
    ConfigRequest,
    ConvertRequest,
    EvaluateRequest,
    FactoryRequest,
    InfoRequest,
    OfflineRequest,
    PlotRequest,
    ProcessRequest,
    SplitRequest,
    ValidateRequest,
    run_check,
    run_classify,
    run_config,
    run_convert,
    run_evaluate,
    run_factory,
    run_info,
    run_offline,
    run_plot,
    run_process,
    run_split,
    run_validate,
)

info = run_info(InfoRequest(Path("data.csv"), schema=True, preview=5))
validation = run_validate(ValidateRequest(Path("rules/chip/custom.yaml"), strict=True))

converted = run_convert(
    ConvertRequest(Path("input.csv"), Path("output.csv"), rule_file="vendor.yaml")
)
classified = run_classify(
    ClassifyRequest(Path("data"), Path("classified"), rule_file="spo2_posture.yaml")
)
split = run_split(SplitRequest(Path("data.csv"), Path("split"), by_size=10000))
processed = run_process(ProcessRequest(Path("data"), Path("processed"), max_workers=4))

plots = run_plot(
    PlotRequest(
        Path("data.csv"),
        Path("plots"),
        plot_type="both",
        channels="red,ir",
        workers=8,
    )
)
factory = run_factory(FactoryRequest(Path("data"), chip_name="gh3036"))
evaluation = run_evaluate(
    EvaluateRequest(Path("results"), Path("reports"), eval_type="hr")
)

checked = run_check(CheckRequest(input_path=Path("data"), chip_name="gh3036"))
offline = run_offline(
    OfflineRequest(input_path=Path("data"), chip_name="gh3036", workers=8)
)

config = run_config(ConfigRequest(ConfigAction.SHOW))
```

## 配置操作

```python
run_config(ConfigRequest(ConfigAction.INIT))
run_config(ConfigRequest(ConfigAction.SET_RULES_DIR, value="D:/rules"))
run_config(ConfigRequest(ConfigAction.SET_OFFLINE_PATH, value="D:/offline_tools"))
run_config(ConfigRequest(ConfigAction.SET_OFFLINE_DEFAULT, value="gh3036=version_a"))
run_config(ConfigRequest(ConfigAction.SCAN_OFFLINE))
```

## 规则管理

规则管理 API 只接受规则类型和单个 YAML 文件名，不接受任意路径。列表会合并包内规则和当前
用户规则目录中的同名文件；用户版本优先生效，`variants` 保留两个来源供 UI 对照显示。

```python
from health_tools.api import (
    RuleListRequest,
    RuleReadRequest,
    RuleSaveRequest,
    RuleSource,
    RuleType,
    run_list_rules,
    run_read_rule,
    run_save_rule,
)

catalog = run_list_rules(RuleListRequest(RuleType.PARSE))
document = run_read_rule(
    RuleReadRequest(RuleType.PARSE, "default.yaml", RuleSource.EFFECTIVE)
)

# 编辑 document.source 后，携带读取时的 revision 保存。
saved = run_save_rule(
    RuleSaveRequest(
        RuleType.PARSE,
        "default.yaml",
        document.source,
        expected_revision=document.revision,
    )
)
print(saved.rule.path, saved.revision)
```

内置规则只读。保存内置规则时不会修改安装包，而是在当前用户规则目录中生成同名覆盖。
已有有效规则必须提供 `expected_revision`；只有全新名称允许省略。外部修改导致 revision 不匹配
时抛出 `RequestValidationError`，调用方应重新读取并让用户决定如何合并。

规则验证与保存支持 Parse 的单 pattern 和顶层 `patterns` 多 pattern 结构，也支持 Classify
的 `structure/rules`、`extract/classify` 和纯 `patterns` 关键词库。Parse 使用单捕获组时可
通过 `separator` 拆分到多个 columns，适合 UI 根据样本日志生成规则。

## 数据分析

```python
from pathlib import Path

from health_tools.api import AnalyzeRequest, run_analyze

result = run_analyze(
    AnalyzeRequest(
        input_path=Path("data"),
        output_path=Path("analysis"),
        analysis_type="hr",
        focus=("动态/**/*.csv",),
        report="all",
    )
)
print(result.conclusion_counts)
```

输入可以是原始 CSV 或已有 offline 结果目录。自动离线升级使用输出工作区中的副本；`AnalyzeResult` 返回报告、结构化明细、升级文件和结论计数。

## 可视化配置编辑

`ConfigAction.REPLACE` 用于保存 UI 中编辑的完整配置 YAML。配置文件已存在时必须携带 SHOW
返回的 revision；首次创建可以省略。

```python
shown = run_config(ConfigRequest(ConfigAction.SHOW))
updated_source = shown.source or "rules_dir: ~/.ghealth_tools/rules\n"
replaced = run_config(
    ConfigRequest(
        ConfigAction.REPLACE,
        source=updated_source,
        expected_revision=shown.revision,
    )
)
```

REPLACE 要求 YAML 根节点为映射，成功后原子替换配置文件并刷新进程内缓存。`source` 和
`expected_revision` 不能用于其他配置 action。

## 离线资源目录

UI 应通过目录 API 构建芯片、分类和版本选择器，不应调用 `core.offline.find_exe` 或解析
`ConfigResult.config` 中的内部结构。

```python
from health_tools.api import OfflineCatalogRequest, run_offline_catalog

all_versions = run_offline_catalog(OfflineCatalogRequest())
gh3036_versions = run_offline_catalog(OfflineCatalogRequest("gh3036"))
for version in gh3036_versions.versions:
    print(
        version.chip_name,
        version.category,
        version.version,
        version.is_default,
        version.exe_available,
    )
```

目录查询只读取当前配置和文件系统。需要重新扫描工具目录时，先调用
`run_config(ConfigRequest(ConfigAction.SCAN_OFFLINE))`。

设置离线工具目录时 API 会展开 `~` 和相对路径，并把绝对路径写入配置。历史配置中的空路径
或 `.` 按 `~/.ghealth_tools/offline_algorithm_tools` 迁移解释，避免 CLI 与 UI 因启动目录
不同而扫描不同位置。

<!-- api-contract-example -->
```python
from pathlib import Path

from health_tools.api import (
    ConfigAction,
    ConfigRequest,
    OfflineRequest,
    OfflineCatalogRequest,
    PlotRequest,
    RuleListRequest,
    RuleReadRequest,
    RuleSaveRequest,
    RuleSource,
    RuleType,
)

rule_list_request = RuleListRequest()
rule_read_request = RuleReadRequest(RuleType.CHIP, "gh3036.yaml", RuleSource.BUILTIN)
rule_save_request = RuleSaveRequest(RuleType.CHIP, "custom.yaml", "chip: custom\n")
config_request = ConfigRequest(ConfigAction.REPLACE, source="rules_dir: rules\n")
offline_request = OfflineCatalogRequest("gh3036")
plot_request = PlotRequest(Path("data"), Path("plots"), workers=8)
offline_run_request = OfflineRequest(
    input_path=Path("data"), chip_name="gh3036", workers=8
)
```

## 安全提示

分类默认复制文件。只有明确需要移动时才设置：

```python
run_classify(
    ClassifyRequest(Path("data"), Path("classified"), mode="move")
)
```

按检查报告分拣同样会移动源文件：

```python
run_check(
    CheckRequest(
        sort_report=True,
        report_path=Path("data/check_report.csv"),
        sort_output=Path("sorted"),
    )
)
```

正常离线跑库会把表头不匹配的 CSV 移到同级备份目录。只处理已有结果时设置
`no_run=True`，并确保输出目录已包含 `数据整理` 或版本子目录。
