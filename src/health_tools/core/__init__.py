from health_tools.models.rules import (
    ChipRule,
    ClassifyRule,
    ConvertRule,
    DataColumn,
    ParseRule,
)

_LAZY_IMPORTS = {
    "LogParser": "health_tools.core.parser",
    "DataPlotter": "health_tools.core.plotter",
    "DataClassifier": "health_tools.core.classifier",
    "DataConverter": "health_tools.core.converter",
    "DataSplitter": "health_tools.core.splitter",
    "split_by_column_value": "health_tools.core.splitter",
    "split_by_size": "health_tools.core.splitter",
    "split_by_time": "health_tools.core.splitter",
    "BatchProcessor": "health_tools.core.processor",
    "process_files": "health_tools.core.processor",
    "STFTPlotter": "health_tools.core.stft",
    "remove_baseline": "health_tools.core.stft",
    "bandpass_filter": "health_tools.core.stft",
    "compute_stft": "health_tools.core.stft",
    "compute_psd": "health_tools.core.stft",
}

__all__ = [
    "LogParser",
    "ParseRule",
    "ChipRule",
    "DataPlotter",
    "DataClassifier",
    "ClassifyRule",
    "DataColumn",
    "DataConverter",
    "ConvertRule",
    "DataSplitter",
    "split_by_column_value",
    "split_by_size",
    "split_by_time",
    "BatchProcessor",
    "process_files",
    "STFTPlotter",
    "remove_baseline",
    "bandpass_filter",
    "compute_stft",
    "compute_psd",
]


def __getattr__(name):
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module 'health_tools.core' has no attribute {name}")
