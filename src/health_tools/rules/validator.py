import math
import re
from pathlib import Path
from typing import List

import yaml

from health_tools.utils.columns import expand_columns as _expand_cols


class RuleValidator:
    @staticmethod
    def validate_file(file_path: Path, strict: bool = False) -> List[str]:
        errors = []

        if not file_path.exists():
            return [f"文件不存在: {file_path}"]

        if file_path.suffix not in (".yaml", ".yml"):
            return [f"文件必须是YAML格式: {file_path.suffix}"]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                rule = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return [f"YAML解析错误: {e}"]

        if not isinstance(rule, dict):
            return ["规则文件必须是一个字典结构"]

        rule_type = RuleValidator._detect_rule_type(file_path)

        if rule_type == "chip":
            errors.extend(RuleValidator._validate_chip_rule(rule, strict))
        elif rule_type == "parse":
            errors.extend(RuleValidator._validate_parse_rule(rule, strict))
        elif rule_type == "classify":
            errors.extend(RuleValidator._validate_classify_rule(rule, strict))
        elif rule_type == "convert":
            errors.extend(RuleValidator._validate_convert_rule(rule, strict))
        elif rule_type == "evaluate":
            errors.extend(RuleValidator._validate_evaluate_rule(rule, strict))
        elif rule_type == "analysis":
            errors.extend(RuleValidator._validate_analysis_rule(rule, strict))
        elif rule_type == "check":
            errors.extend(RuleValidator._validate_check_rule(rule, strict))
        else:
            errors.append("无法识别的规则类型")

        return errors

    @staticmethod
    def validate(rule: object, rule_type: str, strict: bool = False) -> List[str]:
        """校验内存中的规则字典，按规则类型分发。"""
        if not isinstance(rule, dict):
            return ["规则必须是一个字典结构"]

        if rule_type == "chip":
            return RuleValidator._validate_chip_rule(rule, strict)
        elif rule_type == "parse":
            return RuleValidator._validate_parse_rule(rule, strict)
        elif rule_type == "classify":
            return RuleValidator._validate_classify_rule(rule, strict)
        elif rule_type == "convert":
            return RuleValidator._validate_convert_rule(rule, strict)
        elif rule_type == "evaluate":
            return RuleValidator._validate_evaluate_rule(rule, strict)
        elif rule_type == "analysis":
            return RuleValidator._validate_analysis_rule(rule, strict)
        elif rule_type == "check":
            return RuleValidator._validate_check_rule(rule, strict)
        return ["无法识别的规则类型"]

    @staticmethod
    def _detect_rule_type(rule_path: Path) -> str:
        parts = rule_path.parts
        if "chip" in parts:
            return "chip"
        elif "parse" in parts:
            return "parse"
        elif "classify" in parts:
            return "classify"
        elif "convert" in parts:
            return "convert"
        elif "evaluate" in parts:
            return "evaluate"
        elif "analysis" in parts:
            return "analysis"
        elif "check" in parts:
            return "check"
        return "unknown"

    @staticmethod
    def _validate_check_rule(rule: dict, strict: bool) -> List[str]:
        errors = []
        allowed = {
            "version",
            "description",
            "chip",
            "checks",
            "tolerance",
            "static_min",
            "ratios",
            "acc_axis",
            "timestamp",
            "reference",
            "scene_regex",
            "accuracy",
        }
        unknown = set(rule) - allowed
        if unknown:
            errors.extend(f"check 规则包含未知字段: {key}" for key in sorted(unknown))

        if "version" not in rule:
            errors.append("缺少 'version' 字段")
        if "chip" in rule and (not isinstance(rule["chip"], str) or not rule["chip"].strip()):
            errors.append("check 规则 'chip' 必须是非空字符串")

        checks = rule.get("checks")
        supported_checks = {"range", "ipd", "frame", "center", "acc", "agc", "ref"}
        if checks is not None:
            if not isinstance(checks, list) or not checks:
                errors.append("check 规则 'checks' 必须是非空列表")
            else:
                normalized_checks = []
                for index, check in enumerate(checks):
                    if not isinstance(check, str) or not check.strip():
                        errors.append(f"checks[{index}] 必须是非空字符串")
                        continue
                    normalized_checks.append(check)
                unknown_checks = set(normalized_checks) - supported_checks
                if unknown_checks:
                    errors.append("check 规则包含未知检查项: " + ", ".join(sorted(unknown_checks)))

        for field in ("tolerance", "static_min"):
            if field in rule and not RuleValidator._is_non_negative_integer(rule[field]):
                errors.append(f"check 规则 '{field}' 必须是非负整数")
        if "acc_axis" in rule and not isinstance(rule["acc_axis"], bool):
            errors.append("check 规则 'acc_axis' 必须是布尔值")

        ratios = rule.get("ratios")
        if ratios is not None:
            if not isinstance(ratios, dict):
                errors.append("check 规则 'ratios' 必须是映射")
            else:
                for name, value in ratios.items():
                    if name not in {"range", "frame", "center", "ipd", "acc"}:
                        errors.append(f"ratios 包含未知字段: {name}")
                    elif (
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not math.isfinite(float(value))
                        or value < 0
                    ):
                        errors.append(f"ratios.{name} 必须是非负有限数")

        timestamp = rule.get("timestamp")
        if timestamp is not None:
            if not isinstance(timestamp, dict):
                errors.append("check 规则 'timestamp' 必须是映射")
            else:
                errors.extend(
                    RuleValidator._validate_non_negative_number(
                        timestamp, "ratio", "timestamp.ratio"
                    )
                )
                errors.extend(
                    RuleValidator._validate_non_negative_number(timestamp, "ms", "timestamp.ms")
                )
                errors.extend(
                    RuleValidator._validate_non_negative_number(
                        timestamp, "fail_ratio", "timestamp.fail_ratio"
                    )
                )
                errors.extend(
                    RuleValidator._validate_non_negative_number(
                        timestamp, "base_ms", "timestamp.base_ms"
                    )
                )
                if (
                    "column" in timestamp
                    and timestamp["column"] is not None
                    and (
                        not isinstance(timestamp["column"], str) or not timestamp["column"].strip()
                    )
                ):
                    errors.append("timestamp.column 必须是非空字符串或 null")

        reference = rule.get("reference")
        if reference is not None:
            if not isinstance(reference, dict):
                errors.append("check 规则 'reference' 必须是映射")
            else:
                for name in ("sample_rate", "stale_seconds", "step_threshold"):
                    errors.extend(
                        RuleValidator._validate_non_negative_number(
                            reference, name, f"reference.{name}"
                        )
                    )
                for name in ("hr_column", "spo2_column"):
                    if (
                        name in reference
                        and reference[name] is not None
                        and (not isinstance(reference[name], str) or not reference[name].strip())
                    ):
                        errors.append(f"reference.{name} 必须是非空字符串或 null")

        accuracy = rule.get("accuracy")
        if accuracy is not None:
            errors.extend(RuleValidator._validate_check_accuracy(accuracy))
        return errors

    @staticmethod
    def _is_non_negative_integer(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value).is_integer()
            and value >= 0
        )

    @staticmethod
    def _validate_non_negative_number(config: dict, key: str, label: str) -> List[str]:
        if key not in config or config[key] is None:
            return []
        value = config[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or value < 0
        ):
            return [f"{label} 必须是非负有限数或 null"]
        return []

    @staticmethod
    def _validate_check_accuracy(config: object) -> List[str]:
        if not isinstance(config, dict):
            return ["check 规则 'accuracy' 必须是映射"]
        errors = []
        for key in ("enabled", "inclusive"):
            if key in config and not isinstance(config[key], bool):
                errors.append(f"accuracy.{key} 必须是布尔值")
        for key in ("ref_column", "online_column"):
            if key in config and (not isinstance(config[key], str) or not config[key].strip()):
                errors.append(f"accuracy.{key} 必须是非空字符串")
        if (
            "comp_column" in config
            and config["comp_column"] is not None
            and (not isinstance(config["comp_column"], str) or not config["comp_column"].strip())
        ):
            errors.append("accuracy.comp_column 必须是非空字符串或 null")
        methods = config.get("methods")
        known_methods = {
            "std",
            "rmse",
            "mae",
            "mape",
            "bias",
            "within_5",
            "within_10",
            "within_15",
            "correlation",
            "r2",
        }
        if methods is not None:
            if not isinstance(methods, list):
                errors.append("accuracy.methods 必须是列表")
            else:
                for method in methods:
                    if not isinstance(method, str) or (
                        method not in known_methods
                        and not re.fullmatch(r"within_\d+(?:\.\d+)?", method)
                    ):
                        errors.append(f"accuracy.methods 包含未知方法: {method}")

        thresholds = config.get("thresholds", [])
        if not isinstance(thresholds, list):
            errors.append("accuracy.thresholds 必须是列表")
        else:
            for index, threshold in enumerate(thresholds):
                prefix = f"accuracy.thresholds[{index}]"
                if not isinstance(threshold, dict):
                    errors.append(f"{prefix} 必须是映射")
                    continue
                if set(threshold) - {"name", "value", "percent"}:
                    errors.append(f"{prefix} 包含未知字段")
                name = threshold.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append(f"{prefix}.name 必须是非空字符串")
                has_value = "value" in threshold
                has_percent = "percent" in threshold
                if has_value == has_percent:
                    errors.append(f"{prefix} 必须且只能提供 value 或 percent")
                key = "value" if has_value else "percent"
                if key in threshold and not RuleValidator._is_positive_finite(threshold[key]):
                    errors.append(f"{prefix}.{key} 必须是有限正数")

        marks = config.get("marks", [])
        if not isinstance(marks, list):
            errors.append("accuracy.marks 必须是列表")
            return errors
        ids = set()
        categories = set()
        safe_category = re.compile(r"^[A-Za-z0-9_-]+$")
        for index, mark in enumerate(marks):
            prefix = f"marks[{index}]"
            if not isinstance(mark, dict):
                errors.append(f"{prefix} 必须是映射")
                continue
            for field in ("id", "comparison", "metric", "category", "label"):
                if not isinstance(mark.get(field), str) or not mark[field].strip():
                    errors.append(f"{prefix} 缺少有效的 '{field}'")
            mark_id = mark.get("id")
            category = mark.get("category")
            if isinstance(mark_id, str) and mark_id in ids:
                errors.append(f"{prefix}.id 重复: {mark_id}")
            if isinstance(category, str) and category in categories:
                errors.append(f"{prefix}.category 重复: {category}")
            if isinstance(mark_id, str) and mark_id:
                if not safe_category.fullmatch(mark_id):
                    errors.append(f"{prefix}.id 必须是安全的单段目录名")
                ids.add(mark_id)
            if isinstance(category, str) and category:
                categories.add(category)
                if not safe_category.fullmatch(category):
                    errors.append(f"{prefix}.category 必须是安全的单段目录名")
            comparison = mark.get("comparison")
            if isinstance(comparison, str) and comparison in {"online", "comp"}:
                if "min" not in mark or "min_gap" in mark:
                    errors.append(f"{prefix} comparison={comparison} 需要 min 且不能有 min_gap")
                elif not RuleValidator._is_percent(mark["min"]):
                    errors.append(f"{prefix}.min 必须是 0 到 100 的有限数")
            elif isinstance(comparison, str) and comparison == "online_below_comp":
                if "min_gap" not in mark or "min" in mark:
                    errors.append(
                        f"{prefix} comparison=online_below_comp 需要 min_gap 且不能有 min"
                    )
                elif not RuleValidator._is_non_negative_finite(mark["min_gap"]):
                    errors.append(f"{prefix}.min_gap 必须是非负有限数")
            elif isinstance(comparison, str) and comparison:
                errors.append(f"{prefix}.comparison 仅支持 online、comp、online_below_comp")
        return errors

    @staticmethod
    def _is_non_negative_finite(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        )

    @staticmethod
    def _is_percent(value: object) -> bool:
        return RuleValidator._is_non_negative_finite(value) and float(value) <= 100

    @staticmethod
    def _is_positive_finite(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value > 0
        )

    @staticmethod
    def _validate_chip_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        if "chip" not in rule:
            errors.append("芯片规则缺少 'chip' 字段")

        if "csv" not in rule:
            errors.append("芯片规则缺少 'csv' 字段")
        elif isinstance(rule.get("csv"), dict):
            csv_config = rule["csv"]
            if "header_row" not in csv_config:
                errors.append("csv配置缺少 'header_row' 字段")
            if "data_start_row" not in csv_config:
                errors.append("csv配置缺少 'data_start_row' 字段")

        if "columns" not in rule:
            errors.append("芯片规则缺少 'columns' 字段")
        else:
            columns = RuleValidator._expand_columns(rule["columns"])
            if not columns:
                errors.append("'columns' 字段不能为空")

        return errors

    @staticmethod
    def _validate_parse_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        patterns = rule.get("patterns")
        if patterns is not None:
            if not isinstance(patterns, dict) or not patterns:
                errors.append("解析规则 'patterns' 必须是非空字典")
            else:
                for name, pattern in patterns.items():
                    prefix = f"patterns.{name}"
                    if not isinstance(name, str) or not name.strip():
                        errors.append("解析规则 pattern 名称必须是非空字符串")
                        prefix = "patterns.<invalid>"
                    errors.extend(RuleValidator._validate_parse_pattern(pattern, prefix))
            if strict and "description" not in rule:
                errors.append("[严格模式] 缺少 'description' 字段")
            return errors

        errors.extend(RuleValidator._validate_parse_pattern(rule, "解析规则"))

        if strict and "description" not in rule:
            errors.append("[严格模式] 缺少 'description' 字段")

        return errors

    @staticmethod
    def _validate_parse_pattern(pattern_data: object, prefix: str) -> List[str]:
        errors = []
        if not isinstance(pattern_data, dict):
            return [f"'{prefix}' 必须是字典"]

        regex = pattern_data.get("regex")
        compiled = None
        if not isinstance(regex, str) or not regex:
            if prefix == "解析规则":
                errors.append("解析规则缺少 'regex' 字段")
            else:
                errors.append(f"{prefix} 缺少有效的 'regex' 字段")
        else:
            try:
                compiled = re.compile(regex)
            except re.error as exc:
                errors.append(f"{prefix} 正则表达式错误: {exc}")

        columns_data = pattern_data.get("columns")
        columns = []
        if not isinstance(columns_data, list):
            if prefix == "解析规则":
                errors.append("解析规则缺少 'columns' 字段")
            else:
                errors.append(f"{prefix} 缺少有效的 'columns' 字段")
        else:
            columns = RuleValidator._expand_columns(columns_data)
            if not columns:
                errors.append(f"{prefix} 的 'columns' 字段不能为空")

        if compiled is not None and columns:
            groups = compiled.groups
            if groups == len(columns):
                return errors
            separator = pattern_data.get("separator", ",")
            if groups == 1 and len(columns) > 1:
                if not isinstance(separator, str) or not separator:
                    errors.append(f"{prefix} 使用单捕获组拆分多列时 separator 不能为空")
            else:
                errors.append(f"{prefix} 正则捕获组数量({groups})与列名数量({len(columns)})不匹配")

        return errors

    @staticmethod
    def _validate_classify_rule(
        rule: dict, strict: bool, require_version: bool = True
    ) -> List[str]:
        errors = []

        if require_version and "version" not in rule:
            errors.append("缺少 'version' 字段")

        patterns = rule.get("patterns")
        main_keys = {"filename", "data_columns", "structure", "rules", "extract", "classify"}
        if patterns is not None and not (main_keys & set(rule)):
            errors.extend(RuleValidator._validate_classify_patterns(patterns))
            return errors

        has_simple = isinstance(rule.get("structure"), dict) and bool(rule.get("structure"))
        has_pipeline = isinstance(rule.get("extract"), list) and isinstance(
            rule.get("classify"), list
        )

        if not has_simple and not has_pipeline:
            errors.append("分类规则需要非空 'structure'，或同时提供 'extract'/'classify' 列表")

        extract_items = rule.get("extract")
        if isinstance(extract_items, list):
            for index, item in enumerate(extract_items):
                if not isinstance(item, dict) or not item.get("name") or not item.get("function"):
                    errors.append(f"'extract[{index}]' 需要 name 和 function")
        classify_items = rule.get("classify")
        if isinstance(classify_items, list):
            for index, item in enumerate(classify_items):
                if not isinstance(item, dict) or not item.get("target"):
                    errors.append(f"'classify[{index}]' 需要 target")

        data_columns = rule.get("data_columns")
        if data_columns is not None and not isinstance(data_columns, list):
            errors.append("'data_columns' 必须是列表")
        elif isinstance(data_columns, list):
            for index, item in enumerate(data_columns):
                if not isinstance(item, dict):
                    errors.append(f"'data_columns[{index}]' 必须是字典")

        if strict and has_simple:
            if not isinstance(rule.get("rules"), list):
                errors.append("[严格模式] 缺少 'rules' 字段")

        # 校验 path 字段
        path_cfg = rule.get("path")
        if path_cfg is not None:
            if not isinstance(path_cfg, dict):
                errors.append("'path' 必须是字典")
            else:
                path_regex = path_cfg.get("regex")
                if not isinstance(path_regex, str) or not path_regex:
                    errors.append("path 缺少有效的 'regex' 字段")
                else:
                    try:
                        re.compile(path_regex)
                    except re.error as exc:
                        errors.append(f"path 正则表达式错误: {exc}")
                fields = path_cfg.get("fields")
                if fields is not None and not isinstance(fields, list):
                    errors.append("path 'fields' 必须是列表")

        # 校验 filters 字段
        filters_cfg = rule.get("filters")
        if filters_cfg is not None:
            if not isinstance(filters_cfg, dict):
                errors.append("'filters' 必须是字典")
            else:
                for key in ("min_rows", "min_size_kb"):
                    if key in filters_cfg:
                        value = filters_cfg[key]
                        if not isinstance(value, (int, float)) or value < 0:
                            errors.append(f"filters.{key} 必须是非负数")

        # 校验 rename 字段
        rename_cfg = rule.get("rename")
        if rename_cfg is not None and not isinstance(rename_cfg, str):
            errors.append("'rename' 必须是字符串")

        return errors

    @staticmethod
    def _validate_classify_patterns(patterns: object) -> List[str]:
        if not isinstance(patterns, dict) or not patterns:
            return ["分类关键词库 'patterns' 必须是非空字典"]
        errors = []
        for name, values in patterns.items():
            if not isinstance(name, str) or not name.strip():
                errors.append("分类关键词库 patterns 的名称必须是非空字符串")
            if not isinstance(values, list) or not values:
                errors.append(f"patterns.{name} 必须是非空字符串列表")
                continue
            if any(not isinstance(value, str) or not value.strip() for value in values):
                errors.append(f"patterns.{name} 必须只包含非空字符串")
        return errors

    @staticmethod
    def _validate_convert_rule(rule: dict, strict: bool) -> List[str]:
        errors = []

        if "version" not in rule:
            errors.append("缺少 'version' 字段")

        has_mapping = "column_mapping" in rule and isinstance(rule.get("column_mapping"), dict)
        has_source_target = "source_columns" in rule and "target_columns" in rule

        if not has_mapping and not has_source_target:
            errors.append(
                "转换规则需要提供 'column_mapping' 或同时提供 " "'source_columns'/'target_columns'"
            )

        if has_source_target:
            src_cols = RuleValidator._expand_columns(rule["source_columns"])
            tgt_cols = RuleValidator._expand_columns(rule["target_columns"])
            if len(src_cols) != len(tgt_cols):
                errors.append(f"源列数({len(src_cols)})与目标列数({len(tgt_cols)})不匹配")

        extra_source = rule.get("extra_source")
        if extra_source is not None:
            if isinstance(extra_source, list):
                for index, item in enumerate(extra_source):
                    if not isinstance(item, dict):
                        errors.append(f"'extra_source[{index}]' 必须是字典")
                    else:
                        errors.extend(
                            RuleValidator._validate_extra_source_config(
                                item, f"extra_source[{index}]"
                            )
                        )
            elif isinstance(extra_source, dict):
                errors.extend(
                    RuleValidator._validate_extra_source_config(extra_source, "extra_source")
                )
            else:
                errors.append("'extra_source' 必须是字典或列表")

        split = rule.get("split")
        if split is not None:
            if not isinstance(split, dict):
                errors.append("'split' 必须是字典")
            else:
                errors.extend(RuleValidator._validate_split_config(split))

        classify = rule.get("classify")
        if classify is not None:
            errors.extend(RuleValidator._validate_convert_classify_config(classify, strict))

        return errors

    @staticmethod
    def _validate_convert_classify_config(config: object, strict: bool) -> List[str]:
        """convert 规则内联 classify 块：与 classify 规则同构，但不要求 version。"""
        if not isinstance(config, dict):
            return ["'classify' 必须是字典"]
        return RuleValidator._validate_classify_rule(config, strict=strict, require_version=False)

    @staticmethod
    def _validate_split_config(config: dict) -> List[str]:
        errors = []
        modes = [key for key in ("by_column", "by_size", "by_time") if key in config]
        if len(modes) != 1:
            errors.append("'split' 需要且仅需要 by_column/by_size/by_time 之一")
        if "by_column" in config:
            if not isinstance(config["by_column"], str) or not config["by_column"].strip():
                errors.append("'split.by_column' 必须是非空字符串")
            if "column_value" in config and (
                not isinstance(config["column_value"], (int, float))
                or isinstance(config["column_value"], bool)
            ):
                errors.append("'split.column_value' 必须是数字")
        if "by_size" in config and (
            not isinstance(config["by_size"], int)
            or isinstance(config["by_size"], bool)
            or config["by_size"] <= 0
        ):
            errors.append("'split.by_size' 必须是正整数")
        if "by_time" in config:
            if (
                not isinstance(config["by_time"], (int, float))
                or isinstance(config["by_time"], bool)
                or config["by_time"] <= 0
            ):
                errors.append("'split.by_time' 必须是正数")
            if not isinstance(config.get("time_column"), str) or not config["time_column"].strip():
                errors.append("'split.by_time' 需要非空 'time_column'")
        if "time_column" in config and "by_time" not in config:
            errors.append("'split.time_column' 仅在 by_time 模式下有效")
        if "column_value" in config and "by_column" not in config:
            errors.append("'split.column_value' 仅在 by_column 模式下有效")
        unknown = set(config) - {
            "by_column",
            "column_value",
            "by_size",
            "by_time",
            "time_column",
        }
        if unknown:
            errors.append(f"'split' 包含未知字段: {', '.join(sorted(unknown))}")
        return errors

    @staticmethod
    def _validate_evaluate_rule(rule: dict, strict: bool) -> List[str]:
        errors = []
        if rule.get("type") not in {"hr", "spo2"}:
            errors.append("评估规则 'type' 必须是 hr 或 spo2")
        for key in ("ref_column", "pred_column"):
            if not isinstance(rule.get(key), str) or not rule.get(key):
                errors.append(f"评估规则缺少有效的 '{key}' 字段")
        if "methods" in rule and not isinstance(rule.get("methods"), list):
            errors.append("评估规则 'methods' 必须是列表")
        if strict and "description" not in rule:
            errors.append("[严格模式] 缺少 'description' 字段")
        return errors

    @staticmethod
    def _validate_analysis_rule(rule: dict, strict: bool) -> List[str]:
        errors = []
        if "version" not in rule:
            errors.append("缺少 'version' 字段")
        if rule.get("type") not in {"hr", "spo2", "other"}:
            errors.append("分析规则 'type' 必须是 hr、spo2 或 other")
        if not isinstance(rule.get("columns"), dict):
            errors.append("分析规则缺少有效的 'columns' 映射")
        if not isinstance(rule.get("detectors"), list) or not rule.get("detectors"):
            errors.append("分析规则 'detectors' 必须是非空列表")
        if not isinstance(rule.get("thresholds", {}), dict):
            errors.append("分析规则 'thresholds' 必须是映射")
        causes = rule.get("causes")
        if not isinstance(causes, list) or not causes:
            errors.append("分析规则 'causes' 必须是非空列表")
        else:
            for index, cause in enumerate(causes):
                prefix = f"causes[{index}]"
                if not isinstance(cause, dict):
                    errors.append(f"{prefix} 必须是映射")
                    continue
                if not cause.get("id") or not cause.get("title"):
                    errors.append(f"{prefix} 需要 id 和 title")
                if cause.get("origin") not in {"raw", "reference", "algorithm"}:
                    errors.append(f"{prefix}.origin 必须是 raw、reference 或 algorithm")
                if not isinstance(cause.get("when"), dict):
                    errors.append(f"{prefix}.when 必须是结构化条件")
                if cause.get("origin") == "algorithm" and cause.get("actions"):
                    errors.append(f"{prefix} 算法原因不能提供 actions")
        if strict and "description" not in rule:
            errors.append("[严格模式] 缺少 'description' 字段")
        return errors

    @staticmethod
    def _validate_extra_source_config(config: dict, prefix: str) -> List[str]:
        errors = []
        if "column_mapping" in config and not isinstance(config.get("column_mapping"), dict):
            errors.append(f"'{prefix}.column_mapping' 必须是字典")
        for key in ("required_columns", "any_required_columns"):
            if key in config and not isinstance(config.get(key), list):
                errors.append(f"'{prefix}.{key}' 必须是列表")
        align = config.get("align")
        if align is not None:
            if not isinstance(align, dict):
                errors.append(f"'{prefix}.align' 必须是字典")
            elif not align.get("left_on") or not align.get("right_on"):
                errors.append(f"'{prefix}.align' 需要同时提供 'left_on' 和 'right_on'")
        return errors

    @staticmethod
    def _expand_columns(columns: list) -> list:
        return _expand_cols([str(c) for c in columns])
