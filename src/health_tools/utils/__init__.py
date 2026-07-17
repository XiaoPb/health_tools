"""工具函数聚合出口，按需加载以避免引入无关依赖。"""

import importlib

_LAZY_IMPORTS = {
    "detect_file_encoding": "health_tools.utils.file",
    "ensure_dir": "health_tools.utils.file",
    "find_files": "health_tools.utils.file",
    "setup_logger": "health_tools.utils.logger",
    "expand_columns": "health_tools.utils.columns",
    "parallel_process": "health_tools.utils.parallel",
    "parallel_process_with_index": "health_tools.utils.parallel",
    "batch_process": "health_tools.utils.parallel",
    "progress_track": "health_tools.utils.progress",
    "FileResult": "health_tools.utils.reporting",
    "ResultCollector": "health_tools.utils.reporting",
    "print_summary": "health_tools.utils.reporting",
    "calculate_median": "health_tools.utils.classify_helpers",
    "calculate_mean": "health_tools.utils.classify_helpers",
    "calculate_std": "health_tools.utils.classify_helpers",
    "classify_by_range": "health_tools.utils.classify_helpers",
    "extract_from_path": "health_tools.utils.classify_helpers",
    "get_column_value": "health_tools.utils.classify_helpers",
    "CLASSIFY_FUNCTIONS": "health_tools.utils.classify_helpers",
    "get_function": "health_tools.utils.classify_helpers",
    "register_function": "health_tools.utils.classify_helpers",
    "calculate_accuracy": "health_tools.utils.accuracy",
    "AccuracyCalculator": "health_tools.utils.accuracy",
    "ACCURACY_FUNCTIONS": "health_tools.utils.accuracy",
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name):
    if name not in _LAZY_IMPORTS:
        raise AttributeError(f"module 'health_tools.utils' has no attribute {name}")
    module = importlib.import_module(_LAZY_IMPORTS[name])
    return getattr(module, name)
