"""GHealth Tools 公共 API 请求与结果模型。"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


class ItemStatus(str, Enum):
    OK = "OK"
    SKIP = "SKIP"
    WARN = "WARN"
    FAIL = "FAIL"


class ConfigAction(str, Enum):
    INIT = "init"
    SHOW = "show"
    SET_RULES_DIR = "set_rules_dir"
    SET_OFFLINE_PATH = "set_offline_path"
    SET_OFFLINE_DEFAULT = "set_offline_default"
    SCAN_OFFLINE = "scan_offline"
    REPLACE = "replace"


class RuleType(str, Enum):
    CHIP = "chip"
    PARSE = "parse"
    CLASSIFY = "classify"
    CONVERT = "convert"
    EVALUATE = "evaluate"


class RuleSource(str, Enum):
    EFFECTIVE = "effective"
    USER = "user"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class ProgressEvent:
    operation: str
    stage: str
    completed: int
    total: Optional[int]
    message: str = ""
    current_item: Optional[str] = None


@dataclass(frozen=True)
class ItemResult:
    status: ItemStatus
    input: str
    output: str = ""
    reason: str = ""
    detail: str = ""
    category: str = ""
    rows: int = 0


@dataclass(frozen=True)
class BatchResult:
    operation: str
    items: Tuple[ItemResult, ...] = ()
    artifacts: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "artifacts", tuple(Path(path) for path in self.artifacts))

    def count(self, status: ItemStatus) -> int:
        return sum(item.status == status for item in self.items)

    @property
    def ok_count(self) -> int:
        return self.count(ItemStatus.OK)

    @property
    def skip_count(self) -> int:
        return self.count(ItemStatus.SKIP)

    @property
    def warn_count(self) -> int:
        return self.count(ItemStatus.WARN)

    @property
    def fail_count(self) -> int:
        return self.count(ItemStatus.FAIL)


@dataclass(frozen=True)
class InfoResult:
    target: Path
    kind: str
    summary: Mapping[str, Any]
    schema: Mapping[str, Any] = field(default_factory=dict)
    preview: Tuple[Mapping[str, Any], ...] = ()
    statistics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "summary", _freeze(self.summary))
        object.__setattr__(self, "schema", _freeze(self.schema))
        object.__setattr__(self, "preview", _freeze(self.preview))
        object.__setattr__(self, "statistics", _freeze(self.statistics))


@dataclass(frozen=True)
class ValidationResult:
    rule_file: Path
    valid: bool
    rule_type: str = ""
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigResult:
    action: ConfigAction
    config: Mapping[str, Any] = field(default_factory=dict)
    changed_paths: Tuple[Path, ...] = ()
    versions: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    revision: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", _freeze(self.config))
        object.__setattr__(self, "changed_paths", tuple(Path(path) for path in self.changed_paths))
        object.__setattr__(self, "versions", _freeze(self.versions))


@dataclass(frozen=True)
class CheckResult:
    batch: BatchResult
    report_path: Optional[Path] = None
    sort_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_counts", _freeze(self.sort_counts))


@dataclass(frozen=True)
class OfflineResult:
    batch: BatchResult
    output_dir: Optional[Path] = None
    versions: Tuple[str, ...] = ()
    reports: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "versions", tuple(self.versions))
        object.__setattr__(self, "reports", tuple(Path(path) for path in self.reports))


@dataclass(frozen=True)
class RuleVariantInfo:
    source: RuleSource
    path: Path
    writable: bool
    revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True)
class RuleInfo:
    rule_type: RuleType
    name: str
    source: RuleSource
    path: Path
    writable: bool
    overrides_builtin: bool
    variants: Tuple[RuleVariantInfo, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "variants", tuple(self.variants))


@dataclass(frozen=True)
class RuleCatalogResult:
    rules: Tuple[RuleInfo, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))


@dataclass(frozen=True)
class RuleDocumentResult:
    rule: RuleInfo
    source: str
    revision: str


@dataclass(frozen=True)
class OfflineVersionInfo:
    chip_name: str
    category: Optional[str]
    version: str
    is_default: bool
    exe_available: bool


@dataclass(frozen=True)
class OfflineCatalogResult:
    versions: Tuple[OfflineVersionInfo, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "versions", tuple(self.versions))


@dataclass(frozen=True)
class ParseRequest:
    input_path: Path
    output_path: Path
    rule_file: Optional[str] = None
    chip_name: Optional[str] = None
    delimiter: str = ","
    encoding: str = "utf-8"
    filter_name: Optional[str] = None
    dry_run: bool = False


@dataclass(frozen=True)
class PlotRequest:
    input_path: Path
    output_path: Path
    chip_name: Optional[str] = None
    rule_file: Optional[str] = None
    plot_type: str = "both"
    channels: Optional[str] = None
    sample_rate: int = 25
    window: int = 25
    overlap: float = 0.96
    fmt: str = "png"
    dpi: int = 150
    bandpass: str = "0.5-4.0"
    remove_baseline: bool = True
    baseline_method: str = "mean"
    freq_bpm: bool = True
    freq_range: str = "30-240"
    ref_column: Optional[str] = None
    psd_acc: str = "axis"
    no_show: bool = False
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class ClassifyRequest:
    input_path: Path
    output_path: Path
    rule_file: str = "spo2_posture.yaml"
    extend_files: Tuple[str, ...] = ()
    enable_accuracy: bool = False
    ref_column: Optional[str] = None
    pred_column: Optional[str] = None
    mode: str = "copy"
    report: bool = False
    unknown_dir: Optional[str] = None
    chip_name: Optional[str] = None
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class ConvertRequest:
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    rule_file: Optional[str] = None
    chip_name: Optional[str] = None
    from_format: Optional[str] = None
    to_format: Optional[str] = None
    merge: bool = False
    split: Optional[int] = None
    init_rule: bool = False
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class InfoRequest:
    target: Path
    stats: bool = False
    schema: bool = False
    preview: int = 10


@dataclass(frozen=True)
class ValidateRequest:
    rule_file: Path
    strict: bool = False


@dataclass(frozen=True)
class SplitRequest:
    input_path: Path
    output_path: Path
    chip_name: Optional[str] = None
    by_column: str = "FRAME_ID"
    column_value: float = 0
    by_size: Optional[int] = None
    by_time: Optional[float] = None
    time_column: Optional[str] = None
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class ProcessRequest:
    input_path: Path
    output_path: Path
    chip_name: Optional[str] = None
    frame_split: bool = False
    frame_column: str = "FRAME_ID"
    max_workers: int = 4
    pattern: str = "*.csv"
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class FactoryRequest:
    input_path: Path
    chip_name: Optional[str] = None
    rule_file: Optional[str] = None
    gain: Optional[float] = None
    current: Optional[float] = None
    sample_rate: Optional[float] = None
    snr_cfg: Optional[str] = None
    ctr_cfg: Optional[str] = None
    noise_cfg: Optional[str] = None
    adc_offset: Optional[float] = None
    channels: Optional[str] = None
    output_path: Optional[Path] = None
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class ConfigRequest:
    action: ConfigAction
    value: Optional[str] = None
    force: bool = False
    source: Optional[str] = None
    expected_revision: Optional[str] = None


@dataclass(frozen=True)
class RuleListRequest:
    rule_type: Optional[RuleType] = None


@dataclass(frozen=True)
class RuleReadRequest:
    rule_type: RuleType
    name: str
    variant: RuleSource = RuleSource.EFFECTIVE


@dataclass(frozen=True)
class RuleSaveRequest:
    rule_type: RuleType
    name: str
    source: str
    expected_revision: Optional[str] = None


@dataclass(frozen=True)
class OfflineCatalogRequest:
    chip_name: Optional[str] = None


@dataclass(frozen=True)
class EvaluateRequest:
    input_path: Path
    output_path: Path
    eval_type: str = "hr"
    ref_column: Optional[str] = None
    pred_column: Optional[str] = None
    ref_column_col: Optional[int] = None
    pred_column_col: Optional[int] = None
    chip: Optional[str] = None
    rule_file: Optional[str] = None
    diff_threshold: Optional[float] = None
    stale_minutes: Optional[float] = None
    filter_name: Optional[str] = None


@dataclass(frozen=True)
class OfflineRequest:
    input_path: Optional[Path] = None
    output_path: Optional[Path] = None
    chip_name: Optional[str] = None
    ver: Optional[str] = None
    versions: Optional[str] = None
    all_versions: bool = False
    hba_fs: Optional[int] = None
    scene_en: Optional[int] = None
    ch_num: Optional[int] = None
    ref_col: Optional[int] = None
    ppg_offset: int = 0
    ppg_maps: Tuple[str, ...] = ()
    no_accuracy: bool = False
    no_plot: bool = False
    no_run: bool = False
    do_list: bool = False
    timeout: int = 300
    settle_timeout: int = 10


@dataclass(frozen=True)
class CheckRequest:
    input_path: Optional[Path] = None
    chip_name: Optional[str] = None
    checks: Optional[str] = None
    tolerance: int = 50
    static_min: int = 5
    range_ratio: float = 1.0
    frame_ratio: float = 1.0
    center_ratio: float = 5.0
    ipd_ratio: float = 1.0
    acc_ratio: float = 1.0
    acc_axis: bool = False
    timestamp_column: Optional[str] = None
    timestamp_ratio: float = 20.0
    timestamp_ms: Optional[float] = None
    timestamp_fail_ratio: float = 1.0
    output_path: Optional[Path] = None
    sort_report: bool = False
    report_path: Optional[Path] = None
    sort_output: Optional[Path] = None
    workers: int = 4
