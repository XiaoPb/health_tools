"""分析内部结果模型。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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

    @property
    def abnormal(self) -> bool:
        return self.conclusion not in {"未发现异常", "证据不足"} or bool(self.segments)
