from pathlib import Path

import pytest

from health_tools.api import (
    AnalyzeRequest,
    BatchResult,
    CallbackError,
    ClassifyRequest,
    ConfigAction,
    ConfigRequest,
    ConfigResult,
    EvaluateRequest,
    ExecutionContext,
    ItemResult,
    ItemStatus,
    OfflineCatalogRequest,
    OfflineCatalogResult,
    OfflineRequest,
    OfflineResult,
    OfflineVersionInfo,
    OperationCancelled,
    ParseRequest,
    PlotRequest,
    ProgressEvent,
    RequestValidationError,
    RuleCatalogResult,
    RuleDocumentResult,
    RuleInfo,
    RuleListRequest,
    RuleReadRequest,
    RuleSaveRequest,
    RuleSource,
    RuleType,
    RuleVariantInfo,
    run_analyze,
    run_classify,
    run_evaluate,
    run_info,
    run_list_rules,
    run_offline,
    run_offline_catalog,
    run_plot,
    run_read_rule,
    run_save_rule,
)


def test_batch_result_exposes_status_counts():
    result = BatchResult(
        operation="parse",
        items=(
            ItemResult(ItemStatus.OK, "a.log"),
            ItemResult(ItemStatus.SKIP, "b.log"),
            ItemResult(ItemStatus.FAIL, "c.log"),
        ),
    )

    assert result.ok_count == 1
    assert result.skip_count == 1
    assert result.warn_count == 0
    assert result.fail_count == 1


def test_execution_context_emits_progress_and_checks_cancellation():
    events = []
    context = ExecutionContext(on_progress=events.append, is_cancelled=lambda: True)
    event = ProgressEvent("parse", "files", 0, 2, "开始")

    context.emit(event)
    with pytest.raises(OperationCancelled) as exc_info:
        context.check_cancelled("files", BatchResult("parse"))

    assert events == [event]
    assert exc_info.value.stage == "files"
    assert isinstance(exc_info.value.partial_result, BatchResult)


def test_execution_context_wraps_callback_errors():
    def fail(_event):
        raise RuntimeError("boom")

    context = ExecutionContext(on_progress=fail)
    with pytest.raises(CallbackError, match="进度回调执行失败"):
        context.emit(ProgressEvent("parse", "files", 0, 1))


def test_request_models_are_immutable():
    request = ParseRequest(Path("input.log"), Path("output.csv"), chip_name="gh3036")

    with pytest.raises(Exception):
        request.chip_name = "gh3220"


def test_run_info_returns_structured_csv_data(tmp_path: Path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("value,label\n1,a\n2,b\n", encoding="utf-8")

    from health_tools.api import InfoRequest

    result = run_info(InfoRequest(csv_path, stats=True, schema=True, preview=1))

    assert result.kind == "csv"
    assert result.summary["rows"] == 2
    assert result.schema["value"]["non_null"] == 2
    assert result.preview == ({"value": 1, "label": "a"},)

    with pytest.raises(TypeError):
        result.summary["rows"] = 3


def test_rule_and_offline_catalog_models_are_immutable(tmp_path: Path):
    variant = RuleVariantInfo(RuleSource.BUILTIN, tmp_path / "sample.yaml", False, "rev")
    rule = RuleInfo(
        RuleType.PARSE,
        "sample.yaml",
        RuleSource.BUILTIN,
        variant.path,
        False,
        False,
        (variant,),
    )
    catalog = RuleCatalogResult([rule])
    document = RuleDocumentResult(rule, "version: 1\n", "rev")
    offline = OfflineCatalogResult([OfflineVersionInfo("gh3036", "basic", "v1", True, False)])

    assert catalog.rules == (rule,)
    assert document.source == "version: 1\n"
    assert offline.versions[0].category == "basic"
    with pytest.raises(Exception):
        catalog.rules = ()


def test_new_request_defaults_and_config_compatibility():
    assert RuleListRequest().rule_type is None
    assert RuleReadRequest(RuleType.CHIP, "gh3036.yaml").variant == RuleSource.EFFECTIVE
    assert RuleSaveRequest(RuleType.CHIP, "new.yaml", "chip: new\n").expected_revision is None
    assert OfflineCatalogRequest().chip_name is None

    request = ConfigRequest(ConfigAction.SHOW)
    result = ConfigResult(ConfigAction.SHOW, {"rules_dir": "rules"}, (), {})
    assert request.source is None
    assert request.expected_revision is None
    assert result.source == ""
    assert result.revision is None
    assert all(
        callable(function)
        for function in (run_list_rules, run_read_rule, run_save_rule, run_offline_catalog)
    )


@pytest.mark.parametrize(
    "request_model",
    [
        PlotRequest(Path("in"), Path("out")),
        ClassifyRequest(Path("in"), Path("out")),
        EvaluateRequest(Path("in"), Path("out")),
        OfflineRequest(),
        AnalyzeRequest(Path("in"), Path("out")),
    ],
)
def test_accuracy_request_defaults(request_model):
    assert request_model.accuracy_thresholds is None
    assert request_model.accuracy_inclusive is False


def test_parallel_request_defaults():
    assert PlotRequest(Path("in"), Path("out")).workers == 8
    assert OfflineRequest().workers == 8
    EvaluateRequest,
    OfflineRequest,


def test_offline_result_normalizes_logs_without_breaking_positional_arguments():
    batch = BatchResult("offline")

    legacy = OfflineResult(batch, Path("output"), ["v1"], ["report.csv"])
    with_logs = OfflineResult(batch, logs=["a.log"])

    assert legacy.output_dir == Path("output")
    assert legacy.versions == ("v1",)
    assert legacy.reports == (Path("report.csv"),)
    assert legacy.logs == ()
    assert with_logs.logs == (Path("a.log"),)


@pytest.mark.parametrize(
    "plot_request",
    [
        PlotRequest(Path("missing"), Path("out"), fft_start=1.0),
        PlotRequest(Path("missing"), Path("out"), fft_duration=2.0),
        PlotRequest(Path("missing"), Path("out"), fft_start=-1.0, fft_duration=2.0),
        PlotRequest(Path("missing"), Path("out"), fft_start=1.0, fft_duration=0.0),
    ],
)
def test_plot_rejects_invalid_fft_window_before_path_validation(plot_request):
    with pytest.raises(RequestValidationError, match="FFT"):
        run_plot(plot_request)


@pytest.mark.parametrize(
    ("operation", "request_model"),
    [
        (
            run_plot,
            PlotRequest(Path("missing"), Path("out"), accuracy_thresholds=(5.0, 0.0)),
        ),
        (
            run_classify,
            ClassifyRequest(Path("missing"), Path("out"), accuracy_thresholds=(5.0, 0.0)),
        ),
        (
            run_evaluate,
            EvaluateRequest(Path("missing"), Path("out"), accuracy_thresholds=(5.0, 0.0)),
        ),
        (
            run_offline,
            OfflineRequest(
                input_path=Path("missing"),
                output_path=Path("out"),
                accuracy_thresholds=(5.0, 0.0),
            ),
        ),
        (
            run_analyze,
            AnalyzeRequest(Path("missing"), Path("out"), accuracy_thresholds=(5.0, 0.0)),
        ),
    ],
)
def test_accuracy_operations_reject_invalid_thresholds_before_path_validation(
    operation, request_model
):
    with pytest.raises(RequestValidationError, match="有限正数"):
        operation(request_model)
