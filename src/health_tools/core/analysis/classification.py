"""分析结果分类与可配置规则匹配。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import yaml

DEFAULT_CATEGORIES = (
    "normal",
    "acc_warning",
    "centered",
    "other",
    "timestamp",
    "range_high",
    "range_low",
    "saturation",
    "near_zero",
    "agc_unstable",
    "reference_invalid",
    "algorithm_low_accuracy",
)


@dataclass(frozen=True)
class ClassificationRecord:
    file: str
    scene: str = "unknown"
    labels: Tuple[str, ...] = ()
    primary: str = "normal"
    channel_abnormal_ratio: Optional[Mapping[str, float]] = None
    excluded: bool = False
    exclusion_reasons: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        labels = tuple(dict.fromkeys(self.labels)) or (self.primary or "normal",)
        primary = self.primary if self.primary != "normal" or not self.labels else labels[0]
        if primary not in labels:
            labels = (primary, *labels)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "channel_abnormal_ratio", dict(self.channel_abnormal_ratio or {}))
        object.__setattr__(self, "exclusion_reasons", tuple(self.exclusion_reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "scene": self.scene,
            "labels": list(self.labels),
            "primary": self.primary,
            "channel_abnormal_ratio": dict(self.channel_abnormal_ratio),
            "excluded": self.excluded,
            "exclusion_reasons": list(self.exclusion_reasons),
        }


@dataclass(frozen=True)
class ClassificationRule:
    name: str
    pattern: str
    labels: Tuple[str, ...]
    priority: int = 0
    _regex: Optional[re.Pattern] = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("分类规则 name 不能为空")
        if not self.labels:
            raise ValueError(f"分类规则 {self.name} 至少需要一个 labels")
        try:
            compiled = re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(f"分类规则 {self.name} 的正则无效: {exc}") from exc
        object.__setattr__(self, "_regex", compiled)

    def matches(self, value: str) -> bool:
        return bool(self._regex and self._regex.search(value))


def _rule_from_item(item: Mapping[str, Any]) -> ClassificationRule:
    labels = item.get("labels", ())
    if isinstance(labels, str):
        labels = (labels,)
    return ClassificationRule(
        str(item.get("name", "")),
        str(item.get("pattern", "")),
        tuple(str(label) for label in labels),
        int(item.get("priority", 0)),
    )


def load_classification_rules(
    path: Optional[Union[str, Path]] = None,
    *,
    yaml_text: Optional[str] = None,
    cli: Sequence[str] = (),
) -> List[ClassificationRule]:
    """按 CLI > YAML 规则加载；CLI 格式为 name=regex，可重复。"""
    items: List[ClassificationRule] = []
    if path is not None or yaml_text is not None:
        data = (
            yaml.safe_load(yaml_text)
            if yaml_text is not None
            else yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        )
        categories = (data or {}).get("categories")
        if not isinstance(categories, list):
            raise ValueError("分类 YAML 必须包含 categories 列表")
        items.extend(_rule_from_item(item) for item in categories if isinstance(item, Mapping))
    for raw in cli:
        if "=" not in raw:
            raise ValueError(f"--classify 格式应为 name=regex: {raw}")
        name, pattern = raw.split("=", 1)
        name = name.strip()
        items.append(ClassificationRule(name, pattern, (name,), 10000))
    return sorted(items, key=lambda rule: rule.priority, reverse=True)


def classify_file(
    file: Union[str, Path],
    *,
    scene: str = "unknown",
    fields: Optional[Mapping[str, Any]] = None,
    rules: Iterable[ClassificationRule] = (),
) -> ClassificationRecord:
    text = str(file).replace("\\", "/")
    haystack = " ".join([text, scene, *(str(value) for value in (fields or {}).values())])
    labels: List[str] = []
    for rule in rules:
        if rule.matches(haystack):
            labels.extend(rule.labels)
    unique = tuple(dict.fromkeys(labels)) or ("normal",)
    return ClassificationRecord(text, scene, unique, unique[0])


def compact_classification_rows(records: Iterable[ClassificationRecord]) -> List[dict]:
    rows: List[dict] = []
    for record in records:
        ratio = 100.0 / len(record.labels) if record.labels else 100.0
        for label in record.labels:
            rows.append(
                {
                    "file": record.file,
                    "scene": record.scene,
                    "category": label,
                    "count": 1,
                    "ratio": ratio,
                    "channel": "",
                    "channel_ratio": "",
                    "excluded": record.excluded,
                }
            )
    return rows
