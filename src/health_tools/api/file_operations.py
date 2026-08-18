"""转换、分类、绘图和产测公共 API。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import List, Optional

from health_tools.api.context import ExecutionContext
from health_tools.api.errors import RequestValidationError
from health_tools.api.models import (
    BatchResult,
    ClassifyRequest,
    ConvertRequest,
    FactoryRequest,
    ItemResult,
    ItemStatus,
    PlotRequest,
    ProgressEvent,
)
from health_tools.api.operations import _batch, _context, _events, _load_rule, _require_path
from health_tools.utils.errors import (
    REASON_CONFLICT,
    REASON_DRY_RUN,
    REASON_NO_DATA,
    REASON_RULE_MISMATCH,
    REASON_TOO_FEW_ROWS,
    REASON_TOO_SMALL,
    classify_exception,
)


def _read_convert_csv(file_path: Path, csv_config: Optional[dict]):
    import pandas as pd

    if not csv_config:
        return pd.read_csv(file_path, on_bad_lines="skip")
    from health_tools.models.rules import ChipRule
    from health_tools.utils.csv_handler import CSVHandler

    handler = CSVHandler(ChipRule(chip="input", csv=csv_config, columns=[]))
    try:
        _, frame = handler.read(file_path, auto_detect_encoding=False)
        return frame
    except Exception:
        header_row = csv_config.get("header_row", 1) - 1
        data_start = csv_config.get("data_start_row", 2) - 1
        skip = list(range(header_row)) + list(range(header_row + 1, data_start))
        return pd.read_csv(file_path, header=0, skiprows=skip or None, on_bad_lines="skip")


def _write_convert_csv(frame, output_file: Path, csv_config: Optional[dict]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if not csv_config:
        frame.to_csv(output_file, index=False)
        return
    from health_tools.models.rules import ChipRule
    from health_tools.utils.csv_handler import CSVHandler

    handler = CSVHandler(ChipRule(chip="output", csv=csv_config, columns=[]))
    info = csv_config.get("info", "")
    handler.write(output_file, frame, info=info or None)


def _convert_classifier(converter):
    """规则配置 classify 时构建内存分类器，否则返回 None。"""
    if not converter.rule.classify:
        return None
    from health_tools.core.classifier import DataClassifier
    from health_tools.rules.loader import RuleLoader

    return DataClassifier(RuleLoader.build_classify_rule(converter.rule.classify))


def _classify_default(converter) -> str:
    """未命中分类时的默认目录名。"""
    default = converter.rule.classify.get("default")
    return default or "unclassified"


def _available_classify_path(path: Path) -> Path:
    """分类输出重名时追加递增序号，避免覆盖已有文件。"""
    if not path.exists():
        return path
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


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
    def _output_name(index=None) -> str:
        """输出文件名：classify 配置 rename 时用模板（先分类再取字段），否则沿用 destination。"""
        if classifier is not None and classifier.rule.rename:
            base = classifier.resolve_filename(source)
            stem, suffix = Path(base).stem, Path(base).suffix
        else:
            stem, suffix = destination.stem, destination.suffix
        if index is None:
            return f"{stem}{suffix}"
        return f"{stem}_{index}{suffix}"

    try:
        classifier = _convert_classifier(converter)
        default_category = _classify_default(converter)
        frame = _read_convert_csv(source, input_config)
        if not converter.has_matching_columns(frame):
            return ItemResult(
                ItemStatus.SKIP,
                str(source),
                str(destination),
                REASON_RULE_MISMATCH,
                "不符合转换规则",
            )
        if converter.rule.split:
            chunks = converter.convert_split(frame, source_file=source)
            if not chunks:
                return ItemResult(
                    ItemStatus.SKIP,
                    str(source),
                    str(destination),
                    REASON_RULE_MISMATCH,
                    "不符合转换规则",
                )
            outputs = []
            categories = set()
            for index, chunk in enumerate(chunks, 1):
                if classifier is not None:
                    category = (
                        classifier.classify_frame(chunk, source, input_root=input_root)
                        or default_category
                    )
                    chunk_path = _available_classify_path(
                        output_root / category / _output_name(index)
                    )
                    categories.add(category)
                else:
                    chunk_path = destination.parent / _output_name(index)
                _write_convert_csv(chunk, chunk_path, output_config)
                outputs.append(chunk_path)
            return ItemResult(
                ItemStatus.OK,
                str(source),
                ";".join(str(path) for path in outputs),
                category=categories.pop() if len(categories) == 1 else "",
                rows=sum(len(chunk) for chunk in chunks),
            )
        result = converter.convert(frame, source_file=source)
        if result.empty and len(result.columns) == 0:
            return ItemResult(
                ItemStatus.SKIP,
                str(source),
                str(destination),
                REASON_RULE_MISMATCH,
                "不符合转换规则",
            )
        category = ""
        if classifier is not None:
            category = (
                classifier.classify_frame(result, source, input_root=input_root) or default_category
            )
        write_path = (
            _available_classify_path(output_root / category / _output_name())
            if category
            else destination
        )
        _write_convert_csv(result, write_path, output_config)
        return ItemResult(
            ItemStatus.OK,
            str(source),
            str(write_path),
            category=category,
            rows=len(result),
        )
    except Exception as exc:
        return ItemResult(
            ItemStatus.FAIL,
            str(source),
            str(destination),
            classify_exception(exc),
            str(exc),
        )


def _generate_convert_template(chip_rule, output_path: Path, source_file: Optional[Path]) -> None:
    import pandas as pd
    import yaml

    source_columns: List[str] = []
    if source_file and source_file.is_file():
        try:
            source_columns = list(pd.read_csv(source_file, nrows=0).columns)
            if len(source_columns) == 1 or any(c.startswith("Version") for c in source_columns):
                source_columns = list(pd.read_csv(source_file, header=1, nrows=0).columns)
        except Exception:
            source_columns = []

    aliases = {"framecnt": "FRAME_ID", "frameid": "FRAME_ID", "hbaout": "ALGO_RESULT0"}

    def normalized(value: str) -> str:
        value = value.lower().strip().replace("_pa", "")
        return re.sub(r"[^a-z0-9]", "", value)

    index = {normalized(column): column for column in source_columns}
    for source_name, target_name in aliases.items():
        if source_name in index:
            index[normalized(target_name)] = index[source_name]
    mapping = {}
    matched = set()
    for target in chip_rule.columns:
        source = index.get(normalized(target))
        if source:
            mapping[source] = target
            matched.add(source)
    for source in source_columns:
        mapping.setdefault(source, "Unknown")
    if not source_columns:
        mapping = {column: column for column in chip_rule.columns}

    csv_config = {"header_row": 1, "data_start_row": 2, "delimiter": ","}
    if source_file and source_file.is_file():
        try:
            first_line = source_file.open("r", encoding="utf-8").readline().strip()
            if first_line and ("," not in first_line or first_line.startswith("Version")):
                csv_config = {
                    "info_row": 1,
                    "header_row": 2,
                    "data_start_row": 3,
                    "delimiter": ",",
                    "info": first_line,
                }
        except Exception:
            pass
    template = {
        "version": "1.0",
        "description": f"转换为{chip_rule.chip}格式",
        "target_chip": chip_rule.chip,
        "csv": csv_config,
        "column_mapping": mapping,
        "extra_source": {
            "suffix": ".txt",
            "csv": {"header_row": 1, "data_start_row": 2, "delimiter": ","},
            "align": {"left_on": "time", "right_on": "time"},
            "column_mapping": {"polar": "REF_RESULT0"},
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.dump(template, handle, default_flow_style=False, allow_unicode=True, sort_keys=False)
        handle.write("\n# forward_fill: []  # 前向填充列\n")
        handle.write("# expand_repeat: []  # 重复扩展列\n")
        handle.write("# split:  # 先分割再转换（by_column/by_size/by_time）\n")
        handle.write("# classify:  # 转换后分类（完整 classify 规则参数）\n")


def _write_align_report(converter, output_dir: Path) -> Optional[Path]:
    errors = getattr(converter, "extra_source_align_errors", [])
    if not errors:
        return None
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "extra_source_align_errors.csv"
    pd.DataFrame(errors).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def run_convert(
    request: ConvertRequest, *, context: Optional[ExecutionContext] = None
) -> BatchResult:
    """按转换规则转换 CSV。"""
    import pandas as pd

    from health_tools.core.converter import DataConverter
    from health_tools.rules.loader import RuleLoader

    ctx = _context(context)
    if request.init_rule:
        if not request.chip_name:
            raise RequestValidationError("init_rule 需要 chip_name")
        destination = request.output_path or Path(f"convert_{request.chip_name}.yaml")
        chip_rule = _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
        _generate_convert_template(chip_rule, destination, request.input_path)
        ctx.emit(ProgressEvent("convert", "template", 1, 1, "模板已生成", str(destination)))
        return BatchResult("convert", artifacts=(destination,))
    if request.input_path is None or request.output_path is None:
        raise RequestValidationError("需要指定 input_path 和 output_path")
    if not request.rule_file:
        raise RequestValidationError("需要指定 rule_file")

    source = _require_path(request.input_path)
    rule = _load_rule(RuleLoader.load_convert_rule, request.rule_file, "转换")
    chip_rule = None
    if rule.target_chip:
        chip_rule = _load_rule(RuleLoader.load_chip_rule, rule.target_chip, "芯片")
    elif request.chip_name:
        chip_rule = _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
    converter = DataConverter(rule, chip_columns=chip_rule.columns if chip_rule else None)
    input_config = rule.csv or None
    output_config = chip_rule.csv if chip_rule else None
    destination = Path(request.output_path)
    items: List[ItemResult] = []
    artifacts: List[Path] = []

    if source.is_file():
        for _, path in _events("convert", "files", [source], ctx, items):
            item = _convert_one(
                path,
                destination,
                converter,
                input_config,
                output_config,
                output_root=destination.parent,
            )
            items.append(item)
            if item.status == ItemStatus.OK:
                artifacts.extend(Path(path) for path in item.output.split(";"))
    else:
        files = sorted(source.rglob("*.csv"))
        if request.filter_name:
            files = [path for path in files if request.filter_name in path.name]
        if request.merge:
            frames = []
            for _, path in _events("convert", "read", files, ctx, items):
                try:
                    frame = _read_convert_csv(path, input_config)
                    if not converter.has_matching_columns(frame):
                        items.append(
                            ItemResult(
                                ItemStatus.SKIP,
                                str(path),
                                str(destination),
                                REASON_RULE_MISMATCH,
                            )
                        )
                        continue
                    frame = converter._merge_extra_source(frame, path)
                    frames.append(frame)
                    items.append(ItemResult(ItemStatus.OK, str(path), str(destination)))
                except Exception as exc:
                    items.append(
                        ItemResult(
                            ItemStatus.FAIL,
                            str(path),
                            str(destination),
                            classify_exception(exc),
                            str(exc),
                        )
                    )
            if frames:
                merged = pd.concat(frames, ignore_index=True)

                def _merge_path(destination, index, frame, merge_classifier, merge_default):
                    if merge_classifier is not None:
                        category = (
                            merge_classifier.classify_frame(frame, destination) or merge_default
                        )
                        if merge_classifier.rule.rename:
                            base = merge_classifier.resolve_filename(destination)
                            stem, suffix = Path(base).stem, Path(base).suffix
                        else:
                            stem, suffix = destination.stem, destination.suffix
                        name = f"{stem}_{index}{suffix}" if index is not None else f"{stem}{suffix}"
                        return destination.parent / category / name
                    if index is None:
                        return destination.parent / destination.name
                    return destination.parent / f"{destination.stem}_{index}.csv"

                def _write_merge_output(destination, index, frame):
                    """写出合并结果：分类/重命名后写 CSV 并记录产物，异常降级为 FAIL。"""
                    try:
                        merge_classifier = _convert_classifier(converter)
                        merge_default = _classify_default(converter)
                        path = _merge_path(
                            destination, index, frame, merge_classifier, merge_default
                        )
                        _write_convert_csv(frame, path, output_config)
                        artifacts.append(path)
                    except Exception as exc:
                        items.append(
                            ItemResult(
                                ItemStatus.FAIL,
                                str(source),
                                str(destination),
                                classify_exception(exc),
                                str(exc),
                            )
                        )

                if converter.rule.split:
                    try:
                        chunks = converter.convert_split(merged)
                    except Exception as exc:
                        items.append(
                            ItemResult(
                                ItemStatus.FAIL,
                                str(source),
                                str(destination),
                                classify_exception(exc),
                                str(exc),
                            )
                        )
                    else:
                        if not chunks:
                            items.append(
                                ItemResult(
                                    ItemStatus.SKIP,
                                    str(source),
                                    str(destination),
                                    REASON_RULE_MISMATCH,
                                    "不符合转换规则",
                                )
                            )
                        else:
                            for index, chunk in enumerate(chunks, 1):
                                _write_merge_output(destination, index, chunk)
                elif request.split:
                    converted = converter.convert(merged)
                    for index, start in enumerate(range(0, len(converted), request.split), 1):
                        chunk = converted.iloc[start : start + request.split]
                        _write_merge_output(destination, index, chunk)
                else:
                    converted = converter.convert(merged)
                    _write_merge_output(destination, None, converted)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            for _, path in _events("convert", "files", files, ctx, items):
                output_file = destination / path.relative_to(source)
                item = _convert_one(
                    path,
                    output_file,
                    converter,
                    input_config,
                    output_config,
                    output_root=destination,
                    input_root=source,
                )
                items.append(item)
                if item.status == ItemStatus.OK:
                    artifacts.extend(Path(path) for path in item.output.split(";"))
    report = _write_align_report(converter, destination.parent if source.is_file() else destination)
    if report:
        artifacts.append(report)
    return _batch("convert", items, artifacts)


def run_classify(
    request: ClassifyRequest, *, context: Optional[ExecutionContext] = None
) -> BatchResult:
    """按分类规则复制、移动或链接 CSV。"""
    from health_tools.core.classifier import DataClassifier
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.accuracy import AccuracyCalculator
    from health_tools.utils.csv_handler import CSVHandler

    if request.mode not in {"copy", "move", "symlink"}:
        raise RequestValidationError("mode 仅支持 copy、move 或 symlink")
    if request.conflict not in {"skip", "rename", "overwrite"}:
        raise RequestValidationError("conflict 仅支持 skip、rename 或 overwrite")
    ctx = _context(context)
    source = _require_path(request.input_path)
    rule = _load_rule(
        lambda value: RuleLoader.load_classify_rule(value, list(request.extend_files) or None),
        request.rule_file,
        "分类",
    )
    chip_name = request.chip_name or rule.target_chip
    chip_rule = _load_rule(RuleLoader.load_chip_rule, chip_name, "芯片") if chip_name else None
    classifier = DataClassifier(rule, chip_rule)
    output = Path(request.output_path)
    output.mkdir(parents=True, exist_ok=True)
    classifier.create_structure(output)
    files = [source] if source.is_file() else sorted(source.rglob("*.csv"))
    if request.filter_name:
        files = [path for path in files if request.filter_name in path.name]

    # 过滤阈值：CLI 覆盖规则
    rule_filters = getattr(rule, "filters", {}) or {}
    min_rows = (
        request.min_rows if request.min_rows is not None else int(rule_filters.get("min_rows", 0))
    )
    min_size_kb = (
        request.min_size_kb
        if request.min_size_kb is not None
        else float(rule_filters.get("min_size_kb", 0))
    )
    input_root = source if source.is_dir() else None

    accuracy = None
    config = getattr(rule, "accuracy", {}) or {}
    if request.enable_accuracy and (config or (request.ref_column and request.pred_column)):
        ref = request.ref_column or config.get("ref_column")
        pred = request.pred_column or config.get("pred_column")
        if ref and pred:
            accuracy = AccuracyCalculator(
                ref_column=ref,
                pred_column=pred,
                methods=config.get(
                    "methods", ["std", "rmse", "mae", "within_1", "within_2", "within_3"]
                ),
                thresholds=config.get("thresholds", []),
            )
    handler = CSVHandler(chip_rule)
    items: List[ItemResult] = []
    artifacts: List[Path] = []
    seen_targets: set = set()
    for _, path in _events("classify", "files", files, ctx, items):
        try:
            if min_rows > 0 or min_size_kb > 0:
                skip_reason = classifier.check_filters(path, min_rows, min_size_kb)
                if skip_reason is not None:
                    if skip_reason.startswith(REASON_TOO_FEW_ROWS):
                        reason = REASON_TOO_FEW_ROWS
                    elif skip_reason.startswith(REASON_TOO_SMALL):
                        reason = REASON_TOO_SMALL
                    else:
                        # 异常原因：classify_exception 返回的常量是 skip_reason 的前缀
                        reason = skip_reason.split(":")[0].strip()
                    items.append(
                        ItemResult(
                            ItemStatus.SKIP,
                            str(path),
                            reason=reason,
                            detail=skip_reason,
                        )
                    )
                    continue

            target_dir = classifier.classify(path, output, input_root=input_root)
            output_name = classifier.resolve_filename(path)
            if target_dir:
                target = target_dir / output_name
                category = str(target_dir.relative_to(output))
                if request.dry_run:
                    items.append(
                        ItemResult(
                            ItemStatus.SKIP,
                            str(path),
                            str(target),
                            reason=REASON_DRY_RUN,
                            detail="预览模式（未写入）",
                            category=category,
                        )
                    )
                    seen_targets.add(target)
                    continue
                if target.exists() or target in seen_targets:
                    if request.conflict == "skip":
                        items.append(
                            ItemResult(
                                ItemStatus.SKIP,
                                str(path),
                                str(target),
                                reason=REASON_CONFLICT,
                                detail="目标路径已存在，跳过",
                                category=category,
                            )
                        )
                        continue
                    elif request.conflict == "rename":
                        stem = target.stem
                        suffix = target.suffix
                        index = 1
                        while target.exists() or target in seen_targets:
                            target = target_dir / f"{stem}_{index}{suffix}"
                            index += 1
                seen_targets.add(target)
                target_dir.mkdir(parents=True, exist_ok=True)
                if request.mode == "copy":
                    shutil.copy2(path, target)
                elif request.mode == "move":
                    shutil.move(str(path), str(target))
                else:
                    target.symlink_to(path.resolve())
                artifacts.append(target)
                items.append(ItemResult(ItemStatus.OK, str(path), str(target), category=category))
                if accuracy:
                    try:
                        _, frame = handler.read(target)
                        accuracy.add_file_result(category, frame)
                    except Exception as exc:
                        items.append(
                            ItemResult(
                                ItemStatus.WARN,
                                str(path),
                                str(target),
                                detail=f"准确率计算跳过: {exc}",
                                category=category,
                            )
                        )
            elif request.unknown_dir:
                target_dir = output / request.unknown_dir
                target = target_dir / output_name
                category = request.unknown_dir
                if request.dry_run:
                    items.append(
                        ItemResult(
                            ItemStatus.SKIP,
                            str(path),
                            str(target),
                            reason=REASON_DRY_RUN,
                            detail="预览模式（未写入）",
                            category=category,
                        )
                    )
                    seen_targets.add(target)
                    continue
                if target.exists() or target in seen_targets:
                    if request.conflict == "skip":
                        items.append(
                            ItemResult(
                                ItemStatus.SKIP,
                                str(path),
                                str(target),
                                reason=REASON_CONFLICT,
                                detail="目标路径已存在，跳过",
                                category=category,
                            )
                        )
                        continue
                    elif request.conflict == "rename":
                        stem = target.stem
                        suffix = target.suffix
                        index = 1
                        while target.exists() or target in seen_targets:
                            target = target_dir / f"{stem}_{index}{suffix}"
                            index += 1
                seen_targets.add(target)
                target_dir.mkdir(parents=True, exist_ok=True)
                if request.mode == "copy":
                    shutil.copy2(path, target)
                elif request.mode == "move":
                    shutil.move(str(path), str(target))
                artifacts.append(target)
                items.append(
                    ItemResult(
                        ItemStatus.SKIP,
                        str(path),
                        str(target),
                        REASON_NO_DATA,
                        "未匹配任何分类规则，已放入未知目录",
                        request.unknown_dir,
                    )
                )
            else:
                items.append(
                    ItemResult(ItemStatus.SKIP, str(path), reason=REASON_NO_DATA, detail="未匹配")
                )
        except Exception as exc:
            items.append(
                ItemResult(
                    ItemStatus.FAIL, str(path), reason=classify_exception(exc), detail=str(exc)
                )
            )
    if accuracy:
        report_path = output / "accuracy_summary.csv"
        accuracy.save_report(report_path)
        artifacts.append(report_path)
    return _batch("classify", items, artifacts)


def _parse_metric_config(value: Optional[str]) -> Optional[dict]:
    if not value:
        return None
    try:
        parts = [float(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise RequestValidationError("产测配置必须为三个逗号分隔的数字") from exc
    if len(parts) != 3:
        raise RequestValidationError("产测配置格式为 skip_head,skip_tail,min_duration")
    return {
        "skip_head_seconds": parts[0],
        "skip_tail_seconds": parts[1],
        "min_duration_seconds": parts[2],
    }


def _factory_calculator(request, chip_rule):
    from health_tools.core.factory import FactoryCalculator

    config = chip_rule.factory_config if chip_rule else {}
    info = chip_rule.chip_info if chip_rule and chip_rule.chip_info else {}
    return FactoryCalculator(
        gain=request.gain,
        current=request.current,
        sample_rate=request.sample_rate or config.get("sample_rate", 100.0),
        adc_full_scale=float(info.get("adc_full_scale", 8388608)),
        adc_offset=(
            request.adc_offset
            if request.adc_offset is not None
            else float(info.get("adc_offset", 0))
        ),
        adc_vref=float(info.get("adc_vref", 1.8)),
        tia_ratio=float(info.get("tia_ratio", 2.0)),
        snr_config=_parse_metric_config(request.snr_cfg) or config.get("snr"),
        ctr_config=_parse_metric_config(request.ctr_cfg) or config.get("ctr"),
        noise_config=_parse_metric_config(request.noise_cfg) or config.get("noise"),
    )


def run_factory(
    request: FactoryRequest, *, context: Optional[ExecutionContext] = None
) -> BatchResult:
    """计算 SNR、CTR 和 Noise 产测指标。"""
    import pandas as pd

    from health_tools.core.factory import ChipInfoExtractor
    from health_tools.models.rules import ChipRule
    from health_tools.rules.loader import RuleLoader
    from health_tools.utils.csv_handler import read_csv_df

    ctx = _context(context)
    source = _require_path(request.input_path)
    chip_rule = None
    if request.chip_name:
        chip_rule = _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
    elif request.rule_file:
        convert_rule = _load_rule(RuleLoader.load_convert_rule, request.rule_file, "转换")
        chip_rule = ChipRule(chip="", csv=convert_rule.csv, columns=[])
    calculator = _factory_calculator(request, chip_rule)
    extractor = (
        ChipInfoExtractor(chip_rule.chip_info, chip_rule.gain_tia_map)
        if chip_rule and chip_rule.chip_info
        else None
    )
    files = [source] if source.is_file() else sorted(source.rglob("*.csv"))
    if request.filter_name:
        files = [path for path in files if request.filter_name in path.name]
    channels = request.channels.split(",") if request.channels else None
    items: List[ItemResult] = []
    frames = []
    for _, path in _events("factory", "files", files, ctx, items):
        try:
            frame = read_csv_df(path, chip_rule)
            selected = channels
            if selected is None and chip_rule and chip_rule.factory_columns:
                selected = [
                    column for column in chip_rule.factory_columns if column in frame.columns
                ]
            metrics = calculator.calculate(frame, selected, extractor=extractor)
            if not metrics:
                items.append(
                    ItemResult(
                        ItemStatus.SKIP, str(path), reason=REASON_NO_DATA, detail="无有效数据通道"
                    )
                )
                continue
            file_name = path.name if source.is_file() else str(path.relative_to(source))
            frames.append(calculator.to_dataframe(metrics, file_name=file_name))
            items.append(ItemResult(ItemStatus.OK, str(path), rows=len(frame)))
        except Exception as exc:
            items.append(
                ItemResult(
                    ItemStatus.FAIL, str(path), reason=classify_exception(exc), detail=str(exc)
                )
            )
    if not frames:
        return _batch("factory", items)
    result = pd.concat(frames, ignore_index=True)
    if request.output_path:
        output = Path(request.output_path)
        if output.is_dir() or (not output.suffix and not output.exists()):
            output.mkdir(parents=True, exist_ok=True)
            name = source.name if source.is_file() else source.resolve().name
            output = output / f"factory_{name}.csv"
    elif source.is_dir():
        output = source / f"factory_{source.resolve().name}.csv"
    else:
        output = source.parent / f"factory_{source.stem}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    return _batch("factory", items, [output])


def _parse_ac_groups(channels: Optional[str]) -> Optional[List[List[str]]]:
    if channels is None:
        return None
    groups = []
    for raw in channels.split(";"):
        group = [item.strip() for item in raw.split(",") if item.strip()]
        if not group or len(group) > 4:
            raise RequestValidationError(f"AC 每组最多支持 4 个通道，且不能为空: {','.join(group)}")
        groups.append(group)
    return groups


def _safe_suffix(channels: List[str]) -> str:
    return "-".join(re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") for value in channels)


def _plot_one(path, output, plotter, request, chip_rule, channels, groups) -> ItemResult:
    try:
        from health_tools.utils.csv_handler import read_csv_df

        frame = read_csv_df(path, chip_rule)
        outputs: List[Path] = []
        warning = ""
        if request.plot_type in {"time", "both"}:
            target = output / f"{path.stem}_time.{plotter.fmt}"
            plotter.plot_time(frame, target, channels)
            outputs.append(target)
        if request.plot_type in {"freq", "both"}:
            target = output / f"{path.stem}_freq.{plotter.fmt}"
            plotter.plot_freq(frame, target, channels)
            outputs.append(target)
        if request.plot_type in {"stft", "both"}:
            if chip_rule and not channels:
                outputs.extend(plotter.plot_chip_stft(frame, output, path.stem))
            else:
                target = output / f"{path.stem}_stft.{plotter.fmt}"
                plotter.plot_stft(frame, target, channels, request.ref_column)
                outputs.append(target)
        if request.plot_type == "ac":
            from health_tools.core.ppg_analysis import resolve_acc_columns, resolve_ppg_channels

            acc = resolve_acc_columns(frame, chip_rule.acc_columns if chip_rule else None)
            if len(acc) != 3:
                raise ValueError("无法识别完整的 ACC X/Y/Z 三轴")
            actual_groups = groups
            automatic = actual_groups is None
            if automatic:
                detected = resolve_ppg_channels(frame, chip_rule.chip if chip_rule else "")
                actual_groups = [detected[:4]]
                if len(detected) > 4:
                    warning = f"未绘制通道: {', '.join(detected[4:])}"
            for group in actual_groups or []:
                suffix = "" if automatic else f"_{_safe_suffix(group)}"
                target = output / f"{path.stem}_ac{suffix}.{plotter.fmt}"
                plotter.plot_ac(frame, target, group, acc)
                outputs.append(target)
        if request.plot_type == "fft":
            from health_tools.core.ppg_analysis import resolve_ppg_channels

            actual = channels or resolve_ppg_channels(frame, chip_rule.chip if chip_rule else "")
            for channel in actual:
                target = output / f"{path.stem}_fft_{_safe_suffix([channel])}.{plotter.fmt}"
                plotter.plot_fft(frame, target, channel)
                outputs.append(target)
        return ItemResult(
            ItemStatus.WARN if warning else ItemStatus.OK,
            str(path),
            ";".join(str(value) for value in outputs),
            reason=warning,
            detail=warning,
            rows=len(frame),
        )
    except Exception as exc:
        return ItemResult(
            ItemStatus.FAIL,
            str(path),
            str(output),
            classify_exception(exc),
            str(exc),
        )


def run_plot(request: PlotRequest, *, context: Optional[ExecutionContext] = None) -> BatchResult:
    """绘制时域、频域、STFT、PSD、AC 或 FFT 图。"""
    from health_tools.core.plotter import DataPlotter
    from health_tools.models.rules import ChipRule
    from health_tools.rules.loader import RuleLoader

    valid = {"time", "freq", "stft", "psd", "ac", "fft", "both"}
    if request.plot_type not in valid:
        raise RequestValidationError(f"不支持的图表类型: {request.plot_type}")
    if request.channels and request.plot_type != "ac" and ";" in request.channels:
        raise RequestValidationError("分号通道分组仅支持 AC")
    ctx = _context(context)
    source = _require_path(request.input_path)
    output = Path(request.output_path)
    output.mkdir(parents=True, exist_ok=True)
    if request.plot_type == "psd":
        if not source.is_dir():
            raise RequestValidationError("PSD绘图输入必须是离线结果目录")
        from health_tools.core.psd_plotter import PsdPlotter

        ctx.check_cancelled("psd")
        ctx.emit(ProgressEvent("plot", "psd", 0, 1, "生成 PSD", str(source)))
        saved = PsdPlotter().plot(
            source, save_dir=output, show_progress=False, acc_mode=request.psd_acc
        )
        ctx.check_cancelled("psd", BatchResult("plot", artifacts=tuple(saved)))
        ctx.emit(ProgressEvent("plot", "psd", 1, 1, "完成", str(source)))
        psd_items = tuple(ItemResult(ItemStatus.OK, str(source), str(path)) for path in saved)
        return BatchResult("plot", psd_items, tuple(saved))
    chip_rule = None
    if request.chip_name:
        chip_rule = _load_rule(RuleLoader.load_chip_rule, request.chip_name, "芯片")
    elif request.rule_file:
        rule = _load_rule(RuleLoader.load_convert_rule, request.rule_file, "转换")
        chip_rule = ChipRule(chip="", csv=rule.csv, columns=[])
    channels = (
        [value.strip() for value in request.channels.split(",") if value.strip()]
        if request.channels and request.plot_type != "ac"
        else None
    )
    groups = _parse_ac_groups(request.channels) if request.plot_type == "ac" else None
    if request.plot_type in {"ac", "fft"}:
        from health_tools.core.ppg_analysis import validate_bandpass

        try:
            low, high = map(float, request.bandpass.split("-"))
            validate_bandpass(request.sample_rate, low, high)
        except Exception as exc:
            raise RequestValidationError(f"非法带通范围 {request.bandpass}: {exc}") from exc
    try:
        freq_range = tuple(map(float, request.freq_range.split("-")))
        if len(freq_range) != 2:
            raise ValueError
    except Exception:
        freq_range = (30.0, 240.0)
    plotter = DataPlotter(
        sample_rate=request.sample_rate,
        window=request.window,
        overlap=request.overlap,
        fmt=request.fmt,
        dpi=request.dpi,
        bandpass=request.bandpass,
        remove_baseline=request.remove_baseline,
        baseline_method=request.baseline_method,
        freq_bpm=request.freq_bpm,
        freq_range=freq_range,
    )
    files = [source] if source.is_file() else sorted(source.rglob("*.csv"))
    if request.filter_name:
        files = [path for path in files if request.filter_name in path.name]
    items: List[ItemResult] = []
    artifacts: List[Path] = []
    for _, path in _events("plot", "files", files, ctx, items):
        item = _plot_one(path, output, plotter, request, chip_rule, channels, groups)
        items.append(item)
        if item.status in {ItemStatus.OK, ItemStatus.WARN}:
            artifacts.extend(Path(value) for value in item.output.split(";") if value)
    return _batch("plot", items, artifacts)
