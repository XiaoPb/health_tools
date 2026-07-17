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
    PlotRequest(Path("data.csv"), Path("plots"), plot_type="both", channels="red,ir")
)
factory = run_factory(FactoryRequest(Path("data"), chip_name="gh3036"))
evaluation = run_evaluate(
    EvaluateRequest(Path("results"), Path("reports"), eval_type="hr")
)

checked = run_check(CheckRequest(input_path=Path("data"), chip_name="gh3036"))
offline = run_offline(OfflineRequest(input_path=Path("data"), chip_name="gh3036"))

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
