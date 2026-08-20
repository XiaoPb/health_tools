"""分析内部结果模型。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DiagnosisEvidence:
    """单条诊断证据。

    证据与最终原因结论分离，便于报告同时呈现支持和不足信息。
    算法来源的证据不携带 ``suggestions``，避免把机制判断误写成优化建议。
    """

    id: str
    title: str
    origin: str = "raw"
    confidence: float = 0.0
    evidence: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.confidence = float(max(0.0, min(1.0, self.confidence)))
        if self.origin == "algorithm":
            self.suggestions = []

    def to_dict(self) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "origin": self.origin,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "metrics": dict(self.metrics),
        }
        if self.origin != "algorithm":
            value["suggestions"] = list(self.suggestions)
        return value

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass
class AnalysisSegment:
    start_s: float
    end_s: float
    samples: int
    mean_error: float = 0.0
    max_error: float = 0.0


@dataclass
class AnalysisRecord:
    file: str
    source: str
    analysis_type: str
    scene: str = "unknown"
    activity: str = "other"
    focused: bool = False
    features: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    segments: List[AnalysisSegment] = field(default_factory=list)
    psd: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[Dict[str, Any]] = None
    conclusion: str = "证据不足"
    confidence: float = 0.0
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    figure: Optional[str] = None
    secondary_figure: Optional[str] = None
    plot_data: Dict[str, Any] = field(default_factory=dict, repr=False)
    scene_label: Optional[str] = None
    classification: List[str] = field(default_factory=list)
    channel_abnormal_ratio: Dict[str, float] = field(default_factory=dict)
    excluded: bool = False
    exclusion_reasons: List[str] = field(default_factory=list)

    @property
    def abnormal(self) -> bool:
        return self.conclusion not in {"未发现异常", "证据不足"} or bool(self.segments)

    @property
    def primary_classification(self) -> str:
        return self.classification[0] if self.classification else "normal"
