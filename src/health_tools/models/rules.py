"""规则数据类定义"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from health_tools.utils.columns import expand_columns


@dataclass
class ParsePattern:
    regex: str
    columns: List[str]
    separator: str = ","

    def __post_init__(self):
        self.columns = expand_columns(self.columns)
        self._compiled_regex = re.compile(self.regex)


@dataclass
class ParseRule:
    regex: str = ""
    columns: List[str] = field(default_factory=list)
    description: str = ""
    separator: str = ","
    chip: Optional[str] = None
    patterns: Dict[str, "ParsePattern"] = field(default_factory=dict)

    def __post_init__(self):
        self.columns = expand_columns(self.columns)
        if self.regex:
            self._compiled_regex = re.compile(self.regex)


@dataclass
class ChipRule:
    chip: str
    csv: dict
    columns: List[str]
    version: str = "1.0"
    factory_columns: List[str] = field(default_factory=list)
    factory_config: Dict[str, Any] = field(default_factory=dict)
    chip_info: Dict[str, Any] = field(default_factory=dict)
    gain_tia_map: Dict[str, Any] = field(default_factory=dict)
    hr_ref_column: Dict[str, int] = field(default_factory=dict)
    spo_ref_column: Dict[str, int] = field(default_factory=dict)
    acc_columns: Dict[str, str] = field(default_factory=dict)
    frame_column: str = ""
    check_columns: Dict[str, List[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.columns = expand_columns(self.columns)
        self.factory_columns = expand_columns(self.factory_columns)
        self.check_columns = {k: expand_columns(v) for k, v in self.check_columns.items()}

    @property
    def info_row(self) -> int:
        return int(self.csv.get("info_row", 0))

    @property
    def header_row(self) -> int:
        return int(self.csv.get("header_row", 1))

    @property
    def data_start_row(self) -> int:
        return int(self.csv.get("data_start_row", 2))

    @property
    def delimiter(self) -> str:
        return str(self.csv.get("delimiter", ","))

    @property
    def encoding(self) -> str:
        return str(self.csv.get("encoding", "utf-8"))

    @property
    def info(self) -> str:
        return str(self.csv.get("info", ""))


@dataclass
class ConvertRule:
    source_columns: List[str] = field(default_factory=list)
    target_columns: List[str] = field(default_factory=list)
    computed: Dict[str, str] = field(default_factory=dict)
    target_chip: Optional[str] = None
    description: str = ""
    column_mapping: Dict[str, str] = field(default_factory=dict)
    forward_fill: List[str] = field(default_factory=list)
    expand_repeat: Dict[str, int] = field(default_factory=dict)
    csv: Dict[str, Any] = field(default_factory=dict)
    extra_source: Dict[str, Any] = field(default_factory=dict)
    split: Dict[str, Any] = field(default_factory=dict)
    classify: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.source_columns = self._expand_columns(self.source_columns)
        self.target_columns = self._expand_columns(self.target_columns)
        self.column_mapping = self._expand_mapping(self.column_mapping)
        self.forward_fill = self._expand_columns(self.forward_fill)
        self.expand_repeat = self._expand_repeat_keys(self.expand_repeat)

    def _expand_columns(self, columns: List[str]) -> List[str]:
        return expand_columns(columns)

    def _expand_mapping(self, mapping: Dict[str, str]) -> Dict[str, str]:
        expanded = {}
        for src, tgt in mapping.items():
            src_expanded = self._expand_columns([src])
            tgt_expanded = self._expand_columns([tgt])
            if len(src_expanded) == len(tgt_expanded):
                for s, t in zip(src_expanded, tgt_expanded):
                    expanded[s] = t
            else:
                for s in src_expanded:
                    expanded[s] = tgt
        return expanded

    def _expand_repeat_keys(self, repeat: Dict[str, int]) -> Dict[str, int]:
        expanded = {}
        for key, value in repeat.items():
            for k in self._expand_columns([key]):
                expanded[k] = value
        return expanded

    @property
    def info_row(self) -> int:
        return int(self.csv.get("info_row", 0))

    @property
    def header_row(self) -> int:
        return int(self.csv.get("header_row", 1))

    @property
    def data_start_row(self) -> int:
        return int(self.csv.get("data_start_row", 2))

    @property
    def delimiter(self) -> str:
        return str(self.csv.get("delimiter", ","))

    @property
    def encoding(self) -> str:
        return str(self.csv.get("encoding", "utf-8"))


@dataclass
class DataColumn:
    name: str
    type: str = "string"
    column: Optional[str] = None
    column_index: Optional[int] = None
    source: str = "data"
    ranges: Dict[str, List[int]] = field(default_factory=dict)
    values: List[str] = field(default_factory=list)
    match: Dict[str, List[str]] = field(default_factory=dict)
    regex: Optional[str] = None
    group: Optional[int] = None
    compute: Optional[str] = None


@dataclass
class ClassifyRule:
    filename: Dict[str, Any] = field(default_factory=dict)
    path: Dict[str, Any] = field(default_factory=dict)
    data_columns: List[DataColumn] = field(default_factory=list)
    structure: Dict[str, str] = field(default_factory=dict)
    rules: List[Dict[str, Any]] = field(default_factory=list)
    default: str = "unclassified"
    extract: List[Dict[str, Any]] = field(default_factory=list)
    classify_rules: List[Dict[str, Any]] = field(default_factory=list)
    accuracy: Dict[str, Any] = field(default_factory=dict)
    target_chip: Optional[str] = None
    rename: Optional[str] = None
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluateRule:
    type: str = "hr"
    ref_column: str = "REF_RESULT0"
    pred_column: str = "ALGO_RESULT0"
    anomaly: Dict[str, Any] = field(default_factory=dict)
    classify: Dict[str, Any] = field(default_factory=dict)
    classify_rule: Optional[str] = None
    methods: List[str] = field(default_factory=list)
    thresholds: List[Dict[str, Any]] = field(default_factory=list)
    first_output_time: bool = False
    default_category: str = "other"
    description: str = ""

    @property
    def diff_threshold(self) -> float:
        return float(self.anomaly.get("diff_threshold", 30 if self.type == "hr" else 5))

    @property
    def stale_minutes(self) -> float:
        return float(self.anomaly.get("stale_minutes", 2))

    @property
    def sample_rate(self) -> float:
        return float(self.anomaly.get("sample_rate", 25))


@dataclass
class AnalysisRule:
    """受限的数据分析规则，不执行任意表达式。"""

    type: str = "hr"
    columns: Dict[str, Any] = field(default_factory=dict)
    detectors: List[str] = field(default_factory=list)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    causes: List[Dict[str, Any]] = field(default_factory=list)
    sampling: Dict[str, Any] = field(default_factory=dict)
    offline: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class AccuracyMarkRule:
    """check 准确度标定条件。"""

    id: str
    comparison: str
    metric: str
    category: str
    label: str
    min: Optional[float] = None
    min_gap: Optional[float] = None


@dataclass(frozen=True)
class CheckAccuracyRule:
    """check 的准确度列、指标和标定策略。"""

    enabled: bool = False
    ref_column: str = "REF_RESULT0"
    online_column: str = "ALGO_RESULT0"
    comp_column: Optional[str] = "COMP_RESULT0"
    methods: Tuple[str, ...] = (
        "mae",
        "within_5",
        "within_10",
        "within_15",
        "rmse",
        "correlation",
    )
    thresholds: Tuple[Dict[str, Any], ...] = ()
    inclusive: bool = False
    marks: Tuple[AccuracyMarkRule, ...] = ()


@dataclass(frozen=True)
class CheckRatiosRule:
    """check 各检查项允许的异常比例。"""

    range: float = 1.0
    frame: float = 1.0
    center: float = 5.0
    ipd: float = 1.0
    acc: float = 1.0


@dataclass(frozen=True)
class CheckTimestampRule:
    """check 时间戳间隔检查策略。"""

    column: Optional[str] = None
    ratio: float = 20.0
    ms: Optional[float] = None
    fail_ratio: float = 1.0
    base_ms: Optional[float] = None


@dataclass(frozen=True)
class CheckReferenceRule:
    """check 金标检查策略。"""

    hr_column: Optional[str] = None
    spo2_column: Optional[str] = None
    sample_rate: float = 25.0
    stale_seconds: float = 5.0
    step_threshold: float = 8.0


@dataclass(frozen=True)
class CheckRule:
    """check 规则的可复用业务策略。

    ``values`` 保留 YAML 中除准确度外的业务配置，运行时路径、sort 控制和并行参数不属于
    规则。通过属性提供强类型访问，兼容后续 CLI/API 的配置合并。
    """

    version: str = "1.0"
    description: str = ""
    chip: Optional[str] = None
    values: Dict[str, Any] = field(default_factory=dict)
    accuracy: CheckAccuracyRule = field(default_factory=CheckAccuracyRule)

    @property
    def checks(self) -> Tuple[str, ...]:
        configured = self.values.get(
            "checks",
            ("range", "ipd", "frame", "center", "acc", "agc", "ref"),
        )
        return tuple(str(value) for value in configured)

    @property
    def tolerance(self) -> int:
        return int(self.values.get("tolerance", 50))

    @property
    def static_min(self) -> int:
        return int(self.values.get("static_min", 5))

    @property
    def ratios(self) -> CheckRatiosRule:
        configured = self.values.get("ratios", {})
        if not isinstance(configured, dict):
            configured = {}
        return CheckRatiosRule(
            range=float(configured.get("range", 1.0)),
            frame=float(configured.get("frame", 1.0)),
            center=float(configured.get("center", 5.0)),
            ipd=float(configured.get("ipd", 1.0)),
            acc=float(configured.get("acc", 1.0)),
        )

    @property
    def acc_axis(self) -> bool:
        return bool(self.values.get("acc_axis", False))

    @property
    def timestamp(self) -> CheckTimestampRule:
        configured = self.values.get("timestamp", {})
        if not isinstance(configured, dict):
            configured = {}
        return CheckTimestampRule(
            column=configured.get("column"),
            ratio=float(configured.get("ratio", 20.0)),
            ms=configured.get("ms"),
            fail_ratio=float(configured.get("fail_ratio", 1.0)),
            base_ms=configured.get("base_ms"),
        )

    @property
    def reference(self) -> CheckReferenceRule:
        configured = self.values.get("reference", {})
        if not isinstance(configured, dict):
            configured = {}
        return CheckReferenceRule(
            hr_column=configured.get("hr_column"),
            spo2_column=configured.get("spo2_column"),
            sample_rate=float(configured.get("sample_rate", 25.0)),
            stale_seconds=float(configured.get("stale_seconds", 5.0)),
            step_threshold=float(configured.get("step_threshold", 8.0)),
        )

    @property
    def scene_regex(self) -> Optional[str]:
        value = self.values.get("scene_regex")
        return str(value) if value is not None else None
