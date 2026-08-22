"""GHealth Tools 公共 API 业务编排。"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple, TypeVar

import yaml

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import OperationError, RequestValidationError, RuleLoadError
from health_tools.api.models import (
    BatchResult,
    ConfigAction,
    ConfigRequest,
    ConfigResult,
    EvaluateRequest,
    InfoRequest,
    InfoResult,
    ItemResult,
    ItemStatus,
    ParseRequest,
    ProcessRequest,
    ProgressEvent,
    SplitRequest,
    ValidateRequest,
    ValidationResult,
)
from health_tools.utils.errors import REASON_NO_DATA, REASON_PROCESS_FAILED, normalize_reason

T = TypeVar("T")


def _context(context: Optional[ExecutionContext]) -> ExecutionContext:
    return context or ExecutionContext()


def _item(result: Any) -> ItemResult:
    try:
        status = ItemStatus(result.status)
    except ValueError:
        status = ItemStatus.FAIL
    return ItemResult(
        status=status,
        input=result.input,
        output=result.output,
        reason=result.reason,
        detail=result.detail,
        category=result.category,
        rows=result.rows,
    )


def _batch(
    operation: str, items: Sequence[ItemResult], artifacts: Iterable[Path] = ()
) -> BatchResult:
    return BatchResult(operation, tuple(items), tuple(dict.fromkeys(Path(p) for p in artifacts)))


def _events(
    operation: str,
    stage: str,
    values: Sequence[T],
    context: ExecutionContext,
    items: List[ItemResult],
) -> Iterable[Tuple[int, T]]:
    total = len(values)
    context.check_cancelled(stage, _batch(operation, items))
    context.emit(ProgressEvent(operation, stage, 0, total, "开始"))
    for index, value in enumerate(values, 1):
        context.check_cancelled(stage, _batch(operation, items))
        yield index, value
        context.emit(ProgressEvent(operation, stage, index, total, "完成", str(value)))
    context.check_cancelled(stage, _batch(operation, items))


def _load_rule(loader, value: str, kind: str):
    try:
        return loader(value)
    except Exception as exc:
        raise RuleLoadError(f"无法加载{kind}规则 {value}: {exc}") from exc


def _require_path(path: Path, label: str = "输入路径") -> Path:
    path = Path(path)
    if not path.exists():
        raise RequestValidationError(f"{label}不存在: {path}")
    return path


def run_info(request: InfoRequest, *, context: Optional[ExecutionContext] = None) -> InfoResult:
    """读取 CSV 或 YAML 的结构化信息。"""
    import pandas as pd
    import yaml

    ctx = _context(context)
    target = _require_path(request.target, "目标文件")
    if request.preview < 0:
        raise RequestValidationError("preview 不能小于 0")
    ctx.check_cancelled("read")
    ctx.emit(ProgressEvent("info", "read", 0, 1, "读取文件", str(target)))

    try:
        if target.suffix.lower() in {".yaml", ".yml"}:
            with target.open("r", encoding="utf-8") as handle:
                rule = yaml.safe_load(handle)
            if not isinstance(rule, dict):
                raise RequestValidationError("规则文件必须是字典结构")
            result = InfoResult(
                target=target,
                kind="rule",
                summary={"name": target.name, "fields": len(rule)},
                schema=rule,
            )
        elif target.suffix.lower() == ".csv":
            df = pd.read_csv(target)
            schema = {
                str(column): {"dtype": str(df[column].dtype), "non_null": int(df[column].count())}
                for column in df.columns
            }
            statistics = df.describe().to_dict() if request.stats else {}
            result = InfoResult(
                target=target,
                kind="csv",
                summary={
                    "name": target.name,
                    "rows": len(df),
                    "columns": len(df.columns),
                    "size_bytes": target.stat().st_size,
                },
                schema=schema if request.schema else {},
                preview=tuple(df.head(request.preview).to_dict(orient="records")),
                statistics=statistics,
            )
        else:
            raise RequestValidationError(f"不支持的文件类型: {target.suffix}")
    except (RequestValidationError, OperationError):
        raise
    except Exception as exc:
        raise OperationError(f"读取文件失败 {target}: {exc}") from exc

    ctx.emit(ProgressEvent("info", "read", 1, 1, "完成", str(target)))
    return result


def run_validate(
    request: ValidateRequest, *, context: Optional[ExecutionContext] = None
) -> ValidationResult:
    """验证 YAML 规则文件。"""
    from health_tools.rules.validator import RuleValidator

    ctx = _context(context)
    path = Path(request.rule_file)
    ctx.check_cancelled("validate")
    ctx.emit(ProgressEvent("validate", "validate", 0, 1, "验证规则", str(path)))
    errors = tuple(RuleValidator.validate_file(path, strict=request.strict))
    rule_type = RuleValidator._detect_rule_type(path)
    result = ValidationResult(path, not errors, rule_type, errors)
    ctx.emit(ProgressEvent("validate", "validate", 1, 1, "完成", str(path)))
    return result


def run_config(
    request: ConfigRequest, *, context: Optional[ExecutionContext] = None
) -> ConfigResult:
    """读取或修改 GHealth Tools 配置。"""
    from health_tools.config import (
        CONFIG_DIR,
        CONFIG_FILE,
        load_config,
        read_config_document,
        save_config,
    )

    ctx = _context(context)
    ctx.check_cancelled("config")
    ctx.emit(ProgressEvent("config", "config", 0, 1, "处理配置"))
    changed: List[Path] = []
    versions = {}

    if request.action == ConfigAction.REPLACE:
        if request.value is not None or request.force:
            raise RequestValidationError("REPLACE 不能与 value 或 force 同时使用")
        if request.source is None:
            raise RequestValidationError("REPLACE 需要 source")
        if not isinstance(request.source, str):
            raise RequestValidationError("配置 source 必须是字符串")
    elif request.source is not None or request.expected_revision is not None:
        raise RequestValidationError("source 和 expected_revision 仅适用于 REPLACE")

    if request.action == ConfigAction.INIT:
        from health_tools.config import init_config_dir, sync_builtin_rules

        init_config_dir()
        sync_builtin_rules(force=request.force)
        changed.extend([CONFIG_DIR, CONFIG_FILE])
    elif request.action == ConfigAction.SHOW:
        pass
    elif request.action == ConfigAction.SET_RULES_DIR:
        if not request.value:
            raise RequestValidationError("设置规则目录需要 value")
        config = dict(load_config())
        config["rules_dir"] = request.value
        save_config(config)
        changed.append(CONFIG_FILE)
    elif request.action == ConfigAction.SET_OFFLINE_PATH:
        from health_tools.core.offline import (
            merge_scanned_versions,
            save_offline_config,
            scan_versions,
        )

        if not request.value:
            raise RequestValidationError("设置离线工具目录需要 value")
        tools_path = _require_path(Path(request.value).expanduser().resolve(), "离线工具目录")
        config = load_config()
        versions = merge_scanned_versions(
            scan_versions(tools_path), config.get("offline_versions", {})
        )
        save_offline_config(tools_path, versions)
        changed.append(CONFIG_FILE)
    elif request.action == ConfigAction.SET_OFFLINE_DEFAULT:
        if not request.value or "=" not in request.value:
            raise RequestValidationError("默认版本格式应为 chip=version")
        chip, version = request.value.split("=", 1)
        config = dict(load_config())
        versions = config.get("offline_versions", {})
        if chip not in versions:
            raise RequestValidationError(f"未找到芯片 {chip} 的版本信息")
        categories = versions[chip].get("versions", {})
        category = None
        available: List[str] = []
        if isinstance(categories, dict):
            for name, entries in categories.items():
                available.extend(entries)
                if version in entries:
                    category = name
        elif isinstance(categories, list):
            available = categories
            category = "exclusive"
        if version not in available:
            raise RequestValidationError(f"版本 {version} 不在可用列表中")
        versions[chip]["default"] = version
        versions[chip]["default_category"] = category
        config["offline_versions"] = versions
        save_config(config)
        changed.append(CONFIG_FILE)
    elif request.action == ConfigAction.SCAN_OFFLINE:
        from health_tools.core.offline import (
            get_offline_config,
            merge_scanned_versions,
            save_offline_config,
            scan_versions,
        )

        cfg = get_offline_config()
        if not cfg.tools_path.exists():
            raise RequestValidationError(f"离线工具路径不存在: {cfg.tools_path}")
        config = load_config()
        versions = merge_scanned_versions(
            scan_versions(cfg.tools_path), config.get("offline_versions", {})
        )
        save_offline_config(cfg.tools_path, versions)
        changed.append(CONFIG_FILE)
    elif request.action == ConfigAction.ADD_RULE:
        if not request.value:
            raise RequestValidationError("添加规则需要源文件路径")
        if request.rule_type is None:
            raise RequestValidationError("添加规则需要指定规则类型")
        if request.rule_type.value not in {
            "chip",
            "parse",
            "classify",
            "convert",
            "evaluate",
            "analysis",
            "check",
        }:
            raise RequestValidationError(f"不支持添加 {request.rule_type.value} 规则")
        source_path = Path(request.value).expanduser().resolve()
        if not source_path.is_file():
            raise RequestValidationError(f"规则文件不存在: {source_path}")
        if source_path.suffix.lower() not in {".yaml", ".yml"}:
            raise RequestValidationError("规则文件必须是 .yaml 或 .yml")
        try:
            with source_path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise RequestValidationError(f"规则文件读取失败: {exc}") from exc
        from health_tools.rules.validator import RuleValidator

        errors = RuleValidator.validate(document, request.rule_type.value)
        if errors:
            raise RequestValidationError("规则校验失败: " + "; ".join(errors))
        config = load_config()
        from health_tools.config import DEFAULT_RULES_DIR

        rules_dir = Path(config.get("rules_dir", str(DEFAULT_RULES_DIR))).expanduser()
        destination = rules_dir / request.rule_type.value / source_path.name
        if destination.exists() and not request.force:
            raise RequestValidationError(f"规则文件已存在: {destination}，如需覆盖请使用 --force")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        except OSError as exc:
            raise OperationError(f"复制规则文件失败: {exc}") from exc
        changed.append(destination)
    elif request.action == ConfigAction.REPLACE:
        from health_tools.config import ConfigRevisionConflict, replace_config_document

        source = request.source
        if not isinstance(source, str):  # 已在通用请求校验中拦截
            raise RequestValidationError("配置 source 必须是字符串")
        try:
            document = yaml.safe_load(source)
        except yaml.YAMLError as exc:
            raise RequestValidationError(f"配置 YAML 解析失败: {exc}") from exc
        if not isinstance(document, dict):
            raise RequestValidationError("配置 YAML 根节点必须是映射")
        try:
            replace_config_document(source, document, request.expected_revision)
        except ConfigRevisionConflict as exc:
            raise RequestValidationError(
                f"配置 revision 冲突: expected={exc.expected}, current={exc.current}"
            ) from exc
        changed.append(CONFIG_FILE)
    else:  # pragma: no cover - Enum 已限制输入
        raise RequestValidationError(f"未知配置操作: {request.action}")

    config_snapshot = dict(load_config())
    if not versions:
        versions = config_snapshot.get("offline_versions", {})
    try:
        source, revision = read_config_document()
    except (OSError, UnicodeError) as exc:
        raise OperationError(f"读取配置文件失败: {exc}") from exc
    ctx.emit(ProgressEvent("config", "config", 1, 1, "完成"))
    return ConfigResult(
        request.action,
        config_snapshot,
        tuple(changed),
        versions,
        source=source,
        revision=revision,
    )


def run_parse(request: ParseRequest, *, context: Optional[ExecutionContext] = None) -> BatchResult:
    """按解析规则把日志转换为 CSV。"""
    from health_tools.core.parser import LogParser
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import write_csv

    ctx = _context(context)
    input_path = _require_path(request.input_path)
    if not request.rule_file and not request.chip_name:
        raise RequestValidationError("需要指定 rule_file 或 chip_name")

    chip_columns = None
    chip_rule = None
    if request.rule_file:
        rule = _load_rule(RuleLoader.load_parse_rule, request.rule_file, "解析")
        if rule.chip:
            chip_rule = _load_rule(RuleLoader.load_chip_rule, rule.chip, "芯片")
            chip_columns = chip_rule.columns
    else:
        assert request.chip_name is not None
        chip_rule = _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
        rule = chip_rule

    if request.dry_run:
        ctx.check_cancelled("validate")
        ctx.emit(ProgressEvent("parse", "validate", 0, 1, "验证规则"))
        ctx.emit(ProgressEvent("parse", "validate", 1, 1, "规则验证通过"))
        return BatchResult("parse")

    multi_mode = bool(getattr(rule, "patterns", None))
    output_path = Path(request.output_path)
    if input_path.is_file():
        files = [input_path]
    else:
        files = sorted([*input_path.rglob("*.log"), *input_path.rglob("*.txt")])
        if request.filter_name:
            files = [path for path in files if request.filter_name in path.name]
    if multi_mode or input_path.is_dir():
        output_path.mkdir(parents=True, exist_ok=True)

    items: List[ItemResult] = []
    artifacts: List[Path] = []
    for _, source in _events("parse", "files", files, ctx, items):
        try:
            parser = LogParser(rule, chip_columns=chip_columns)
            if multi_mode:
                frames = parser.parse_file_multi(source, request.encoding)
                outputs = []
                rows = 0
                for name, multi_frame in frames.items():
                    destination = output_path / f"{source.stem}_{name}.csv"
                    if chip_rule:
                        write_csv(
                            destination,
                            multi_frame,
                            chip_rule=chip_rule,
                            info=chip_rule.info,
                        )
                    else:
                        multi_frame.to_csv(destination, index=False)
                    outputs.append(destination)
                    artifacts.append(destination)
                    rows += len(multi_frame)
                if outputs:
                    items.append(
                        ItemResult(
                            ItemStatus.OK,
                            str(source),
                            ";".join(str(path) for path in outputs),
                            rows=rows,
                        )
                    )
                else:
                    items.append(
                        ItemResult(
                            ItemStatus.SKIP,
                            str(source),
                            str(output_path),
                            REASON_NO_DATA,
                            "未匹配到可解析记录",
                        )
                    )
            else:
                parsed_frame = parser.parse_file(source, request.encoding)
                destination = (
                    output_path if input_path.is_file() else output_path / f"{source.stem}.csv"
                )
                if parsed_frame is None or parsed_frame.empty:
                    items.append(
                        ItemResult(
                            ItemStatus.SKIP,
                            str(source),
                            str(destination),
                            REASON_NO_DATA,
                            "未匹配到可解析记录",
                        )
                    )
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if chip_rule:
                        write_csv(
                            destination,
                            parsed_frame,
                            chip_rule=chip_rule,
                            info=chip_rule.info,
                        )
                    else:
                        parsed_frame.to_csv(destination, index=False, sep=request.delimiter)
                    artifacts.append(destination)
                    items.append(
                        ItemResult(
                            ItemStatus.OK,
                            str(source),
                            str(destination),
                            rows=len(parsed_frame),
                        )
                    )
        except Exception as exc:
            from health_tools.utils.errors import classify_exception

            items.append(
                ItemResult(
                    ItemStatus.FAIL,
                    str(source),
                    str(output_path),
                    classify_exception(exc),
                    str(exc),
                )
            )
    return _batch("parse", items, artifacts)


def run_split(request: SplitRequest, *, context: Optional[ExecutionContext] = None) -> BatchResult:
    """分割单个 CSV 或目录中的 CSV。"""
    from health_tools.core.splitter import DataSplitter
    from health_tools.rules.loader import RuleLoader

    ctx = _context(context)
    source = _require_path(request.input_path)
    chip_rule = (
        _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
        if request.chip_name
        else None
    )
    splitter = DataSplitter(chip_rule)
    if source.is_file():
        files = [source]
    else:
        files = sorted(source.rglob("*.csv"))
        if request.filter_name:
            files = [path for path in files if request.filter_name in path.name]

    items: List[ItemResult] = []
    artifacts: List[Path] = []
    for _, path in _events("split", "files", files, ctx, items):
        destination = Path(request.output_path)
        if source.is_dir():
            destination = destination / path.relative_to(source).parent
        try:
            result = splitter.split_file_result(
                path,
                destination,
                by_column=request.by_column,
                column_value=request.column_value,
                by_size=request.by_size,
                by_time=request.by_time,
                time_column=request.time_column,
            )
        except Exception as exc:
            from health_tools.utils.reporting import result_from_exception

            result = result_from_exception(path, exc, output=destination)
        item = _item(result)
        items.append(item)
        if item.status == ItemStatus.OK:
            artifacts.extend(Path(value) for value in item.output.split(";") if value)
    return _batch("split", items, artifacts)


def run_process(
    request: ProcessRequest, *, context: Optional[ExecutionContext] = None
) -> BatchResult:
    """复制 CSV，或按帧列分割目录中的 CSV。"""
    from health_tools.core.processor import BatchProcessor
    from health_tools.rules.loader import RuleLoader

    ctx = _context(context)
    source = _require_path(request.input_path, "输入目录")
    if not source.is_dir():
        raise RequestValidationError(f"输入路径必须是目录: {source}")
    if request.max_workers < 1:
        raise RequestValidationError("max_workers 必须大于 0")
    chip_rule = (
        _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
        if request.chip_name
        else None
    )
    processor = BatchProcessor(chip_rule)
    files = sorted(source.rglob(request.pattern))
    if request.filter_name:
        files = [path for path in files if request.filter_name in path.name]
    output = Path(request.output_path)
    output.mkdir(parents=True, exist_ok=True)
    items: List[ItemResult] = []
    artifacts: List[Path] = []

    def process_one(path: Path) -> ItemResult:
        if request.frame_split:
            result = processor.splitter.split_file_result(
                path,
                output / path.stem,
                by_column=request.frame_column,
                column_value=0,
            )
            return _item(result)
        else:
            destination = output / path.relative_to(source)
            raw = processor.process_file(path, destination)
            if raw.get("success"):
                return ItemResult(
                    ItemStatus.OK,
                    str(path),
                    str(destination),
                    rows=int(raw.get("rows", 0) or 0),
                )
            return ItemResult(
                ItemStatus.FAIL,
                str(path),
                str(destination),
                normalize_reason(REASON_PROCESS_FAILED),
                str(raw.get("error") or ""),
            )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    total = len(files)
    ctx.check_cancelled("files", _batch("process", items))
    ctx.emit(ProgressEvent("process", "files", 0, total, "开始"))
    executor = ThreadPoolExecutor(max_workers=request.max_workers)
    futures = {executor.submit(process_one, path): path for path in files}
    try:
        for completed, future in enumerate(as_completed(futures), 1):
            ctx.check_cancelled("files", _batch("process", items, artifacts))
            path = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                from health_tools.utils.errors import classify_exception

                item = ItemResult(
                    ItemStatus.FAIL,
                    str(path),
                    reason=classify_exception(exc),
                    detail=str(exc),
                )
            items.append(item)
            if item.status == ItemStatus.OK:
                artifacts.extend(Path(value) for value in item.output.split(";") if value)
            ctx.emit(ProgressEvent("process", "files", completed, total, "完成", str(path)))
        ctx.check_cancelled("files", _batch("process", items, artifacts))
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    return _batch("process", items, artifacts)


def run_evaluate(
    request: EvaluateRequest, *, context: Optional[ExecutionContext] = None
) -> BatchResult:
    """批量评估心率或血氧结果。"""
    from health_tools.core.evaluator import BatchEvaluator
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.accuracy import normalize_accuracy_thresholds

    ctx = _context(context)
    try:
        accuracy_thresholds = normalize_accuracy_thresholds(request.accuracy_thresholds)
    except ValueError as exc:
        raise RequestValidationError(str(exc)) from exc
    source = _require_path(request.input_path, "输入目录")
    if request.eval_type not in {"hr", "spo2"}:
        raise RequestValidationError("eval_type 仅支持 hr 或 spo2")
    rule_name = request.rule_file or f"evaluate_{request.eval_type}.yaml"
    rule = _load_rule(RuleLoader.load_evaluate_rule, rule_name, "评估")
    if request.ref_column:
        rule.ref_column = request.ref_column
    if request.pred_column:
        rule.pred_column = request.pred_column
    if request.diff_threshold is not None:
        rule.anomaly["diff_threshold"] = request.diff_threshold
    if request.stale_minutes is not None:
        rule.anomaly["stale_minutes"] = request.stale_minutes
    chip_rule = (
        _load_rule(RuleLoader.load_chip_rule, request.chip, "芯片") if request.chip else None
    )
    evaluator = BatchEvaluator(
        rule,
        chip_rule,
        ref_column_col=request.ref_column_col,
        pred_column_col=request.pred_column_col,
        accuracy_thresholds=accuracy_thresholds,
        accuracy_inclusive=request.accuracy_inclusive,
    )
    ctx.check_cancelled("evaluate")
    ctx.emit(ProgressEvent("evaluate", "evaluate", 0, 1, "评估目录", str(source)))
    outputs = evaluator.evaluate_directory(
        source,
        Path(request.output_path),
        filter_name=request.filter_name,
        show_progress=False,
    )
    collector = getattr(evaluator, "last_collector", None)
    items = [_item(value) for value in collector.results] if collector is not None else []
    result = _batch("evaluate", items, outputs.values())
    ctx.check_cancelled("evaluate", result)
    ctx.emit(ProgressEvent("evaluate", "evaluate", 1, 1, "完成", str(source)))
    return result
